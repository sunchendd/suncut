"""编剧 agent —— 两段式: 叙事大纲(钩子/情绪曲线/意象库) → 分镜剧本.

D 轮框架升级(2026-09-26): ①大纲层先行,冷开场钩子铁律(3 秒内高潮/低谷);
②意象引擎——每镜至少一个可拍视觉记忆点,拒绝"站着感受";③人称一致性/说的必须拍到/
相邻镜去重三条 lint 进修订闭环;④duration_hint(short 快切/std)供制片剪辑表破等长节奏.
"""
import json

from . import config, creative_skills, llm, lint

SYSTEM = """你是短剧编剧。你写的每个字都会被 AI 视频模型逐字执行,所以生成端的硬约束必须
在编剧阶段就写进剧本,绝不事后改。只输出 JSON。

【硬约束(全部强制)】
1. 每镜生成素材上限 {SHOT_SECONDS:.2f} 秒；交付剪辑用 edit_in_s + edit_duration_s 决定，
   edit_duration_s 必须是 1.2~4.9 秒的连续值。只在动作落点、视线转移、声音桥或反应落地时切，
   禁止把全片写成两档等长。duration_hint 仅为旧项目兼容字段
2. 每镜动作 = 1 个主爆发动作 + 最多 1 个次要节点 + 收势静止(共≤3 节点,写多了 AI 执行必崩);
   禁止 then/接着 连缀 3 个以上动作;动作要"可默读"——观众一眼看懂
3. 每镜单一连续运镜(推近/拉远/环绕/跟随 四选一),主体保持画面中央三分之一(竖版要中心裁切);
   相邻镜景别必须跳变(远全/中近/特写交替),禁止连续同景别
4. 旁白每镜 ≤ 25 个汉字(约4-5字/秒,不溢出镜头);**全剧叙事人称唯一**(全"我"或全"他",混用必打回)
5. 台词(dialogue):关键情节点用角色台词推戏,后期配音呈现 —— 画面绝不拍正面对嘴
   (只许背影/侧脸/远景/画外);每镜 ≤ 2 句、每句 ≤ 18 字;who 填该镜出场角色的 story_role;
   同一镜「台词+旁白」合计 ≤ 25 字,二选一优先台词
6. 手部弱化:动作描述避免手部特写/摸脸/数钱,用持物/袖口/口袋代替
7. **双主体镜降级**:两人同框时严禁递物/接触交互(AI 融合形变事故源)——一主体完成动作,
   另一主体静立/背对;物品要么已在桌面,要么在自己手里
8. **说的必须拍到**:台词/旁白点名的关键道具(信封/工牌/种子…)必须写进同镜 action_en,
   绝不"用嘴说、不用画面演"
9. 音乐已由服化道定了 BPM,全剧逐字复用,你不写音乐
10. 场景必须用服化道给的场景 DNA,不新造地点
11. 第 1 镜前 3 秒必须是强钩子(悬念画面/强烈视觉反差/情绪冲击),短视频完播率取决于此
12. **意象优先**:每镜至少一个可拍视觉记忆点(象征物/光影事件/动作爆发)——从大纲的
    imagery_bank 取材,空泛的"站着感受/望着远方"是废拍
"""

CRITIC_SYSTEM = ("你是短剧剧本评审。从短视频完播率角度严格打分(0-10):"
                 "hook=开头3秒钩子强度(首拍是否直接落在高潮/低谷,平静开场≤4), "
                 "arc=情绪弧线与起承转合(每段必有峰值拍与落点拍), "
                 "narration=台词与旁白(配音可演性/文学性/字数节奏/人称统一),"
                 "visual=画面可拍性(动作爆发点/意象记忆点/景别跳变/说的必须拍到)。只输出 JSON。")


