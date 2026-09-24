"""audition —— 签约新演员:一句话人设 → 人设卡(LLM)→ 试镜照 → 全套资料包入库.

候选区 = 工坊/候选/<名字>/;pool.scan 只迭代 素材/,故候选对招聘 agent 不可见。
签约 = 补齐 三视图+三件套 后搬入 素材/,pool 立即可选(动态扫描,免重启)。

状态从文件推导,零额外状态文件:
  有 角色提示词.md            → 待试镜
  有 0_试镜/audition.png      → 试镜照就绪
  有 1_设定图/三视图.png      → 签约资料生成中/完成
"""
import random
import re
import shutil
import time
from pathlib import Path

from . import config, llm, qwenimage

CANDIDATES = config.WORKSHOP / "候选"

# v4 写实系三视图模板壳(角色E_莉亚.md 实证通过的那套,逐字保留要点)
TURNAROUND_TMPL = (
    "Professional studio photography: full-body character reference photos of a real "
    "young Chinese adult (East Asian features) in the early twenties, shot for a "
    "live-action film production, styled "
    "like a trendy modern game-character cosplay photoshoot. The same person photographed "
    "three times side by side: front view, side view and back view, standing in a relaxed "
    "neutral A-pose, aligned on the same ground line, identical person in all three photos. "
    "This person is {anchor}. Well-fitted modern tailoring. Shot on a Canon EOS R5, 85mm "
    "lens at f/2.8, flattering soft beauty lighting, true-to-life colors, realistic fabric "
    "weave and texture, plain light gray seamless studio backdrop, sharp focus")

TURNAROUND_NEG = ("模糊, 低分辨率, 失焦, 畸变的手指和四肢, 文字乱码, 三个视角外观不一致, "
                  "构图错乱, 显老, 中年感, 法令纹, 眼袋, 粗糙暗沉的皮肤, 服装老气过时, "
                  "臃肿拖沓的款式, 廉价感, 塑料感皮肤, 过度磨皮, 蜡像感, CG渲染, 3D渲染, "
                  "插画, 动漫风格, 洋娃娃感, 过度饱和, 浓重美颜滤镜, "
                  "欧美人长相, 西方面孔, 高加索特征, 深眼窝高鼻梁的欧美立体脸, 金发碧眼, "
                  "成熟妇女感, 大龄感, 严肃刻板面相")

CARDS_SYSTEM = """你是影视选角导演,为本地短剧工坊签约新演员设计人设卡。审美铁律与硬性规范:
0) 审美铁律(最高优先级): 一律**中式审美东亚面孔**——FACE DNA 必须显式写
   Chinese/East Asian features(如 a sweet Chinese young woman / a handsome young Chinese man),
   面相走 清新甜美(女)/阳光帅气(男) 路线,参考国产青春剧选角;
   禁止欧美面孔、西方成熟感长相,禁止老气横秋的面相描述;
1) 一律成年人:FACE 里显式写 20-28 岁之间的年龄锚点(如 a 23-year-old Chinese young woman);
2) FACE DNA 为一段英文:东亚长相特征(dark expressive eyes, soft smooth East Asian facial
   features 类),情绪词必须正向(bright/warm/cheerful/sweet 类,禁 moody/brooding/gloomy),
   发色以黑发/深棕为主(彩发写成 realistic dyed hair),非自然瞳色写 colored contact lenses,
   皮肤写 natural pores/fine texture 等写实描述;女性可加 sweet dimples/gentle smile 类甜美特征,
   男性可加 sharp jawline yet boyish charm 类清爽帅气特征;
3) 默认穿搭为一段英文:现代合身版型,材质具体(棉/羊毛/牛仔等),符合中式日常审美,与气质匹配;
4) 多张卡之间气质、年龄感、发型、服装风格必须明显错开,不许同质化;
5) name 是中文艺名,2-4 个字;
6) positioning_cn 一句话中文定位(适合演什么类型角色)。
只输出 JSON,不要任何多余文字。"""

NAME_RE = re.compile(r"^[\w\u4e00-\u9fff-]{1,24}$")


# ---------------------------------------------------------------- 人设卡(LLM,零 GPU)
def make_cards(requirement, count=3):
    """招聘要求 → count 张差异化人设卡(仅文本,不落盘不花钱)."""
    from . import pool as sd_pool
    existing = ", ".join(c["name"] for c in sd_pool.scan_all()) or "无"
    user = (f"【招聘要求】\n{requirement}\n\n【现有演员(避免撞型)】\n{existing}\n\n"
            f"产出 {count} 张人设卡。只输出 JSON:\n"
            '{"cards": [{"name": "中文艺名", "positioning_cn": "一句话定位", '
            '"face_dna": "英文一段", "outfit_dna": "英文一段"}]}')
    d = llm.chat_json(config.LLM_TEXT, CARDS_SYSTEM, user)
    cards, seen = [], set()
    for c in d.get("cards", [])[:count]:
        name = _safe_name(str(c.get("name", "")).strip())
        if not name or name in seen:
            continue
        face = re.sub(r"\s+", " ", str(c.get("face_dna", ""))).strip()
        outfit = re.sub(r"\s+", " ", str(c.get("outfit_dna", ""))).strip()
        if len(face) < 40 or len(outfit) < 20:
            continue
        seen.add(name)
        cards.append({"name": name, "positioning_cn": str(c.get("positioning_cn", "")).strip(),
                      "face_dna": face, "outfit_dna": outfit,
                      "seed": random.randint(1_000_000, 9_999_999)})
    if not cards:
        raise RuntimeError("LLM 未产出合格人设卡,请重试或改写招聘要求")
    return cards


