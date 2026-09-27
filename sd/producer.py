"""制片 agent —— 全流程编排 + 成片交付(横竖屏/分辨率按项目设置,可选字幕烧录与配音混入).

交付目录(D6 优化后):
  deliver/<名>-横版WxH.mp4 / <名>-竖版WxH.mp4   最终成片(烧字幕版带 -字幕 后缀)
  deliver/base.mp4                              工作母版(拼接+可选VO混音)
  桌面副本: 短剧-<剧名>-<名>-<横版|竖版>WxH[-母版].mp4
"""
import json
from pathlib import Path

from . import av, casting, config, director, dubbing, materials, reviewer, \
    screenwriter, storyboard
from .metrics import Metrics, stopwatch
from .project import Project

MAX_RETAKE_ROUNDS = 2   # 审片不过的重拍轮数上限(每轮内所有失败镜一起重拍)


def produce(name, auto_retake=True, force_stage=None):
    proj = Project(name)
    if not proj.exists():
        raise SystemExit(f"项目不存在: {name}(先 python3 -m sd new)")
    force = lambda st: force_stage == st   # noqa: E731

    steps = [("cast", "1/8 招聘选角", casting.run),
             ("materials", "2/8 服化道", materials.run),
             ("script", "3/8 编剧", screenwriter.run),
             ("storyboard", "4/8 分镜", storyboard.run)]
    for stage, label, fn in steps:
        print(f"[制片] {label}…")
        with stopwatch(proj, stage):
            fn(proj, force=force(stage))

    print("[制片] 5/8 导演开拍…")
    with stopwatch(proj, "generate", shots=len(proj.load_state().get("takes", {})) or proj.load_state()["shots"]):
        director.shoot(proj, force=force("generate"))
    print("[制片] 6/8 审片…")
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
    print("[制片] 7/8 配音配乐…")
    try:
        with stopwatch(proj, "dub"):
            dubbing.run(proj)
    except Exception as e:                        # 配音失败不阻塞交付(原声直出)
        print(f"[制片] 配音跳过: {e}")
    print("[制片] 8/8 交付…")
    with stopwatch(proj, "deliver"):
        paths = deliver(proj)
    try:
        from . import report
        cover = report.make_cover(proj)
        rep = report.write_report(proj)
        paths.update(cover)
        paths["report"] = rep
        title = (proj.load_stage("script") or {}).get("title_cn", proj.name)
        paths["nas_extra"] = _nas_sync(
            {cover["desktop"]: Path(cover["desktop"]).name,
             rep: Path(rep).name}, "成片", f"{title}-{proj.name}")
    except Exception as e:   # 封面/报告失败不阻塞交付
        print(f"[制片] 封面/报告跳过: {e}")
    m = Metrics(proj)
    m.data["delivered"] = paths
    m.file.write_text(json.dumps(m.data, ensure_ascii=False, indent=1))
    print(f"[制片] 完成: {paths}")
    return paths


def _final_encode(src, out, settings, subs_srt=None, crf=17, preset="medium",
                  abitrate="192k", look=True):
    """按项目设置(横竖屏/分辨率)出最终片;subs_srt 给定则烧字幕.视频重编码.

    look: 感知链(hqdn3d/LUT/eq/cas).母版交付的 master 条已在超分端烤入感知链,
    其再编码(烧字幕)传 look=False 防二次叠加.
    尺寸已达标且不烧字幕 → 流拷省一代编码(母版链全程只剩 SPAN 后那一次 CRF14).
    """
    landscape = settings["orientation"] == "landscape"
    W, H = config.RESOLUTIONS[settings["resolution"]][0 if landscape else 1]
    if not subs_srt and av.probe_size(src) == (W, H):
        av.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                "-c", "copy", str(out)])
        return {"path": str(out), "w": W, "h": H, "copy": True}
    vf = av.orient_vf(W, H, settings["orientation"], look=look)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    cwd = None
    if subs_srt and Path(subs_srt).exists():
        vf = av.burn_vf(Path(subs_srt).name, extra=av.orient_vf(
            W, H, settings["orientation"], look=look))
        cwd = str(Path(subs_srt).parent)          # srt 相对名,规避滤镜串转义
    cmd += ["-vf", vf, "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
            "-af", "alimiter=limit=0.8413:level=false",   # 交付级 -1.5dBTP 兜底
            "-c:a", "aac", "-b:a", abitrate, str(out)]
    av.run(cmd, timeout=3600, cwd=cwd)
    return {"path": str(out), "w": W, "h": H}


