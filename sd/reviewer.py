"""审片 agent —— 技术、故事事实、动态自然度、表演和画面质量的完整 verdict。"""
import json
import subprocess
from pathlib import Path

from . import config, creative_skills, llm, quality

PROMPT_TMPL = """{refs_desc}后7张按时间顺序覆盖同一镜头从开头到结尾({orient_note})。
必须把它们当成连续动作判断，不能因为某一张构图漂亮就忽略前后矛盾。

【不可改写故事事实】{locked_facts}
【该镜执行描述】{dd}

评审(只输出 JSON;空镜镜 identity 固定给 10):
{{"identity": 0-10, "story_facts": 0-10, "action": 0-10, "composition": 0-10,
 "motion_naturalness": 0-10, "performance": 0-10,
 "text_artifacts": true/false(画面任何位置是否出现乱码/涂痕/无意义文字,信封道具也不例外),
 "usable_in_s": 0.0-1.0(建议裁掉不稳定开头后的入点),
 "usable_out_s": 3.5-5.04(动作/反应完成且结尾未崩的出点),
 "advice_cn": "不通过时同时指出事实/动态/表演中最关键的问题和可执行修法;通过则空串"}}

{qa_skill}"""


def orient_note_of(proj):
    """审片提示里的画幅说明(与项目交付 orientation 一致;vision_ab 等工具共用)."""
    portrait = proj.settings().get("orientation", "landscape") == "portrait"
    return (f"横版 {config.VIDEO_W}x{config.VIDEO_H},成片会中心裁切成竖版,"
            f"所以主体必须在中三分之一" if portrait else
            f"横版 {config.VIDEO_W}x{config.VIDEO_H} 直出,"
            f"主体保持中三分之一构图")


def _ffprobe(video):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True)
    d = json.loads(r.stdout)
    streams = {s["codec_type"] for s in d["streams"]}
    return {"duration": float(d["format"]["duration"]), "has_audio": "audio" in streams}


def _frames(video, out_dir, case):
    paths = []
    times = (0.35, 1.05, 1.75, 2.50, 3.25, 4.00, 4.70)
    for i, t in enumerate(times):
        p = out_dir / f"{case}-f{i}.jpg"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                            "-i", str(video), "-frames:v", "1", "-q:v", "3", str(p)],
                           capture_output=True, text=True)
        if r.returncode == 0 and p.exists():
            paths.append(p)
    return paths


