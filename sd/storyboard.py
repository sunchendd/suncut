"""分镜 agent —— 剧本 → ref2va JSONL。

关键设计: LLM 只写每镜的 detailed_description 和 overall_soundscape,
subject_definitions(角色DNA)与 non_diegetic_music(音乐块)由程序逐字拼装,
从根上杜绝 LLM"好心改写"DNA 导致的跨镜换脸(桌面工作流 §4.2 第一条审稿项)。
"""
import json
import hashlib
import shutil
from pathlib import Path

from . import config, creative_skills, llm
from . import lint


def story_contract_hash(shot):
    """锁住重拍不能擅自改变的剧本合同。"""
    contract = {
        "id": shot.get("id", ""),
        "cast": shot.get("cast") or [],
        "action_en": shot.get("action_en", ""),
        "locked_facts": shot.get("locked_facts") or [],
    }
    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

SYSTEM = ("你是分镜师。把剧本每镜扩写成 ref2va 的 detailed_description(英文一段),"
          "遵守: 单一连续运镜、**1 个主爆发动作+最多 1 个次要节点+收势(共≤3 节点,"
          "过度密集 AI 必崩)**、无手部特写、正脸不说话、"
          "主体居中 central third、点光源氛围;场景 DNA 的关键词必须出现在描述里;"
          "出场角色用 <Subject 1>/<Subject 2> 指代(按各镜 cast 顺序),描述以 '<Subject 1> ' 开头;"
          "双角色镜两人都要有动作,且分别在画面两侧留出空间;"
          "**双主体镜严禁递物/接触交互(形变事故源): 一主体完成动作,另一主体静立/背对,"
          "物品放桌面或已在自己手里**;"
          "**相邻镜景别必须跳变(远全/中近/特写交替),剧本的 imagery_en 记忆点必须写进描述**;"
          "结尾加 'natural live-action motion, physically plausible inertia, real scene, photorealistic'，"
          "禁止 cinematic still/人物长时间僵住。只输出 JSON。")