def _nas_sync(files, sub, key):
    """交付物同步到绿联 NAS(短剧工坊/);automount 按需挂载,NAS 离线时静默跳过,
    绝不阻塞交付。files: {本地路径: 目标文件名}。"""
    root = config.NAS_ROOT / sub / key
    copied = []
    if not config.NAS_ROOT.exists():
        print(f"[制片] NAS 未挂载({config.NAS_ROOT}),跳过同步")
        return copied
    try:
        root.mkdir(parents=True, exist_ok=True)
        for src, name in files.items():
            if not Path(src).exists():
                continue
            dst = root / name
            if dst.exists() and dst.stat().st_size == Path(src).stat().st_size:
                continue                       # 幂等: 同大小不重传
            import shutil
            shutil.copy2(src, dst)
            copied.append(str(dst))
        if copied:
            print(f"[制片] NAS 同步 → {root} ({len(copied)} 个文件)")
    except OSError as e:                       # NAS 半路掉线等,交付不受影响
        print(f"[制片] NAS 同步失败(忽略): {e}")
    return copied


def _edit_durations(proj, cases):
    """剪辑表时长: storyboard 行 duration_hint=short → SHORT_TRIM,否则满镜."""
    sb = proj.load_stage("storyboard")
    hints = {}
    try:
        for line in open(sb["jsonl"]):
            row = json.loads(line)
            hints[row["case_id"]] = row.get("duration_hint", "std")
    except Exception:
        pass
    return [config.SHORT_TRIM if hints.get(c) == "short" else config.SHOT_SECONDS
            for c in cases]


def _title_clip(proj, out_dir):
    """片尾片名卡: PIL 黑底字卡(venv 子进程,ttc face 精确选 SC) → 1.7s 静音 mp4."""
    import subprocess
    script = proj.load_stage("script") or {}
    title = script.get("title_cn", proj.name)
    logline = script.get("logline", "")
    png = out_dir / "title-card.png"
    code = (
        "from PIL import Image, ImageDraw, ImageFont\n"
        "FONT_PATH = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'\n"
        "def load(face_hint, size):\n"
        "    for idx in range(8):\n"
        "        f = ImageFont.truetype(FONT_PATH, size, index=idx)\n"
        "        if face_hint in ' '.join(f.getname()):\n"
        "            return f\n"
        "    return ImageFont.truetype(FONT_PATH, size)\n"
        "W, H = 1344, 768\n"
        "im = Image.new('RGB', (W, H), (8, 8, 10))\n"
        "d = ImageDraw.Draw(im)\n"
        "def center(text, font, y, fill):\n"
        "    bb = d.textbbox((0, 0), text, font=font)\n"
        "    d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], y), text, font=font, fill=fill)\n"
        f"center({title!r}, load('SC', 96), int(H * 0.40), (245, 242, 235))\n"
        f"center({logline!r}, load('SC', 34), int(H * 0.40) + 130, (170, 170, 165))\n"
        "im.save(r'%s')\nprint('TITLE_OK')" % str(png)
    )
    py = config.HOME / "venvs/imagegen/bin/python"
    r = subprocess.run([str(py), "-c", code], capture_output=True, text=True)
    if r.returncode != 0 or not png.exists():
        print(f"[制片] 片名卡失败(跳过): {(r.stderr or '')[-160:]}")
        return None
    return av.make_title_clip(png, out_dir / "title-card.mp4")