OUTLINE_SYSTEM = """你是短剧叙事架构师。先搭骨架后填肉: 输出一份可独立审阅的叙事大纲。
铁律: ①第 1 拍必须直接落在高潮或低谷(死亡/冲突/强烈反差/悬念画面),绝不平静开场;
②每拍必须有具体可拍内容(谁+动作+道具),拒绝"感受类"空泛拍;③每拍一个视觉记忆点。
只输出 JSON。"""


def run_outline(proj, force=False):
    """两段式第一段: 叙事大纲(钩子设计/逐拍节拍/意象库/人称决定)."""
    if proj.stage_done("outline") and not force:
        return proj.load_stage("outline")
    if proj.stage_done("script"):                # 老项目兼容: 剧本已成不回补
        return {"skipped": True, "note": "script 已存在,大纲层跳过"}
    brief = (proj.path / "brief.txt").read_text().strip()
    cast = proj.load_stage("cast")
    n = proj.load_state()["shots"]
    cast_lines = "\n".join(f"- {r['story_role']}: {r['char']}" for r in cast["cast"])
    user = f"""【故事梗概】
{brief}

【演员】
{cast_lines}

写 {n} 拍叙事大纲(每拍≈一镜 {config.SHOT_SECONDS:.2f}s,总长 {n * config.SHOT_SECONDS:.1f}s)。
结构模板(可变形,钩子铁律不变): 冷开场高潮/低谷 → 悬念问题 → 递进升级 → 小反转/情绪释放 → 尾钩。
允许倒叙/闪回结构(如先给多年前的关键场面,再切现在)。

只输出 JSON:
{{"title_cn": "剧名(4-8字)", "logline": "一句话故事",
 "person": "旁白叙事人称,first 或 third,全剧唯一",
 "hook_beat": "第1拍钩子设计: 为什么观众3秒内不划走",
 "beats": [{{"id": "q1", "beat_cn": "这一拍发生什么(≤30字,含具体动作与道具)", "emotion_cn": "情绪2-4字", "peak": false}}],
 "imagery_bank": ["全剧复用视觉意象,英文短语5-8个(象征物/光影事件),如: dying potted plant on the desk / wax seal cracked open / fireflies over the field"],
 "tail_hook": "结尾钩子(钩住下一幕)"}}"""
    outline_system = OUTLINE_SYSTEM + "\n\n" + creative_skills.prompt_for("screenwriter")
    data = llm.chat_json(config.LLM_TEXT, outline_system, user)
    # 大纲自评一轮: 钩子强度 + 峰值拍检查
    critique = llm.chat_json(
        config.LLM_FAST, CRITIC_SYSTEM,
        "【叙事大纲】\n" + json.dumps(data, ensure_ascii=False) +
        '\n\n只输出 JSON: {"hook":0-10,"arc":0-10,"peaks_ok":true/false(每段有峰有落),"issues":["具体问题"]}')
    data["critique"] = critique
    if critique.get("hook", 0) < 8 or not critique.get("peaks_ok", False):
        data = llm.chat_json(
            config.LLM_TEXT, outline_system,
            user + "\n\n【你上一稿的评审反馈,逐条修复(尤其钩子必须落在高潮/低谷)】\n"
            + json.dumps(critique, ensure_ascii=False))
        data["critique"] = critique
    proj.save_stage("outline", data, meta={"hook": data["critique"].get("hook"),
                                           "title": data.get("title_cn", "")})
    print(f"[编剧·大纲] 钩子 {data['critique'].get('hook')}/10 | {data.get('hook_beat', '')[:60]}")
    return data


def _durations(shots):
    """剪辑表目标时长；新项目用连续时长，老项目兼容 short/std。"""
    out = []
    for s in shots:
        fallback = config.SHORT_TRIM if s.get("duration_hint") == "short" else config.SHOT_SECONDS
        try:
            dur = float(s.get("edit_duration_s", fallback))
        except (TypeError, ValueError):
            dur = fallback
        out.append(round(max(1.2, min(config.SHOT_SECONDS - 0.08, dur)), 3))
    return out


