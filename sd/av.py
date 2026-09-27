"""av —— 交付端音视频工具(配音师/制片共用,避免互相 import).

- pick_best: 每镜历史最佳条选片(全≥7 优先,同分取总分)
- orient_vf: 横竖屏裁切/缩放滤镜(生成端固定 1344x768,9:16 中心裁切安全)
- vo_of / bgm_of: 配音产物定位
- mix_vo: VO 侧链压制混音(音乐床让路,人声清晰)
- burn_vf: 字幕烧录滤镜(libass + Noto Sans CJK SC)
"""
import subprocess
from pathlib import Path

from . import config, quality

SUB_STYLE = ("FontName=Noto Sans CJK SC,FontSize=22,PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=48")


def run(cmd, timeout=1800, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {cmd[:4]}…: {(r.stderr or '')[-400:]}")
    return r


def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


def probe_size(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True)
    w, h = r.stdout.strip().splitlines()[0].split(",")[:2]
    return int(w), int(h)


# ---------------------------------------------------------------- 选片
def pick_best(proj, require_approved=True):
    """每镜选完整通过/人工例外的最佳条；默认无批准候选即阻断。"""
    script = proj.load_stage("script")
    state = proj.load_state()
    gen = proj.load_stage("generate") or {"videos": {}}
    takes = state.get("takes", {})
    rv = proj.load_stage("review") or {"results": []}
    current_reviews = {r["case"]: r for r in rv["results"]}
    humans = quality.human_reviews(proj)

    segs, pick_log = [], []
    for shot in script["shots"]:
        case = f"{proj.name}-{shot['id']}"
        candidates = [{"mp4": t["mp4"], "review": t.get("review"),
                       "scores": t.get("scores", {})} for t in takes.get(case, [])]
        if gen["videos"].get(case):
            candidates.append({"mp4": gen["videos"][case],
                               "review": state.get("gen_reviews", {}).get(case),
                               "scores": state.get("gen_scores", {}).get(case, {})})
        candidates = [c for c in candidates if Path(c["mp4"]).exists()]
        if not candidates:
            raise RuntimeError(f"{case} 没有任何可用条")

        for c in candidates:
            current = current_reviews.get(case)
            if current and current.get("video") == c["mp4"]:
                c["review"] = current
            c["disposition"] = quality.candidate_disposition(
                c.get("review"), humans.get(case), c["mp4"])

        def rank(c):
            approved = 1 if c["disposition"] in ("pass", "waived") else 0
            return (approved, quality.score_total(c.get("review")))

        best = max(candidates, key=rank)
        segs.append(best["mp4"])
        pick_log.append({"case": case, "picked": best["mp4"],
                         "disposition": best["disposition"],
                         "review": best.get("review"),
                         "human": humans.get(case),
                         "picked_scores": best.get("scores")})
    if require_approved:
        quality.assert_release_ready(pick_log, rv.get("consistency"))
    return segs, pick_log


# ---------------------------------------------------------------- 配音产物
def vo_of(proj):
    """全片 VO 音轨(配音师产物);不存在返回 None."""
    f = proj.path / "audio" / "vo_full.wav"
    return str(f) if (proj.stage_done("dub") and f.exists()) else None


def bgm_of(proj):
    """用户投喂的全片 BGM 替换文件(audio/bgm.*);不存在返回 None."""
    for ext in (".mp3", ".wav", ".flac", ".m4a"):
        f = proj.path / "audio" / f"bgm{ext}"
        if f.exists():
            return str(f)
    return None


# ---------------------------------------------------------------- 感知链
# 2026-09-25 quality_ab 三轮视觉盲裁定稿(拉普拉斯方差会把噪点/白边当"锐度",不可单独采信):
#   · LUT+eq 色调链:一致胜出(暗部更深邃/肤色更质感/无伪影) → 两条链默认启用
#   · hqdn3d: 时域拖影会糊发丝;SPAN 输出本就干净 → 默认不启用(常量保留备用)
#   · cas: 在 SPAN 母版上有白边晕轮 → 母版链不用;仅日常档(纯 lanczos 拉伸偏软)
#     用 0.7 轻档(等效强度低于旧竖版 unsharp=0.35,风险已知可控)
LOOKS_DIR = config.FRAMEWORK_ROOT / "looks"   # 放 *.cube 即全片统一调色
LOOK_PREFER = "warm-film.cube"                # A/B 胜者;teal-orange-strong 手动可换
EQ_LOOK = "eq=contrast=1.03:saturation=1.05"  # 温和对比/饱和,抬感知清晰度
CAS = "cas=strength=0.7"                      # 仅日常档;越小越锐(0.45 在母版上已见晕轮)
HQDN = "hqdn3d=1.5:1.5:6:6"                   # 备用:生成噪声重时可手工加回


def lut3d_filter():
    """looks/ 里的全片统一调色(优先 A/B 胜者 warm-film);没有则空串(链路照跑)."""
    cubes = sorted(LOOKS_DIR.glob("*.cube")) if LOOKS_DIR.is_dir() else []
    prefer = [c for c in cubes if c.name == LOOK_PREFER]
    return f"lut3d=file={prefer[0] if prefer else cubes[0]}" if cubes else ""


def look_vf():
    """母版链纯色调链(无缩放/无锐化): master.py 在 PNG→CRF14 单次编码时烤入.

    SPAN 输出本身已锐,再加 cas/hqdn3d 只会带来白边与拖影(盲评实证).
    """
    lut = lut3d_filter()
    return ",".join(([lut] if lut else []) + [EQ_LOOK])


def orient_vf(w, h, orientation, look=True):
    """裁切/缩放 + 色调链(+轻锐化);生成端 1344x768 / 母版 1920x1080 同比安全(9:16=0.5625).

    look=False: 母版链的烧字幕等再编码场景(色调已烤进 master 条,防二次叠加).
    日常档走纯 lanczos 拉伸偏软,故保留轻 cas;母版档(SPAN)经 look_vf 烤入,不再锐化.
    """
    vf = []
    if orientation == "portrait":
        vf.append("crop=w='min(iw,ih*0.5625)':h=ih:x='(iw-ow)/2':y=0")
        vf.append(f"scale={w}:{h}:flags=lanczos")
    else:
        vf.append(f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos")
        vf.append(f"crop={w}:{h}")
    if look:
        lut = lut3d_filter()
        if lut:
            vf.append(lut)
        vf.append(EQ_LOOK)
        vf.append(CAS)
    return ",".join(vf)


def burn_vf(srt_name, extra=""):
    """字幕烧录滤镜;调用方须以 srt 所在目录为 cwd(规避滤镜串路径转义)."""
    sub = f"subtitles={srt_name}:force_style='{SUB_STYLE}'"
    return f"{extra},{sub}" if extra else sub


def _audio_chain(vo_src, dur, bgm_src=None):
    """[aout]：保留现场环境音，BGM 只作为可被旁白压低的音乐床。

    0:a 是画面原声，1:a 是 VO，2:a（可选）是循环 BGM。过去 BGM 会直接
    替换 0:a，导致脚步、风声和动作感消失；现在先把环境声和音乐合成，再给 VO
    留出动态空间。dur 限定循环输入，防止最终文件被 BGM 拉长。
    """
    natural = (f"[0:a]atrim=0:{dur:.3f},asetpts=N/SR/TB,"
               "loudnorm=I=-25:TP=-2:LRA=11,aresample=48000[natural]")
    if bgm_src:
        bed = (natural + ";" +
               f"[{bgm_src}]atrim=0:{dur:.3f},asetpts=N/SR/TB,"
               "loudnorm=I=-25:TP=-2:LRA=9,volume=0.72,aresample=48000[music];"
               "[natural][music]amix=inputs=2:duration=first:normalize=0[bed]")
    else:
        bed = natural + ";[natural]anull[bed]"
    return (f"{bed};"
            f"[{vo_src}]loudnorm=I=-13:TP=-1.2:LRA=9,aresample=48000,asplit=2[sc][vo];"
            f"[bed][sc]sidechaincompress=threshold=0.05:ratio=10:attack=20:release=420[bedd];"
            f"[bedd][vo]amix=inputs=2:duration=first:normalize=0,"
            f"alimiter=limit=0.8413:level=false[aout]")   # -1.5dBTP 安全岛


def mix_vo(video, vo, out, bgm=None):
    """视频原声＋可选 BGM × VO 侧链混音；视频流直拷。"""
    dur = probe_duration(video)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", vo]
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", bgm]
    cmd += ["-filter_complex", _audio_chain("1:a", dur, "2:a" if bgm else None),
            "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", str(out)]
    run(cmd)
    return str(out)


def concat(segs, outlist, out, reencode=True):
    """concat demuxer 拼接(同源同参);reencode=False 时流直拷."""
    Path(outlist).write_text("".join(f"file '{s}'\n" for s in segs))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", str(outlist)]
    if reencode:
        cmd += ["-c:v", "libx264", "-crf", "17", "-preset", "medium",
                "-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-c", "copy"]
    cmd += [str(out)]
    run(cmd, timeout=3600)
    return str(out)


# ---------------- D 轮框架升级: 剪辑表重剪 / 片名卡 ----------------
def smart_concat(segs, edits, out):
    """剪辑表拼接: 每镜使用内容感知 in/duration，并在音频边界做短淡化.

    edits: [{"in": 秒, "duration": 秒}]；兼容旧调用传纯时长。
    """
    n = len(segs)
    if not n or len(edits) != n:
        raise ValueError("smart_concat 需要一一对应的非空镜头与剪辑范围")
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for s in segs:
        cmd += ["-i", str(s)]
    fc = []
    for i, edit in enumerate(edits):
        if isinstance(edit, (int, float)):
            start, dur = 0.0, float(edit)
        else:
            start, dur = float(edit.get("in", 0.0)), float(edit["duration"])
        if start < 0 or dur <= 0:
            raise ValueError(f"第 {i + 1} 镜剪辑范围非法: in={start}, duration={dur}")
        fade_out = max(0.0, dur - 0.08)
        fc.append(f"[{i}:v]trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS[v{i}]")
        fc.append(f"[{i}:a]atrim=start={start:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:st=0:d=0.04,afade=t=out:st={fade_out:.3f}:d=0.08[a{i}]")
    fc.append("".join(f"[v{i}][a{i}]" for i in range(n)) +
              f"concat=n={n}:v=1:a=1[vout][araw];"
              f"[araw]alimiter=limit=0.8413:level=false[aout]")   # -1.5dBTP
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", "17", "-preset", "medium",
            "-c:a", "aac", "-b:a", "160k", str(out)]
    run(cmd, timeout=3600)
    return str(out)


def make_title_clip(png, out, dur=1.4, w=1344, h=768):
    """片尾片名卡: PNG(loop) + 静音轨 → 可与正片 concat 的 mp4."""
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-loop", "1", "-t", f"{dur:.3f}", "-i", str(png),
         "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
         "-c:v", "libx264", "-crf", "17", "-preset", "medium",
         "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)])
    return str(out)