def _safe_name(name):
    name = name.split("/")[0].split("\\")[0].strip()
    return name if NAME_RE.match(name) else ""


# ---------------------------------------------------------------- 候选区管理
def _cdir(name):
    return CANDIDATES / name


def create_candidate(card):
    """人设卡 → 候选目录(标准 角色提示词.md,pool.scan 兼容格式)."""
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    d = _cdir(card["name"])
    if d.exists():
        i = 2
        while (CANDIDATES / f"{card['name']}{i}").exists():
            i += 1
        card = {**card, "name": f"{card['name']}{i}"}
        d = CANDIDATES / card["name"]
    d.mkdir(parents=True)
    (d / "角色提示词.md").write_text(_card_md(card), encoding="utf-8")
    print(f"[签约] 候选 {card['name']} 已建档")
    return d, card


def _card_md(card):
    return f"""# {card['name']} — 提示词档案(工坊候选)

> 定位:{card.get('positioning_cn', '')}

## 身份锚点

**FACE**:
> {card['face_dna']}

**默认穿搭**:
> {card['outfit_dna']}

**seed:{card['seed']}**　**风格后缀**:`photorealistic real-person style, cinematic photography, detailed realistic skin and fabric texture, even soft studio lighting, shot on 85mm lens, sharp focus`
"""


def char_of(name):
    """候选目录 → qwenimage 需要的 char dict."""
    d = _cdir(name)
    md = (d / "角色提示词.md").read_text(encoding="utf-8")

    def block(tag):
        m = re.search(tag + r"[^\n]*\n+\s*((?:>[^\n]*\n?)+)", md)
        return " ".join(l.lstrip("> ").strip() for l in m.group(1).splitlines()) if m else ""

    seed = re.search(r"seed[：:]\s*(\d+)", md)
    return {"name": name, "dir": str(d),
            "face_dna": block(r"\*\*FACE\*\*") or "a young adult",
            "outfit_dna": block(r"\*\*默认穿搭") or "casual modern outfit",
            "seed": int(seed.group(1)) if seed else config.CHAR_SEED_BASE,
            "refs": {}}


def list_candidates():
    if not CANDIDATES.exists():
        return []
    out = []
    for d in sorted(CANDIDATES.iterdir()):
        if not d.is_dir() or not (d / "角色提示词.md").exists():
            continue
        c = char_of(d.name)
        c["audition"] = str(d / "0_试镜" / "audition.png") if (d / "0_试镜" / "audition.png").exists() else None
        c["attempts"] = len(list((d / "0_试镜").glob("*.png"))) if (d / "0_试镜").exists() else 0
        c["has_package"] = (d / "2_视频参考" / "01_正面特写.png").exists()
        c["status"] = ("资料就绪" if c["has_package"]
                       else "试镜照就绪" if c["audition"] else "待试镜")
        m = re.search(r"定位[：:]\s*(.+)", (d / "角色提示词.md").read_text(encoding="utf-8"))
        c["positioning_cn"] = m.group(1).strip() if m else ""
        c["created"] = time.strftime("%F %T", time.localtime(d.stat().st_mtime))
        out.append(c)
    return out


def discard(name):
    d = _cdir(name)
    if not d.exists() or CANDIDATES not in d.resolve().parents:
        raise KeyError(f"没有候选 {name}")
    shutil.rmtree(d)
    return True


# ---------------------------------------------------------------- 生成(走 GPU)
def audition_photo(char, attempt=None):
    """单种子锁脸试镜照 → 0_试镜/audition.png(重掷=新 attempt)."""
    out = Path(char["dir"]) / "0_试镜"
    out.mkdir(parents=True, exist_ok=True)
    _wait_gpu_free(char["dir"])
    attempt = attempt if attempt is not None else len(list(out.glob("*.png")))
    seed = char["seed"] + 991 * attempt
    face, outfit = char["face_dna"], char["outfit_dna"]
    makeup = ("natural fresh makeup, healthy rosy complexion, a warm friendly expression"
              if "少年" not in face and "girl" not in face.lower()
              else "natural fresh complexion, lively curious expression")
    prompt = qwenimage.CLOSEUP_TMPL.format(face=face, outfit=outfit, makeup=makeup)
    dst = out / "audition.png"
    print(f"[签约] {char['name']} 试镜照 seed={seed}(attempt {attempt + 1})…")
    qwenimage._gen_one(prompt, seed, dst, steps=25, width=1024, height=1280)
    return dst


