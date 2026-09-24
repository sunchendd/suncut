"""制片 agent —— 全流程编排 + 成片交付(横版/竖版裁切)到桌面."""
import json
import subprocess
from pathlib import Path

from . import casting, config, director, materials, reviewer, screenwriter, storyboard
from .metrics import Metrics, stopwatch
from .project import Project

MAX_RETAKE_ROUNDS = 2   # 审片不过的重拍轮数上限(每轮内所有失败镜一起重拍)


def produce(name, auto_retake=True, force_stage=None):
    proj = Project(name)
    if not proj.exists():
        raise SystemExit(f"项目不存在: {name}(先 python3 -m sd new)")
    force = lambda st: force_stage == st   # noqa: E731

    steps = [("cast", "1/7 招聘选角", casting.run),
             ("materials", "2/7 场景物料", materials.run),
             ("script", "3/7 编剧", screenwriter.run),
             ("storyboard", "4/7 分镜", storyboard.run)]
    for stage, label, fn in steps:
        print(f"[制片] {label}…")
        with stopwatch(proj, stage):
            fn(proj, force=force(stage))

    print("[制片] 5/7 导演开拍…")
    with stopwatch(proj, "generate", shots=len(proj.load_state().get("takes", {})) or proj.load_state()["shots"]):
        director.shoot(proj, force=force("generate"))
    print("[制片] 6/7 审片…")
    with stopwatch(proj, "review"):
        rv = reviewer.review(proj, force=force("review"))
    Metrics(proj).mark("review", 0.0, {"passed": f"{rv['passed']}/{rv['total']}"})
    print(f"[审片] {rv['passed']}/{rv['total']} 过")
    if auto_retake:
        for round_i in range(1, MAX_RETAKE_ROUNDS + 1):
            state = proj.load_state()
            failing = [r for r in rv["results"]
                       if r.get("verdict") in ("retake", "fail")
                       and not reviewer.has_passing_take(state, r["case"])]
            if not failing:
                break
            for r in failing:
                print(f"[制片] 重拍R{round_i} {r['case']}: "
                      f"{r.get('advice_cn') or r.get('advice', '')}")
                with stopwatch(proj, "retake"):
                    director.retake(proj, r["case"], advice=r.get("advice_cn", ""))
            with stopwatch(proj, "review"):
                rv = reviewer.review(proj, force=True)
            Metrics(proj).mark("review", 0.0, {"passed": f"{rv['passed']}/{rv['total']}"})
            print(f"[复审R{round_i}] {rv['passed']}/{rv['total']} 过")
    print("[制片] 7/7 交付…")
    with stopwatch(proj, "deliver"):
        paths = deliver(proj)
    try:
        from . import report
        cover = report.make_cover(proj)
        rep = report.write_report(proj)
        paths.update(cover)
        paths["report"] = rep
    except Exception as e:   # 封面/报告失败不阻塞交付
        print(f"[制片] 封面/报告跳过: {e}")
    m = Metrics(proj)
    m.data["delivered"] = paths
    m.file.write_text(json.dumps(m.data, ensure_ascii=False, indent=1))
    print(f"[制片] 完成: {paths}")
    return paths