def run(proj, force=False):
    if proj.stage_done("storyboard") and not force:
        return proj.load_stage("storyboard")
    script, mats = proj.load_stage("script"), proj.load_stage("materials")
    scene_lines = "\n".join(f"- {s['id']}: {s['dna_en']}" for s in mats["scenes"])
    cast_by_name = {r["char"]: r["profile"] for r in proj.load_stage("cast")["cast"]}
    shots_in = [{"id": s["id"], "scene": s["scene"], "cast": s.get("cast", []),
                 "shot_en": s["shot_en"], "action_en": s["action_en"],
                 "duration_hint": s.get("duration_hint", "std"),
                 "imagery_en": s.get("imagery_en", ""),
                 "emotion_cn": s.get("emotion_cn", ""),
                 "shot_function": s.get("shot_function", ""),
                 "cut_intent": s.get("cut_intent", ""),
                 "performance_beat": s.get("performance_beat", ""),
                 "locked_facts": s.get("locked_facts", [])} for s in script["shots"]]
    two_by = {s["id"]: len(s.get("cast") or []) > 1 for s in script["shots"]}
    orient_note = ("横构图、主体 central third(成片会中心裁竖版,主体必须在中三分之一)"
                   if proj.settings().get("orientation", "landscape") == "portrait"
                   else "横构图、主体 central third(横版直出)")
    user = f"""【剧本镜头(英文基础描述,cast=该镜出场角色)】
{json.dumps(shots_in, ensure_ascii=False)}

【场景DNA(描述中必须体现其地点与光线)】
{scene_lines}

【光线与色调纪律(detailed_description 的光线短语必须遵守)】
主光源从词表选一(带方向): soft window key light / warm tungsten key light from one side / cold neon rim light / golden-hour warm backlight / overcast diffused daylight / single practical lamp low-key
同一场景各镜共用同一主光源,色调不得逐镜冷暖跳变;禁 low light / underexposed / dim(暗部噪点毁清晰度)。

为每镜输出英文的 detailed_description(一段: 景别+运镜+动作+场景+光线,
{config.VIDEO_W}x{config.VIDEO_H} {orient_note}、no cuts、no text)
和 overall_soundscape(该镜环境音,英文)。
出场角色按 cast 顺序写成 <Subject 1>(第一位)/<Subject 2>(第二位,若有)。

只输出 JSON:
{{"shots": [{{"id": "q1", "detailed_description": "<Subject 1> ...", "overall_soundscape": "..."}}]}}"""
    system = SYSTEM + "\n\n" + creative_skills.prompt_for("storyboard")
    data = llm.chat_json(config.LLM_TEXT, system, user)
    dd_by = {s["id"]: s for s in data["shots"]}
    dd_by, lint_log = _lint_and_rewrite(shots_in, dd_by, two_by)

    # 参考图必须复制进 runtime 根(infer 容器只挂载 ~/sol-h3-spark-runtime)
    refs_dir = config.SD_RUNTIME / proj.name / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)

    def copy_refs(profile):
        paths = []
        for key, suffix in (("closeup", "1-closeup"), ("front", "2-front"), ("side", "3-side")):
            dst = refs_dir / f"{profile['name']}-{suffix}{Path(profile['refs'][key]).suffix}"
            if not dst.exists():
                shutil.copy2(profile["refs"][key], dst)
            paths.append(str(dst))
        return paths

    def subject_def(k, profile):
        p = 3 * k + 1
        return (f"<Subject {k + 1}> is the person shown in "
                f"<Picture {p}> (close-up), <Picture {p + 1}> (front full-body view) "
                f"and <Picture {p + 2}> (side view): {profile['face_dna']} "
                f"Subject {k + 1} is wearing {profile['outfit_dna']}.")

    # 主角取第一个有人物的镜头的 cast[0](首镜可能是空镜);全空镜时取选角表第一位
    lead_shot = next((s for s in script["shots"] if s.get("cast")), None)
    lead_name = lead_shot["cast"][0] if lead_shot else next(iter(cast_by_name))
    lead = cast_by_name[lead_name]
    rows = []
    for s in script["shots"]:
        dd = dd_by[s["id"]]["detailed_description"]
        empty_shot = not s.get("cast")           # 空镜: 无人物,t2va
        if empty_shot:
            dd = dd.replace("<Subject 1>", "the scene").replace("<Subject 2>", "the scene")
        elif "<Subject 1>" not in dd:
            dd = "<Subject 1> " + dd.lstrip()
        dd = lint.ensure_safety_phrases(dd)   # 程序化补 no cuts/no text
        # 本镜出场角色的参考图与 DNA 逐字拼装(单镜≤2人,超员只取前2)
        in_shot = [cast_by_name[n] for n in (s.get("cast") or [])[:2]] or ([lead] if not empty_shot else [])
        locked_facts = [str(x) for x in (s.get("locked_facts") or [s.get("action_en", "")]) if str(x).strip()]
        for k, name in enumerate(s.get("cast") or []):
            locked_facts = [f.replace(name, f"<Subject {k + 1}>") for f in locked_facts]
        locked_block = " | ".join(locked_facts)
        if empty_shot:
            row = {
                "case_id": f"{proj.name}-{s['id']}",
                "seed": lead["seed"],
                "task": "t2va",
                "references": [],
                "prompt": (f"locked_story_facts: {locked_block}. "
                           f"detailed_description: {dd} "
                           f"overall_soundscape: {dd_by[s['id']]['overall_soundscape']}. "
                           "non_diegetic_music: none; final BGM is added once by the producer"),
                "note": _shot_note(s, []),
                "dd": dd,
                "duration_hint": s.get("duration_hint", "std"),   # 制片剪辑表读取
                "edit_in_s": s.get("edit_in_s", 0.15),
                "edit_duration_s": s.get("edit_duration_s", config.SHOT_SECONDS - 0.23),
                "cut_intent": s.get("cut_intent", ""),
                "shot_function": s.get("shot_function", ""),
                "locked_facts": locked_facts,
                "story_contract_hash": story_contract_hash(s),
                "soundscape": dd_by[s["id"]]["overall_soundscape"],
                "cast": [],
            }
            rows.append(row)
            continue
        ref_paths, defs = [], []
        for k, profile in enumerate(in_shot):
            ref_paths += [{"type": "image", "path": p} for p in copy_refs(profile)]
            defs.append(subject_def(k, profile))
        row = {
            "case_id": f"{proj.name}-{s['id']}",
            "seed": in_shot[0]["seed"],
            "task": "ref2va",
            "references": ref_paths,
            # 逐字拼装: DNA/穿搭/音乐块永不经过 LLM 之手
            "prompt": (
                f"subject_definitions: {' '.join(defs)} "
                f"locked_story_facts: {locked_block}. "
                f"detailed_description: {dd} "
                f"overall_soundscape: {dd_by[s['id']]['overall_soundscape']}. "
                "non_diegetic_music: none; final BGM is added once by the producer"
            ),
            "note": _shot_note(s, in_shot),
            "dd": dd,                       # 留档供单镜重拍时外科手术式改写
            "duration_hint": s.get("duration_hint", "std"),
            "edit_in_s": s.get("edit_in_s", 0.15),
            "edit_duration_s": s.get("edit_duration_s", config.SHOT_SECONDS - 0.23),
            "cut_intent": s.get("cut_intent", ""),
            "shot_function": s.get("shot_function", ""),
            "locked_facts": locked_facts,
            "story_contract_hash": story_contract_hash(s),
            "soundscape": dd_by[s["id"]]["overall_soundscape"],
            "cast": [p["name"] for p in in_shot],
        }
        rows.append(row)
    # 落盘到 runtime 下(docker 挂载边界),导演直接引用
    jf = config.SD_RUNTIME / proj.name / "prompts.jsonl"
    jf.parent.mkdir(parents=True, exist_ok=True)
    jf.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    out = {"jsonl": str(jf), "lead": lead["name"], "seed": lead["seed"],
           "cases": [r["case_id"] for r in rows], "lint": lint_log,
           "cast_per_case": {r["case_id"]: r["cast"] for r in rows}}
    proj.save_stage("storyboard", out, meta={"cases": out["cases"]})
    return out