def _sheet(frames, out_dir, case):
    if len(frames) < 2:
        return None
    p = out_dir / f"{case}-sheet.jpg"
    try:
        from PIL import Image, ImageDraw
        cols, cell_w = 4, 480
        ims = []
        for i, f in enumerate(frames):
            im = Image.open(f).convert("RGB")
            h = round(im.height * cell_w / im.width)
            ims.append((i, im.resize((cell_w, h))))
        cell_h = max(im.height for _, im in ims) + 26
        rows = -(-len(ims) // cols)
        sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "black")
        draw = ImageDraw.Draw(sheet)
        for i, im in ims:
            x, y = (i % cols) * cell_w, (i // cols) * cell_h
            sheet.paste(im, (x, y + 26))
            draw.text((x + 8, y + 5), f"t{i + 1}", fill="yellow")
        sheet.save(p, quality=90)
        return p
    except Exception:
        return None


def review(proj, force=False):
    """逐镜评审(3 并发);评分回写各条历史;返回 review.json 数据."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    gen = proj.load_stage("generate")
    sb = proj.load_stage("storyboard")
    script = proj.load_stage("script")
    dd_by = {s["id"]: s for s in script["shots"]}
    cast_stage = proj.load_stage("cast")
    cast_by_name = {r["char"]: r["profile"] for r in cast_stage["cast"]}
    lead_name = cast_stage["cast"][0]["char"]
    out_dir = proj.path / "review"
    out_dir.mkdir(exist_ok=True)
    state = proj.load_state()
    takes = state.get("takes", {})

    def current_video(shot_id):
        case = f"{proj.name}-{shot_id}"
        video = gen["videos"].get(case)
        if takes.get(case):
            video = takes[case][-1]["mp4"]
        return case, video

    def review_one(shot):
        case, video = current_video(shot["id"])
        if not video or not Path(video).exists():
            return {"case": case, "video": video, "tech": "缺文件", "verdict": "fail"}
        tech = _ffprobe(video)
        if abs(tech["duration"] - config.SHOT_SECONDS) > 0.5 or not tech["has_audio"]:
            return {"case": case, "video": video, "tech": tech, "verdict": "fail",
                    "advice": "技术指标异常(时长/音轨)"}
        frames = _frames(video, out_dir, case)
        if len(frames) < 7:
            return {"case": case, "video": video, "tech": tech, "verdict": "fail", "advice": "抽帧失败"}
        _sheet(frames, out_dir, case)
        dd_full = _dd_from_jsonl(sb, case) or (
            dd_by[shot["id"]]["shot_en"] + " " + dd_by.get(shot["id"], {}).get("action_en", ""))
        in_cast = [cast_by_name[n] for n in shot.get("cast", [])][:2]
        ref_imgs = [p for prof in in_cast for p in (prof["refs"]["closeup"], prof["refs"]["front"])]
        refs_desc = (f"前{len(ref_imgs)}张图是角色参考图(每位角色两张:头部特写+全身正面,"
                     f"顺序对应镜中 Subject 编号)," if ref_imgs else "本镜是无人物空镜,")
        orient_note = orient_note_of(proj)
        locked_facts = shot.get("locked_facts") or [shot.get("action_en", "")]
        text = PROMPT_TMPL.format(refs_desc=refs_desc, orient_note=orient_note,
                                  locked_facts=json.dumps(locked_facts, ensure_ascii=False),
                                  dd=dd_full,
                                  qa_skill=creative_skills.prompt_for("reviewer"))
        try:
            # 双次评审取均值(单次 VLM 打分噪声大,同视频可差 ±4)
            v1 = llm.extract_json(llm.vision(text, ref_imgs + frames))
            v2 = llm.extract_json(llm.vision(text, ref_imgs + frames))
            for k in quality.CORE_SCORES:
                if k in v1 and k in v2:
                    v1[k] = round((v1[k] + v2[k]) / 2)
        except Exception as e:
            return {"case": case, "video": video, "tech": tech,
                    "verdict": "error", "advice": str(e)}
        v = v1
        v.update({"case": case, "tech": tech, "video": video})
        # pass 由程序统一计算；缺少任何新维度都按 0，不能由旧三维分冒充完整通过。
        for k in quality.CORE_SCORES:
            v[k] = v.get(k, 0)
        id_thr = 8 if len(shot.get("cast") or []) > 1 else 7
        v["identity_threshold"] = id_thr
        v["pass"] = (v["identity"] >= id_thr and v["action"] >= 7
                     and v["composition"] >= 7 and v["story_facts"] >= 8
                     and v["motion_naturalness"] >= 7 and v["performance"] >= 7
                     and v.get("text_artifacts") is False)
        try:
            start = max(0.0, min(1.0, float(v.get("usable_in_s", 0.15))))
            end = max(start + 1.2, min(config.SHOT_SECONDS, float(v.get("usable_out_s", 4.85))))
        except (TypeError, ValueError):
            start, end = 0.15, 4.85
        v["usable_in_s"], v["usable_out_s"] = round(start, 2), round(end, 2)
        v["verdict"] = "pass" if v["pass"] else "retake"
        return v

    results = [None] * len(script["shots"])
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(review_one, s): i for i, s in enumerate(script["shots"])}
        for f in as_completed(futs):
            results[futs[f]] = f.result()

    # 完整 verdict 绑定到具体视频；review/pick/deliver 共享同一份事实。
    for r in results:
        case = r["case"]
        dims = {k: r.get(k) for k in quality.CORE_SCORES if k in r}
        video = r.get("video")
        if takes.get(case) and video and takes[case][-1].get("mp4") == video:
            t = takes[case][-1]
            t.setdefault("scores_history", []).append(dims)
            t.setdefault("review_history", []).append(r)
            t["scores"] = dims
            t["review"] = r
        else:
            state.setdefault("gen_scores", {})[case] = dims
            state.setdefault("gen_review_history", {}).setdefault(case, []).append(r)
            state.setdefault("gen_reviews", {})[case] = r
    proj._write_state(state)

    passed = sum(1 for r in results if r.get("verdict") == "pass")
    data = {"results": results, "passed": passed, "total": len(results),
            "consistency": _consistency_check(proj, script)}
    proj.save_stage("review", data, meta={"passed": f"{passed}/{len(results)}"})
    return data


def _consistency_check(proj, script):
    """跨镜拼图校验: 全片首帧拼成一张图,一次 VLM 调用比对脸/服装/场景/色调跨镜一致性.

    逐镜独立打分看不见跨镜漂移(衬衫每镜换一件/农舍两栋的事故都漏在这),
    拼图一次全看,只报问题不翻转逐镜 verdict(由人工/重拍流程消化).
    """
    frames = []
    for s in script["shots"]:
        p = proj.path / "review" / f"{proj.name}-{s['id']}-f0.jpg"
        if p.exists():
            frames.append((s["id"], p))
    if len(frames) < 2:
        return {"checked": False, "note": "首帧不足"}
    try:
        from PIL import Image, ImageDraw
        cols, cell_w = 4, 480
        thumbs = []
        for sid, p in frames:
            im = Image.open(p)
            h = round(im.height * cell_w / im.width)
            thumbs.append((sid, im.resize((cell_w, h))))
        cell_h = max(t.height for _, t in thumbs) + 28
        rows = -(-len(thumbs) // cols)
        sheet_im = Image.new("RGB", (cols * cell_w, rows * cell_h), "black")
        draw = ImageDraw.Draw(sheet_im)
        for i, (sid, t) in enumerate(thumbs):
            x, y = (i % cols) * cell_w, (i // cols) * cell_h
            sheet_im.paste(t, (x, y + 28))
            draw.text((x + 8, y + 4), sid, fill="yellow")
        sheet = proj.path / "review" / "contact-sheet.jpg"
        sheet_im.save(sheet, quality=88)
        order = "、".join(sid for sid, _ in frames)
        text = (f"这张拼图按顺序是全片 {len(frames)} 个镜头的首帧(左上角黄字标注镜号,顺序: {order})。"
                "检查跨镜一致性: ①同一角色在不同镜头是否同一张脸、同一套衣服"
                "(颜色/材质/图案逐一比);②同一场景的不同镜头是否同一处;"
                "③色调是否连贯(刻意冷暖分段除外)。只输出 JSON: "
                '{"consistent": true/false, "issues": ["q3:衬衫从纯色变成格子,与q1不一致", ...]}\n\n'
                + creative_skills.prompt_for("reviewer"))
        out = None
        for _ in range(2):                       # vision 空回复偶发,重试一次
            try:
                out = llm.extract_json(llm.vision(text, [str(sheet)]))
                break
            except llm.LLMError:
                continue
        if out is None:
            return {"checked": False, "note": "vision 两次空回复"}
        return {"checked": True, "consistent": bool(out.get("consistent")),
                "issues": out.get("issues", [])[:8]}
    except Exception as e:
        return {"checked": False, "note": str(e)[:150]}


def has_passing_take(state, case):
    """该镜是否存在任何拥有完整通过 verdict 的条。"""
    if quality.review_is_pass(state.get("gen_reviews", {}).get(case)):
        return True
    return any(quality.review_is_pass(t.get("review"))
               for t in state.get("takes", {}).get(case, []))


def _dd_from_jsonl(sb, case):
    try:
        for line in open(sb["jsonl"]):
            row = json.loads(line)
            if row["case_id"] == case:
                import re
                m = re.search(r"detailed_description:\s*(.*?)\s*overall_soundscape:",
                              row["prompt"], re.S)
                return m.group(1).strip() if m else row["prompt"][:800]
    except Exception:
        pass
    return None
