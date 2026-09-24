"""编剧 agent —— 分场剧本: 生成端硬约束写进剧本 + 旁白 + SRT 草稿."""
import json

from . import config, llm

SYSTEM = """你是短剧编剧。你写的每个字都会被 AI 视频模型逐字执行,所以生成端的硬约束必须
在编剧阶段就写进剧本,绝不事后改。只输出 JSON。

【硬约束(全部强制)】
1. 每镜固定 {SHOT_SECONDS:.2f} 秒(121帧@24fps),不可变
2. 每镜动作 = 1 个主爆发动作 + 最多 1 个次要节点 + 收势静止(共≤3 节点,写多了 AI 执行必崩);
   禁止 then/接着 连缀 3 个以上动作;动作要"可默读"——观众一眼看懂
3. 每镜单一连续运镜(推近/拉远/环绕/跟随 四选一),主体保持画面中央三分之一(竖版要中心裁切)
4. 旁白每镜 ≤ 25 个汉字(约4-5字/秒,不溢出镜头)
5. 对白镜头只许背影/侧脸/远景;正面说话必穿帮,一律改旁白
6. 手部弱化:动作描述避免手部特写/摸脸/数钱,用持物/袖口/口袋代替
7. 音乐已由物料定了 BPM,全剧逐字复用,你不写音乐
8. 场景必须用物料给的场景 DNA,不新造地点
9. 第 1 镜前 3 秒必须是强钩子(悬念画面/强烈视觉反差/情绪冲击),短视频完播率取决于此
"""

CRITIC_SYSTEM = ("你是短剧剧本评审。从短视频完播率角度严格打分(0-10):"
                 "hook=开头3秒钩子强度, arc=情绪弧线与起承转合, narration=旁白文学性与字数节奏,"
                 "visual=画面可拍性(动作爆发点/光线/景别变化/结尾记忆点)。只输出 JSON。")