def deliver(proj, force=False, subs=False):
    """按剧本顺序选每镜最佳条 → 剪辑表拼接(short 快切破等距节奏) → (配音混入)
    → 片尾片名卡 → 横/竖+分辨率 → deliver/ 与桌面."""
    settings = proj.settings()
    out_dir = proj.path / "deliver"
    out_dir.mkdir(exist_ok=True)
    segs, pick_log = av.pick_best(proj)
    (proj.path / "picks.json").write_text(json.dumps(pick_log, ensure_ascii=False, indent=1))

    cases = [p["case"] for p in pick_log]
    durs = _edit_durations(proj, cases)
    if any(d < config.SHOT_SECONDS - 0.01 for d in durs):
        base = av.smart_concat(segs, durs, out_dir / "base.mp4")   # 剪辑表重剪
        print(f"[制片] 剪辑表重剪: {[round(d, 1) for d in durs]}")
    else:
        base = av.concat(segs, proj.path / "concat.txt", out_dir / "base.mp4", reencode=True)
    vo = av.vo_of(proj)
    if vo:                                         # 配音师产物 → 侧链压制混入
        base = av.mix_vo(base, vo, out_dir / "base-dub.mp4", bgm=av.bgm_of(proj))
        print(f"[制片] 混入配音: {vo}")
    card = _title_clip(proj, out_dir)              # 0.5s 黑场由卡自带前黑边近似
    if card:
        base = av.concat([base, card], proj.path / "concat-card.txt",
                         out_dir / "base-card.mp4", reencode=True)

    srt = proj.path / "subtitles" / f"{proj.name}.srt"
    if not srt.exists():
        srt = proj.path / "narration.srt"          # 老项目兼容
    landscape = settings["orientation"] == "landscape"
    W, H = config.RESOLUTIONS[settings["resolution"]][0 if landscape else 1]
    label = "横版" if landscape else "竖版"
    name_stem = f"{proj.name}-{label}{W}x{H}" + ("-字幕" if subs else "")
    h = out_dir / f"{name_stem}.mp4"
    _final_encode(base, h, settings, subs_srt=(srt if subs else None), crf=17)

    title = (proj.load_stage("script") or {}).get("title_cn", proj.name)
    v = config.DESKTOP / (f"短剧-{title}-{proj.name}-{label}{W}x{H}"
                          + ("-字幕" if subs else "") + ".mp4")
    try:
        v.write_bytes(h.read_bytes())              # 同机桌面,直接复制
    except OSError:
        import shutil
        shutil.copy2(h, v)
    nas = _nas_sync({h: v.name, v: v.name}, "成片", f"{title}-{proj.name}")
    return {"deliver": str(h), "desktop": str(v), "resolution": f"{W}x{H}",
            "orientation": label, "subs": bool(subs), "dubbed": bool(vo),
            "nas": nas}


def deliver_master(proj, force=False, subs=False):
    """母版交付: master 1080p 条拼接 → (配音混入) → 按设置横竖/分辨率 CRF14 → 桌面."""
    from . import master
    m = master.run(proj, force=force)
    script = proj.load_stage("script")
    settings = proj.settings()
    order = {f"{proj.name}-{s['id']}": i for i, s in enumerate(script["shots"])}
    out_dir = proj.path / "deliver"
    out_dir.mkdir(exist_ok=True)

    def shot_order(c):
        case = Path(c).stem[: -len("-1080p")]     # <proj>-<qid>-1080p → <proj>-<qid>
        return order.get(case, 99)

    clips = sorted(m["clips"], key=shot_order)
    concat = proj.path / "concat_master.txt"
    src = out_dir / "base-master.mp4"
    try:                                           # 同源同参先流拷
        av.concat(clips, concat, src, reencode=False)
    except Exception:
        src = av.concat(clips, concat, src, reencode=True)

    vo = av.vo_of(proj)
    if vo:
        src = av.mix_vo(src, vo, out_dir / "base-master-dub.mp4", bgm=av.bgm_of(proj))

    srt = proj.path / "subtitles" / f"{proj.name}.srt"
    if not srt.exists():
        srt = proj.path / "narration.srt"
    landscape = settings["orientation"] == "landscape"
    W, H = config.RESOLUTIONS[settings["resolution"]][0 if landscape else 1]
    label = "横版" if landscape else "竖版"
    h = out_dir / f"{proj.name}-母版-{label}{W}x{H}" + ("-字幕" if subs else "") + ".mp4"
    _final_encode(src, h, settings, subs_srt=(srt if subs else None),
                  crf=14, preset="slow", look=False)
    title = script.get("title_cn", proj.name)
    v = config.DESKTOP / (f"短剧-{title}-{proj.name}-母版{label}{W}x{H}"
                          + ("-字幕" if subs else "") + ".mp4")
    try:
        v.write_bytes(h.read_bytes())
    except OSError:
        import shutil
        shutil.copy2(h, v)
    nas = _nas_sync({h: v.name, v: v.name}, "母版", f"{title}-{proj.name}")
    return {"master": str(h), "master_desktop": str(v), "resolution": f"{W}x{H}",
            "nas": nas}
