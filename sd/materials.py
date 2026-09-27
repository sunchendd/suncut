"""服化道 agent —— 场景 DNA / 全剧统一音乐块 / 道具清单(供分镜逐字复用的英文封闭块).

支持从「短剧资产库」预选场地/道具(项目 assets.json):
锁定场地逐字使用,只让 LLM 补缺;产出自动归档回资产库(harvest),越用越富。
"""
import json

from . import assetlib, config, llm

SYSTEM = ("你是短剧美术指导。产出的是『逐字块』: 下游分镜会原样粘贴、绝不改写,"
          "所以每块必须自成一体、封闭、具体(可枚举的物件优先于抽象形容词)。只输出 JSON。")


def run(proj, force=False):
    if proj.stage_done("materials") and not force:
        return proj.load_stage("materials")
    brief = (proj.path / "brief.txt").read_text().strip()
    cast = proj.load_stage("cast")
    cast_lines = "\n".join(
        f"- {r['story_role']}: {r['char']} | {r['profile']['face_dna'][:120]}... | {r.get('wardrobe_note', '')}"
        for r in cast["cast"])

    # ── 资产库预选(assets.json): 锁定场地逐字复用,道具设为必用 ──
    picks = proj.load_assets_pick()
    lib_scenes, lib_props = [], []
    for sid in (picks.get("scenes") or [])[:4]:
        s = assetlib.get("scene", sid)
        if s:
            lib_scenes.append(s)
    for pid in (picks.get("props") or [])[:6]:
        p = assetlib.get("prop", pid)
        if p:
            lib_props.append(p)

    n_total = max(2, min(4, proj.load_state()["shots"]))
    n_gen = max(0, n_total - len(lib_scenes))
    locked = "\n".join(
        f"- {s['name_cn']}: {s['dna_en']} (灯光:{s.get('light_cn', '')})"
        for s in lib_scenes) or "(无)"
    must_props = "\n".join(f"- {p['name_cn']}: {p.get('desc_en', '')}" for p in lib_props) or "(无)"

    user = f"""【故事梗概】
{brief}

【已定演员】
{cast_lines}

【从场地库锁定的场景(dna_en 逐字使用,禁止改写)】
{locked}

【必用道具库(新造场景的 props 优先从这里选,写中文名)】
{must_props}

为整部短剧准备服化道。要求:
1. scenes: 新造 {n_gen} 个场景({"不新造,输出空数组" if n_gen == 0 else "必须有变化"}),每个场景给 name_cn(中文名2-6字)、一句**封闭英文场景DNA**(地点+显式点光源+氛围,如灯笼/霓虹灯箱/橱窗灯/路灯/月光/火光),点光源是硬要求;**DNA 里禁止任何可读文字**(招牌/海报/贴纸一律 no readable text 或模糊)——同场景多镜共用这张 DNA 锁美术一致
2. music_en: 全剧统一音乐块(英文): 风格 + {config.DEFAULT_BPM} BPM 固定,写明鼓点落在每一拍;全剧逐字复用只许改乐器点缀
3. props: 每个新造场景 1-2 个道具,能反复出现的视觉记忆点优先;写"中文名-英文一句描述";**道具表面一律 no readable text**(信纸/工牌等可读内容由后期字幕呈现,不在道具上画字);关键道具注明复用建议(如"贯穿全剧的信封:蜡封特写/拆封/贴胸口袋三次复用")
4. b_roll: 1-2 个空镜DNA(纯场景无人物,强化点光源氛围,供开场/转场),英文一句

只输出 JSON:
{{"scenes": [{{"name_cn": "雨夜便利店", "dna_en": "a small convenience store interior at night, ...",
              "light_cn": "冷白荧光灯+门口暖霓虹", "props": ["透明雨伞-a transparent umbrella, ..."]}}],
 "b_roll": [{{"id": "B1", "dna_en": "empty rain-soaked street at night, one warm streetlamp ..."}}],
 "music_en": "lo-fi city pop beat at {config.DEFAULT_BPM} BPM, soft kick drum on every beat, ...",
 "style_note_en": "photorealistic cinematic still, real scene"}}"""
    gen = llm.chat_json(config.LLM_TEXT, SYSTEM, user)

    # ── 合成: 锁定场景在前(逐字),新造场景在后;统一编号 S1..Sn ──
    scenes = []
    for s in lib_scenes:
        scenes.append({"name_cn": s["name_cn"], "dna_en": s["dna_en"],
                       "light_cn": s.get("light_cn", ""), "props": [],
                       "from_lib": s["id"]})
    for s in gen.get("scenes", [])[:n_gen]:
        if not (s.get("dna_en") or "").strip():
            continue
        scenes.append({"name_cn": (s.get("name_cn") or "")[:12] or "场景",
                       "dna_en": s["dna_en"].strip(),
                       "light_cn": s.get("light_cn", ""),
                       "props": [str(p) for p in s.get("props", [])][:2]})
    for i, s in enumerate(scenes, 1):
        s["id"] = f"S{i}"
    if len(scenes) < 2:
        raise ValueError(f"场景总数不足(库锁定+新造仅 {len(scenes)} 个),重跑 materials")

    data = {"scenes": scenes,
            "b_roll": gen.get("b_roll", [])[:2],
            "music_en": gen["music_en"],
            "style_note_en": gen.get("style_note_en", "photorealistic cinematic still, real scene"),
            "locked_from_lib": [s["name_cn"] for s in lib_scenes],
            "must_props": [p["name_cn"] for p in lib_props]}
    dna = " ".join(s["dna_en"] for s in scenes).lower()
    for kw in ("light", "neon", "lantern", "lamp", "glow", "moon", "fluorescent"):
        if kw in dna:
            break
    else:
        raise ValueError("场景 DNA 缺点光源关键词,重跑 materials")
    # 新产出归档回资产库(按 name_cn 去重;只归档新造场景)
    try:
        made = assetlib.harvest({"scenes": [s for s in scenes if not s.get("from_lib")],
                                 "props": _parse_props(scenes)}, source=proj.name)
        data["archived"] = made
    except Exception as e:                       # 归档失败不阻塞主流程
        data["archived"] = {"error": str(e)[:120]}
    proj.save_stage("materials", data, meta={"scenes": [s["id"] for s in scenes]})
    return data


def _parse_props(scenes):
    """scenes[].props 的 "中文名-英文描述" 字符串 → harvest 需要的对象."""
    out, seen = [], set()
    for s in scenes:
        for p in s.get("props", []):
            name, _, desc = str(p).partition("-")
            name = name.strip()
            if name and name not in seen:
                seen.add(name)
                out.append({"name_cn": name, "desc_en": desc.strip() or name})
    return out