def run(proj, force=False):
    if proj.stage_done("script") and not force:
        return proj.load_stage("script")
    brief = (proj.path / "brief.txt").read_text().strip()
    cast, mats = proj.load_stage("cast"), proj.load_stage("materials")
    n = proj.load_state()["shots"]
    cast_lines = "\n".join(
        f"- {r['story_role']}: {r['char']} | DNA: {r['profile']['face_dna']} | 穿搭: {r['profile']['outfit_dna']}"
        for r in cast["cast"])
    lead_name = cast["cast"][0]["char"]
    scene_lines = "\n".join(f"- {s['id']}: {s['dna_en']} (灯光:{s.get('light_cn','')})" for s in mats["scenes"])
    user = f"""【故事梗概】
{brief}

【演员(外观DNA逐字块)】
{cast_lines}

【场景库(逐字DNA)】
{scene_lines}
【全剧风格】{mats.get('style_note_en', 'photorealistic cinematic still, real scene')}

写一部 {n} 镜短剧(每镜 {config.SHOT_SECONDS:.2f}s,总片长 {n * config.SHOT_SECONDS:.1f}s)。
结构: 起(约1/3) 承(约1/3) 转+合(约1/3),结尾留一个视觉记忆点动作。

每镜输出:
- id: "q1".."q{n}"
- scene: 场景id(S1..)
- cast: 该镜出场角色,从【演员】的列表里按名字选,**单镜最多 2 人**(能 1 人就 1 人);
  纯场景空镜/转场镜给空数组 [](**全剧最多 1 镜**,须从物料 b_roll 选景)
- shot_en: 英文,景别+单一连续运镜+central third 构图(竖版安全)
- action_en: 英文,2-3 个爆发点动作+慢过渡,无手部特写,正脸不说话(对白转旁白或背影/侧脸);双角色镜动作用 "{{名1}}…" "{{名2}}…" 分述
- emotion_cn: 情绪(中文2-4字)
- narration_cn: 旁白 ≤25 汉字(可空字符串表示纯环境镜)

只输出 JSON:
{{"title_cn": "剧名(4-8字)", "logline": "一句话故事",
 "shots": [{{"id": "q1", "scene": "S1", "cast": ["{lead_name}"], "shot_en": "...", "action_en": "...",
   "emotion_cn": "...", "narration_cn": "..."}}],
 "ending_memory": "结尾视觉记忆点说明"}}"""
    system = SYSTEM.format(SHOT_SECONDS=config.SHOT_SECONDS)
    data = llm.chat_json(config.LLM_TEXT, system, user)
    # ── 自评-修订闭环: 评审打分,任一维 <7 则带反馈修订,最多两轮 ──
    critique_log = []
    for rnd in range(1, 3):
        critique = llm.chat_json(
            config.LLM_FAST, CRITIC_SYSTEM,
            "【剧本】\n" + json.dumps(data, ensure_ascii=False) +
            '\n\n只输出 JSON: {"hook":0-10,"arc":0-10,"narration":0-10,"visual":0-10,'
            '"issues":["具体问题1","具体问题2"]}')
        dims = {k: critique[k] for k in ("hook", "arc", "narration", "visual")}
        critique_log.append({"round": rnd, "scores": dims, "issues": critique.get("issues", [])})
        print(f"[编剧] 自评 R{rnd}: {dims}")
        if all(v >= 7 for v in dims.values()):
            break
        data = llm.chat_json(
            config.LLM_TEXT, system,
            user + "\n\n【你上一稿的评审反馈,逐条修复】\n" + json.dumps(critique, ensure_ascii=False))
    data["critique"] = critique_log
    shots = data["shots"]
    if len(shots) != n:
        raise ValueError(f"镜数不符: 要求{n} 实得{len(shots)}")
    cast_names = [r["char"] for r in cast["cast"]]
    max_empty = max(1, round(n * 0.4))          # 空镜占比上限 ~40%
    n_empty = 0
    for i, s in enumerate(shots, 1):
        if s["scene"] not in {x["id"] for x in mats["scenes"]}:
            raise ValueError(f"{s['id']} 引用了不存在的场景 {s['scene']}")
        if len(s.get("narration_cn") or "") > 25:
            s["narration_cn"] = s["narration_cn"][:25]   # 超字自动截断,不整轮报废
        names = s.get("cast", None)
        if names is None:
            names = [cast_names[0]]       # 缺省=主角单人镜
        names = names[:2]
        if not names:
            n_empty += 1
            if n_empty > max_empty:       # 超额空镜自动改为主角单人镜(从后往前保前面的)
                s["cast"] = [cast_names[0]]
                s["action_en"] = (s.get("action_en", "") + " "
                                  f"{cast_names[0]} stands quietly in this scene, seen from behind.")
                continue
        bad = [x for x in names if x not in cast_names]
        if bad:
            raise ValueError(f"{s['id']} 出场了未选角的人物: {bad}")
        s["cast"] = names
        s.setdefault("shot_en", "")
        s.setdefault("action_en", "")
    data["shot_ids"] = [s["id"] for s in shots]
    _write_srt(proj, data)
    proj.save_stage("script", data, meta={"shots": n, "title": data.get("title_cn", "")})
    return data


def _write_srt(proj, data):
    """旁白直接当字幕草稿: 第 i 镜时间窗 = [(i-1)*5.04, i*5.04)."""
    def ts(sec):
        h, m = int(sec // 3600), int(sec % 3600 // 60)
        s, ms = int(sec % 60), int(round((sec % 1) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    lines, idx = [], 0
    for i, shot in enumerate(data["shots"], 1):
        t0, t1 = (i - 1) * config.SHOT_SECONDS, i * config.SHOT_SECONDS
        text = (shot.get("narration_cn") or "").strip()
        if text:
            idx += 1
            lines.append(f"{idx}\n{ts(t0 + 0.3)} --> {ts(t1 - 0.2)}\n{text}\n")
    (proj.path / "narration.srt").write_text("\n".join(lines))