def _wait_gpu_free(char_dir, timeout=1200):
    """等同一角色目录的孤儿 imagegen 子进程跑完(服务重启遗留),防双占卡.

    匹配必须含 imagegen/bin/python(排除恰好含有该文本的 bash 包装命令),
    且命令行里带本角色目录(临时脚本路径即目录内)。
    """
    import subprocess as _sp
    import time as _t
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        r = _sp.run(["pgrep", "-af", "imagegen/bin/python"],
                    capture_output=True, text=True)
        busy = [l for l in (r.stdout or "").splitlines()
                if str(char_dir) in l and "/bin/bash -c" not in l]
        if not busy:
            return
        print(f"[签约] 等待遗留 GPU 子进程完成: {busy[0][:80]}…")
        _t.sleep(10)
    print("[签约] 等待超时,继续执行(注意可能有并行占卡)")


def gen_turnaround(char, seed=None, steps=40, width=2528, height=1696, force=False):
    """Qwen-Image-2.1 三视图(正/侧/背 横排)→ 1_设定图/三视图.png,VLM 自检一次.

    断点续跑: 三视图已存在时仍做 VLM 自检,通过才跳过;未过则重新生成.
    """
    out = Path(char["dir"]) / "1_设定图"
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "三视图.png"
    if dst.exists() and not force:
        ok0, reason0 = _vlm_check_turnaround(dst, char)
        if ok0:
            print(f"[签约] 三视图已存在且自检通过,跳过生成(断点续跑): {dst}")
            return dst
        print(f"[签约] 已有三视图自检未过({reason0}),重新生成…")
    _wait_gpu_free(char["dir"])
    anchor = f"{char['face_dna']}, wearing {char['outfit_dna']}"
    prompt = TURNAROUND_TMPL.format(anchor=anchor)
    seed = seed or char["seed"]
    qwenimage._gen_one(prompt, seed, dst, steps=steps, width=width, height=height,
                       neg=TURNAROUND_NEG, timeout=2700)
    ok, reason = _vlm_check_turnaround(dst, char)
    if not ok:
        print(f"[签约] 三视图自检未过({reason}),换 seed 重掷一次…")
        qwenimage._gen_one(prompt, seed + 88, dst, steps=steps, width=width, height=height,
                           neg=TURNAROUND_NEG, timeout=2700)
        ok, reason = _vlm_check_turnaround(dst, char)
        if not ok:
            raise RuntimeError(f"三视图两次未过自检: {reason}")
    return dst


def _vlm_check_turnaround(png, char):
    text = ("这张图应是同一人的三视图(正面/侧面/背面横排,A-pose,同一地面线)。"
            f"角色设定: {char['face_dna'][:200]}\n"
            '只输出 JSON: {"same_person": true/false, "three_views": true/false, "reason": "一句话"}')
    try:
        d = llm.extract_json(llm.vision(text, [str(png)]))
    except Exception as e:
        return True, f"VLM 不可用,放行({e})"
    ok = bool(d.get("same_person")) and bool(d.get("three_views"))
    return ok, d.get("reason", "")


def full_package(char):
    """签约全链: 三视图 → 裁正/侧身 → 3种子特写 VLM 选优."""
    _wait_gpu_free(char["dir"])
    gen_turnaround(char)
    qwenimage.crop_views(Path(char["dir"]), Path(char["dir"]) / "2_视频参考")
    refs = qwenimage.buildrefs(char)
    print(f"[签约] {char['name']} 全套资料完成: {sorted(refs)}")
    return refs


def _next_letter():
    used = set()
    if (config.WORKSHOP / "素材").exists():
        for d in (config.WORKSHOP / "素材").iterdir():
            m = re.match(r"^角色([A-Z])_", d.name)
            if m:
                used.add(m.group(1))
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if ch not in used:
            return ch
    return random.choice("XYZ")


def sign(name, name_override=None):
    """候选 → 正式演员:全链生成后搬入 素材/角色X_名字."""
    char = char_of(name)
    full_package(char)
    final = name_override or name
    final = _safe_name(final) or name
    letter = _next_letter()
    dst = config.WORKSHOP / "素材" / f"角色{letter}_{final}"
    i = 2
    while dst.exists():
        dst = config.WORKSHOP / "素材" / f"角色{letter}_{final}{i}"
        i += 1
    shutil.move(str(_cdir(name)), str(dst))
    print(f"[签约] {name} 已入库 → {dst.name}(招聘 agent 立即可选)")
    return dst.name