def deliver_master(proj, force=False):
    """母版交付: master 1080p 条拼接 → 横版 CRF14 + 竖版 1080x1920 到桌面."""
    from . import master
    m = master.run(proj, force=force)
    script = proj.load_stage("script")
    order = {f"{proj.name}-{s['id']}": i for i, s in enumerate(script["shots"])}

    def shot_order(c):
        case = Path(c).stem[: -len("-1080p")]     # <proj>-<qid>-1080p → <proj>-<qid>
        return order.get(case, 99)

    clips = sorted(m["clips"], key=shot_order)
    concat = proj.path / "concat_master.txt"
    concat.write_text("".join(f"file '{c}'\n" for c in clips))
    title = script.get("title_cn", proj.name)
    h = proj.path / f"{proj.name}-母版-横版1080p.mp4"
    v = config.DESKTOP / f"短剧-{title}-{proj.name}-母版竖版1080p.mp4"
    run = lambda cmd: subprocess.run(cmd, capture_output=True, text=True)  # noqa: E731
    r = run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat), "-c", "copy", str(h)])
    if r.returncode != 0:   # copy 失败(参数差异)则重编码
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                 "-i", str(concat), "-c:v", "libx264", "-crf", "14", "-preset", "slow",
                 "-c:a", "aac", "-b:a", "192k", str(h)])
        if r.returncode != 0:
            raise RuntimeError("母版横版拼接失败: " + r.stderr[-300:])
    r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(h),
             "-vf", "crop=612:1088:654:0,scale=1080:1920:flags=lanczos",
             "-c:v", "libx264", "-crf", "14", "-preset", "slow", "-c:a", "copy", str(v)])
    if r.returncode != 0:
        raise RuntimeError("母版竖版裁切失败: " + r.stderr[-300:])
    return {"master_horizontal": str(h), "master_vertical_desktop": str(v)}


def deliver(proj, force=False):
    """按剧本顺序拼接每镜最佳条 → 横版 CRF17 + 竖版 1080x1920,复制到桌面."""
    script = proj.load_stage("script")
    state = proj.load_state()
    gen = proj.load_stage("generate")
    takes = state.get("takes", {})
    rv = proj.load_stage("review") or {"results": []}
    verdict = {r["case"]: r.get("verdict") for r in rv["results"]}

    segs, pick_log = [], []
    for shot in script["shots"]:
        case = f"{proj.name}-{shot['id']}"
        gen_scores = state.get("gen_scores", {}).get(case, {})
        candidates = [{"mp4": t["mp4"], "scores": t.get("scores", {})}
                      for t in takes.get(case, [])]          # 重拍条
        if gen["videos"].get(case):                            # 首轮条殿后
            candidates.append({"mp4": gen["videos"][case], "scores": gen_scores})
        candidates = [c for c in candidates if Path(c["mp4"]).exists()]
        if not candidates:
            raise RuntimeError(f"{case} 没有任何可用条")

        def rank(c):   # 有分数且全 ≥7 最优,其次总分,无分垫底
            s = c.get("scores") or {}
            ok = 1 if (s and min(s.values()) >= 7) else 0
            return (ok, sum(s.values()) if s else -1)

        best = max(candidates, key=rank)
        segs.append(best["mp4"])
        pick_log.append({"case": case, "picked": best["mp4"], "verdict": verdict.get(case),
                         "picked_scores": best.get("scores")})
    (proj.path / "picks.json").write_text(json.dumps(pick_log, ensure_ascii=False, indent=1))

    concat = proj.path / "concat.txt"
    concat.write_text("".join(f"file '{s}'\n" for s in segs))
    title = (proj.load_stage("script") or {}).get("title_cn", proj.name)
    h = proj.path / f"{proj.name}-横版.mp4"
    v = config.DESKTOP / f"短剧-{title}-{proj.name}-竖版.mp4"
    run = lambda cmd: subprocess.run(cmd, capture_output=True, text=True)  # noqa: E731

    r = run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat), "-c:v", "libx264", "-crf", "17", "-preset", "medium",
             "-c:a", "aac", "-b:a", "160k", str(h)])
    if r.returncode != 0:
        raise RuntimeError("横版拼接失败: " + r.stderr[-400:])
    r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(h),
             "-vf", "crop=432:768:456:0,scale=1080:1920:flags=lanczos,unsharp=5:5:0.35",
             "-c:v", "libx264", "-crf", "17", "-preset", "medium",
             "-c:a", "copy", str(v)])
    if r.returncode != 0:
        raise RuntimeError("竖版裁切失败: " + r.stderr[-400:])
    return {"horizontal": str(h), "vertical_desktop": str(v)}
