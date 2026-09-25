"""审片 agent —— 技术核验 + GLM-4.5V 抽帧视觉评审 + 审片包(人可复核).

审片维度(桌面工作流 §5.1): 身份一致性 / 动作 / 构图。
每镜抽 3 帧(0.5s/2.5s/4.5s)与角色参考图(特写+全身)同送视觉模型,
输出 0-10 三维评分;全维 ≥7 过,否则给出重拍建议。
"""
import json
import subprocess
from pathlib import Path

from . import config, llm

PROMPT_TMPL = """{refs_desc}后3张是同一镜头视频的第0.5s/2.5s/4.5s帧({orient_note})。

【该镜要求】{dd}

评审(只输出 JSON;空镜镜 identity 固定给 10):
{{"identity": 0-10, "action": 0-10, "composition": 0-10,
 "pass": true/false(三项全部>=7 才 true),
 "advice_cn": "不通过时给一句具体重拍建议(如:换运镜/减动作/强调光线);通过则空串"}}"""


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
    for i, t in enumerate(("0.5", "2.5", "4.5")):
        p = out_dir / f"{case}-f{i}.jpg"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", t,
                            "-i", str(video), "-frames:v", "1", "-q:v", "3", str(p)],
                           capture_output=True, text=True)
        if r.returncode == 0 and p.exists():
            paths.append(p)
    return paths


def _sheet(frames, out_dir, case):
    if len(frames) < 2:
        return None
    p = out_dir / f"{case}-sheet.jpg"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-i", frames[0], "-i", frames[1], "-i", frames[2],
                        "-filter_complex", "[0][1][2]hstack=3,scale=1536:-2",
                        str(p)], capture_output=True, text=True)
    return p if r.returncode == 0 and p.exists() else None


def review(proj, force=False):
    """逐镜评审(3 并发);评分回写各条历史;返回 review.json 数据."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    gen = proj.load_stage("generate")
    sb = proj.load_stage("storyboard")
    script = proj.load_stage("script")
    portrait = proj.settings().get("orientation", "landscape") == "portrait"
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
            return {"case": case, "tech": "缺文件", "verdict": "fail"}
        tech = _ffprobe(video)
        if abs(tech["duration"] - config.SHOT_SECONDS) > 0.5 or not tech["has_audio"]:
            return {"case": case, "tech": tech, "verdict": "fail",
                    "advice": "技术指标异常(时长/音轨)"}
        frames = _frames(video, out_dir, case)
        if len(frames) < 3:
            return {"case": case, "tech": tech, "verdict": "fail", "advice": "抽帧失败"}
        _sheet(frames, out_dir, case)
        dd_full = _dd_from_jsonl(sb, case) or (
            dd_by[shot["id"]]["shot_en"] + " " + dd_by.get(shot["id"], {}).get("action_en", ""))
        in_cast = [cast_by_name[n] for n in shot.get("cast", [])][:2] or [cast_by_name[lead_name]]
        ref_imgs = [p for prof in in_cast for p in (prof["refs"]["closeup"], prof["refs"]["front"])]
        refs_desc = (f"前{len(ref_imgs)}张图是角色参考图(每位角色两张:头部特写+全身正面,"
                     f"顺序对应镜中 Subject 编号)," if ref_imgs else "本镜是无人物空镜,")
        orient_note = (f"横版 {config.VIDEO_W}x{config.VIDEO_H},成片会中心裁切成竖版,"
                       f"所以主体必须在中三分之一" if portrait else
                       f"横版 {config.VIDEO_W}x{config.VIDEO_H} 直出,"
                       f"主体保持中三分之一构图")
        text = PROMPT_TMPL.format(refs_desc=refs_desc, orient_note=orient_note,
                                  dd=dd_full)
        try:
            # 双次评审取均值(单次 VLM 打分噪声大,同视频可差 ±4)
            v1 = llm.extract_json(llm.vision(text, ref_imgs + frames))
            v2 = llm.extract_json(llm.vision(text, ref_imgs + frames))
            for k in ("identity", "action", "composition"):
                if k in v1 and k in v2:
                    v1[k] = round((v1[k] + v2[k]) / 2)
        except Exception as e:
            return {"case": case, "tech": tech, "verdict": "error", "advice": str(e)}
        v = v1
        v.update({"case": case, "tech": tech, "video": video})
        # pass 由程序按双次均值三维分计算(VLM 自报布尔偏保守且与分数不一致)
        dims = [v.get(k, 0) for k in ("identity", "action", "composition")]
        v["pass"] = all(d >= 7 for d in dims)
        v["verdict"] = "pass" if v["pass"] else "retake"
        return v

    results = [None] * len(script["shots"])
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(review_one, s): i for i, s in enumerate(script["shots"])}
        for f in as_completed(futs):
            results[futs[f]] = f.result()

    # 评分回写条历史: 只升不降(保留历史最优,防噪声把好条打崩)
    for r in results:
        case = r["case"]
        dims = {k: r.get(k) for k in ("identity", "action", "composition") if k in r}
        if not dims:
            continue
        if takes.get(case):
            t = takes[case][-1]
            old = t.get("scores") or {}
            t.setdefault("scores_history", []).append(dims)
            if (not old) or sum(dims.values()) >= sum(old.values()):
                t["scores"] = dims
        else:
            state.setdefault("gen_scores", {})[case] = dims
    proj._write_state(state)

    passed = sum(1 for r in results if r.get("verdict") == "pass")
    data = {"results": results, "passed": passed, "total": len(results)}
    proj.save_stage("review", data, meta={"passed": f"{passed}/{len(results)}"})
    return data


def has_passing_take(state, case):
    """该镜是否存在任何已通过的条(首轮或某次重拍)."""
    gs = state.get("gen_scores", {}).get(case)
    if gs and min(gs.values()) >= 7:
        return True
    return any(t.get("scores") and min(t["scores"].values()) >= 7
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