def run(proj, force=False):
    if proj.stage_done("script") and not force:
        return proj.load_stage("script")
    outline = run_outline(proj)                   # 两段式: 大纲未成先补(已成则直接读)
    brief = (proj.path / "brief.txt").read_text().strip()
    cast, mats = proj.load_stage("cast"), proj.load_stage("materials")
    n = proj.load_state()["shots"]
    cast_lines = "\n".join(
        f"- {r['story_role']}: {r['char']} | DNA: {r['profile']['face_dna']} | 穿搭: {r['profile']['outfit_dna']}"
        for r in cast["cast"])
    lead_name = cast["cast"][0]["char"]
    lead_role = cast["cast"][0]["story_role"]
    scene_lines = "\n".join(f"- {s['id']}: {s['dna_en']} (灯光:{s.get('light_cn','')})" for s in mats["scenes"])
    beats = outline.get("beats") or []
    beats_lines = "\n".join(
        f"- {b['id']}: {b.get('beat_cn','')} [{b.get('emotion_cn','')}"
        + (" | 本幕情绪峰" if b.get("peak") else "") + "]"
        for b in beats) or "(无)"
    imagery = ", ".join(outline.get("imagery_bank") or [])
    person_cn = {"first": "第一人称『我』", "third": "第三人称『他』"}.get(
        outline.get("person"), "与大纲一致")
    user = f"""【故事梗概】
{brief}

【叙事大纲(两段式第一段产物,逐拍执行,情绪峰拍要有爆发动作)】
钩子设计: {outline.get("hook_beat", "")}
{beats_lines}
尾钩: {outline.get("tail_hook", "")}
【全剧意象库(每镜至少取一个做视觉记忆点)】{imagery}

【演员(外观DNA逐字块)】
{cast_lines}

【场景库(逐字DNA)】
{scene_lines}
【全剧风格】{mats.get('style_note_en', 'photorealistic cinematic still, real scene')}

写一部 {n} 镜短剧(每镜素材最多 {config.SHOT_SECONDS:.2f}s；成片时长由各镜 edit_duration_s 相加决定)。
结构: 起(约1/3) 承(约1/3) 转+合(约1/3),结尾留一个视觉记忆点动作。
旁白叙事人称: {person_cn},全剧统一。

每镜输出:
- id: "q1".."q{n}"
- scene: 场景id(S1..)
- cast: 该镜出场角色,从【演员】的列表里按名字选,**单镜最多 2 人**(能 1 人就 1 人);
  双人镜一主体动作+另一主体静立,严禁递物/接触交互;纯场景空镜给空数组 [](**全剧最多 1 镜**)
- shot_function: establish/trigger/escalate/reaction/reveal/decision/aftermath 之一,说明本镜为什么存在
- edit_duration_s: 1.2~4.9 秒连续值,在观众获得信息/动作峰值/反应落地时切,禁止只填 2.6 或 5.0 两档
- edit_in_s: 0.0~0.5 秒,生成素材开头预计需要裁掉的稳定期
- cut_intent: 中文一句,说明从什么动作/视线/声音切入下一镜
- shot_en: 英文,景别+单一连续运镜+central third 构图(竖版安全);相邻镜景别必须跳变
- action_en: 英文,2-3 个爆发点动作+慢过渡,无手部特写,正脸不说话(台词靠后期配音,画面拍背影/侧脸/远景);双角色镜动作用 "{{名1}}…" "{{名2}}…" 分述;**台词/旁白点名的道具必须在这里出现**
- performance_beat: 中文一句,目标+阻力+可见微反应;禁止只有“站着不动”
- locked_facts: 英文数组,逐条写不可改写的“角色名+动作+对象+结果状态”;分镜/重拍必须原样守住
- emotion_cn: 情绪(中文2-4字)
- imagery_en: 本镜的视觉记忆点(从意象库取或呼应,英文短语)
- dialogue_cn: 台词数组(可省略=无台词),如 [{{"who": "{lead_role}", "line": "≤18字台词"}}];
  全剧约一半的镜头要有台词推戏;纯环境镜/空镜不给
- narration_cn: 旁白 ≤25 汉字(可空字符串;该镜有台词时通常留空);人称={person_cn}

只输出 JSON:
{{"title_cn": "剧名(4-8字)", "logline": "一句话故事",
 "shots": [{{"id": "q1", "scene": "S1", "cast": ["{lead_name}"], "shot_function": "trigger",
   "edit_duration_s": 3.6, "edit_in_s": 0.15, "cut_intent": "动作落点后切反应",
   "shot_en": "...", "action_en": "...", "performance_beat": "...",
   "locked_facts": ["{lead_name} performs the required story action and reaches the stated result"],
   "emotion_cn": "...", "imagery_en": "...", "dialogue_cn": [{{"who": "...", "line": "..."}}], "narration_cn": "..."}}],
 "ending_memory": "结尾视觉记忆点说明"}}"""
    system = (SYSTEM.format(SHOT_SECONDS=config.SHOT_SECONDS, SHORT_TRIM=config.SHORT_TRIM)
              + "\n\n" + creative_skills.prompt_for("screenwriter"))
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
    # ── 框架 lint 闭环: 人称/说的必须拍到/相邻镜去重(代码确定性检查,违规一轮修订) ──
    def _fw_lints(shots):
        issues = []
        for msg in lint.lint_person([s.get("narration_cn") or "" for s in shots]):
            issues.append(msg)
        for sid, miss in lint.lint_show_dont_tell(shots):
            issues.append(f"{sid}: 说了『{'、'.join(miss)}』但 action_en 没拍到(说的必须拍到)")
        for sid, why in lint.lint_adjacent(shots):
            issues.append(f"{sid}: {why}(相邻镜去重)")
        return issues
    fw_issues = _fw_lints(data["shots"])
    if fw_issues:
        print(f"[编剧] 框架 lint {len(fw_issues)} 条,修订一轮")
        data = llm.chat_json(
            config.LLM_TEXT, system,
            user + "\n\n【确定性 lint 反馈,逐条修复】\n" + "\n".join("- " + i for i in fw_issues))
        residual = _fw_lints(data["shots"])
        data["fw_lint_residual"] = residual
        if residual:
            print(f"[编剧] lint 残留 {len(residual)} 条(保留): {residual[:3]}")
    data["critique"] = critique_log
    shots = data["shots"]
    if len(shots) != n:
        raise ValueError(f"镜数不符: 要求{n} 实得{len(shots)}")
    cast_names = [r["char"] for r in cast["cast"]]
    role_names = [r["story_role"] for r in cast["cast"]]
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
        role2char = {r["story_role"]: r["char"] for r in cast["cast"]}
        names = [role2char.get(x, x) for x in names]   # LLM 误用 story_role 时映射回 char
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
        s["dialogue_cn"] = _norm_dialogue(s.pop("dialogue_cn", None), names, role_names, cast)
        # 5.04s 窗口装不下太多字: 台词优先,合计>25 字时丢旁白;两句台词>26 字时留第一句
        n_dia = sum(len(d["line"]) for d in s["dialogue_cn"])
        if n_dia and len(s.get("narration_cn") or "") and n_dia + len(s["narration_cn"]) > 25:
            s["narration_cn"] = ""
        if len(s["dialogue_cn"]) == 2 and n_dia > 26:
            s["dialogue_cn"] = s["dialogue_cn"][:1]
        s.setdefault("shot_en", "")
        s.setdefault("action_en", "")
        if s.get("duration_hint") not in ("short", "std"):
            s["duration_hint"] = "std"            # 老工作台兼容字段
        fallback = config.SHORT_TRIM if s["duration_hint"] == "short" else config.SHOT_SECONDS
        try:
            edit_in = max(0.0, min(0.5, float(s.get("edit_in_s", 0.15))))
            edit_dur = float(s.get("edit_duration_s", fallback))
        except (TypeError, ValueError):
            edit_in, edit_dur = 0.15, fallback
        # 自然语速约 4.5~5 字/秒；留出气口，宁可延长画面也不在配音端暴力加速。
        voice_chars = n_dia + len(s.get("narration_cn") or "")
        min_voice = min(config.SHOT_SECONDS - edit_in - 0.08,
                        max(1.2, voice_chars / 4.8 + 0.55) if voice_chars else 1.2)
        edit_dur = max(min_voice, min(edit_dur, config.SHOT_SECONDS - edit_in - 0.08))
        s["edit_in_s"] = round(edit_in, 2)
        s["edit_duration_s"] = round(edit_dur, 2)
        s.setdefault("shot_function", "reveal")
        s.setdefault("cut_intent", "信息落地后直切下一拍")
        s.setdefault("performance_beat", "一个主动作后出现可见微反应")
        facts = [str(x).strip() for x in (s.get("locked_facts") or []) if str(x).strip()]
        s["locked_facts"] = facts or [s["action_en"].strip()]
    data["shot_ids"] = [s["id"] for s in shots]
    _write_srt(proj, data)
    proj.save_stage("script", data, meta={"shots": n, "title": data.get("title_cn", "")})
    return data