def _shot_note(s, in_shot):
    """分镜行的中文摘要: 情绪 | 台词/旁白 | 出场(配音与面板共用)."""
    parts = [s.get("emotion_cn", "")]
    dia = " / ".join(f"{d['who']}:{d['line']}" for d in s.get("dialogue_cn") or [])
    voice = dia or (s.get("narration_cn") or "")
    parts.append((("台词: " + dia) if dia else ("旁白: " + voice) if voice else "无台词"))
    if in_shot:
        parts.append("出场: " + "+".join(p["name"] for p in in_shot))
    else:
        parts.append("空镜")
    return " | ".join(p for p in parts if p)


def _lint_and_rewrite(shots_in, dd_by, two_by=None, max_rounds=2):
    """自动审稿: 确定性 lint 命中(双主体镜加查交互高危) → 带违规原因让 LLM 重写该镜;
    运镜全同则要求多样化."""
    from . import lint as lintmod
    two_by = two_by or {}
    log = {"rounds": [], "residual": {}}
    shot_en_by = {s["id"]: s["shot_en"] for s in shots_in}
    for rnd in range(1, max_rounds + 1):
        view = [{"id": sid, "shot_en": shot_en_by.get(sid, ""),
                 "dd": d["detailed_description"], "two": two_by.get(sid, False)}
                for sid, d in dd_by.items()]
        per, cams, variety_ok = lintmod.lint_batch(view)
        if not per and variety_ok:
            log["rounds"].append({"round": rnd, "clean": True, "cameras": cams})
            return dd_by, log
        log["rounds"].append({"round": rnd, "violations": {k: [n for n, _, _ in v] for k, v in per.items()},
                              "cameras": cams, "variety_ok": variety_ok})
        fix_items = []
        for sid, hits in per.items():
            fix_items.append({"id": sid, "detailed_description": dd_by[sid]["detailed_description"],
                              "violations": lintmod.violations_feedback(hits)})
        variety_note = "" if variety_ok else (
            "另外:全片运镜雷同(" + str(cams) +
            "),请在重写时让各镜运镜多样化(push-in/pull-back/orbit/track 交替)。\n")
        user = f"""以下分镜的 detailed_description 违反了生成端硬约束,逐镜重写(保持原意与场景,消除违规):

{json.dumps(fix_items, ensure_ascii=False, indent=1)}

{variety_note}只输出 JSON: {{"shots": [{{"id": "...", "detailed_description": "重写后的英文描述"}}]}}"""
        fixed = llm.chat_json(config.LLM_TEXT, SYSTEM + " 你是审稿修订者。", user)
        for s in fixed["shots"]:
            if s["id"] in dd_by:
                dd_by[s["id"]]["detailed_description"] = s["detailed_description"]
    view = [{"id": sid, "shot_en": shot_en_by.get(sid, ""),
             "dd": d["detailed_description"], "two": two_by.get(sid, False)}
            for sid, d in dd_by.items()]
    per, cams, _ = lintmod.lint_batch(view)
    log["residual"] = {k: [n for n, _, _ in v] for k, v in per.items()}
    return dd_by, log