def _norm_dialogue(raw, shot_cast, role_names, cast):
    """台词规范化: 字符串→数组; who 归一到 story_role;每镜≤2句、每句≤18字.

    字符串格式 "主角:台词" 或裸台词(缺省该镜第一位角色);空镜丢弃台词。
    """
    if not raw:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out = []
    char2role = {r["char"]: r["story_role"] for r in cast["cast"]}
    for it in items[:2]:
        if isinstance(it, dict):
            who, line = str(it.get("who", "")).strip(), str(it.get("line", "")).strip()
        else:
            s = str(it).strip()
            if ":" in s[:8]:
                who, _, line = s.partition(":")
            elif "：" in s[:8]:
                who, _, line = s.partition("：")
            else:
                who, line = "", s
            who, line = who.strip(), line.strip()
        line = line[:18]                          # 超字截断,不整轮报废
        if not line:
            continue
        if who in role_names:
            pass
        elif who in char2role:
            who = char2role[who]                  # 写了演员名 → 归一成 story_role
        else:
            who = role_names[0]                   # 未知说话人 → 该镜首位角色
        if not shot_cast:                         # 空镜不允许台词 → 转旁白字段不做了,直接丢
            continue
        out.append({"who": who, "line": line})
    return out


def _write_srt(proj, data):
    """字幕草稿 = 台词+旁白;时间轴按剪辑表(duration_hint 裁剪后的实际时长)累计."""
    def ts(sec):
        h, m = int(sec // 3600), int(sec % 3600 // 60)
        s, ms = int(sec % 60), int(round((sec % 1) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    lines, idx = [], 0
    t = 0.0
    for shot, dur in zip(data["shots"], _durations(data["shots"])):
        t0, t1 = t, t + dur
        t = t1
        events = [(d["line"], True) for d in shot.get("dialogue_cn") or []]
        if (shot.get("narration_cn") or "").strip():
            events.append((shot["narration_cn"].strip(), False))
        m = len(events)
        for j, (text, _is_dia) in enumerate(events):
            slot = (dur - 0.6) / m
            e0 = t0 + 0.3 + j * slot
            e1 = min(e0 + slot - 0.12, t1 - 0.15)
            if e1 <= e0:
                e1 = e0 + 0.8
            idx += 1
            lines.append(f"{idx}\n{ts(e0)} --> {ts(e1)}\n{text}\n")
    (proj.path / "narration.srt").write_text("\n".join(lines))
    # 交付用全片字幕(带目录结构)同步落 subtitles/
    sub_dir = proj.path / "subtitles"
    sub_dir.mkdir(exist_ok=True)
    (sub_dir / f"{proj.name}.srt").write_text("\n".join(lines))
