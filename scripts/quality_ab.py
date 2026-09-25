#!/usr/bin/env python3
"""quality_ab —— 交付感知链 A/B 验证: 客观锐度指标 + VLM 盲评.

变体(同一源,同 CRF14/slow 编码器):
  A 旧链      仅缩放/裁切(=今天交付产物)
  B 新感知链  hqdn3d → eq → cas
  C 温和 LUT  B + looks/warm-film.cube
  D 加强 LUT  B + looks/teal-orange-strong.cube

第一步先用单帧校准 cas strength(拉普拉斯方差,越小越锐),再用全片变体
抽 4 帧算指标 + glm-4.5v 两轮盲评定胜负。

用法: python3 scripts/quality_ab.py [源mp4] [--skip-calib]
      缺省源 = projects/jiuwu/master/jiuwu-q1-1080p.mp4
"""
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sd import llm  # noqa: E402

WORK = Path("/tmp/quality_ab")
LOOKS = ROOT / "looks"
DEFAULT_SRC = ROOT / "projects" / "jiuwu" / "master" / "jiuwu-q1-1080p.mp4"
VLM_MODEL = "glm-4.5v"

HQDN = "hqdn3d=1.5:1.5:6:6"
EQ = "eq=contrast=1.03:saturation=1.05"
CAS_STRENGTH = 0.45        # 校准后写回 sd/av.py 的 CAS 常量


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cmd 失败: {cmd[:3]}…: {r.stderr[-200:]}")
    return r.stdout


def duration(p):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(p)]).strip())


def sharpness(png):
    """拉普拉斯方差(灰度 4 邻域): 越大越锐."""
    import numpy as np
    from PIL import Image
    g = np.asarray(Image.open(png).convert("L"), dtype=np.float64)
    lap = np.abs(4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1]
                 - g[1:-1, :-2] - g[1:-1, 2:])
    return float(lap.var())


def grab(src, ts, out_png):
    sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ts:.2f}", "-i", str(src),
        "-frames:v", "1", str(out_png)])


def calibrate(src):
    """cas 方向/强度校准: 单帧各强度 + 旧 unsharp 对照."""
    ts = duration(src) * 0.5
    base = WORK / "cal_src.png"
    grab(src, ts, base)
    rows = [("none", "null"), ("旧unsharp", "unsharp=5:5:0.35")]
    rows += [(f"cas={s}", f"cas=strength={s}")
             for s in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9)]
    print("\n== cas 强度校准(拉普拉斯方差,越大越锐) ==")
    v0 = sharpness(base)
    print(f"{'none':<12} {v0:10.1f}  (基准)")
    table = {}
    for name, vf in rows:
        out = WORK / f"cal_{name.replace('=', '_').replace('旧', 'old')}.png"
        sh(["ffmpeg", "-y", "-loglevel", "error", "-i", str(base),
            "-vf", vf, "-frames:v", "1", str(out)])
        v = sharpness(out)
        table[name] = v
        print(f"{name:<12} {v:10.1f}  ({v / v0:.2f}x)")
    return table


def encode_variants(src):
    lut_g = f"lut3d=file={LOOKS / 'warm-film.cube'}"
    lut_s = f"lut3d=file={LOOKS / 'teal-orange-strong.cube'}"
    variants = {
        "A_旧链": "scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080",
        "B_感知链": f"{HQDN},{EQ},cas=strength={CAS_STRENGTH}",
        "C_温和LUT": f"{HQDN},{lut_g},{EQ},cas=strength={CAS_STRENGTH}",
        "D_加强LUT": f"{HQDN},{lut_s},{EQ},cas=strength={CAS_STRENGTH}",
    }
    outs = {}
    dur = duration(src)
    for name, vf in variants.items():
        out = WORK / f"{name}.mp4"
        t0 = time.time()
        sh(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf,
            "-c:v", "libx264", "-crf", "14", "-preset", "slow",
            "-c:a", "copy", str(out)])
        mb = out.stat().st_size / 1e6
        print(f"[encode] {name} {mb:.2f}MB {mb * 8 / dur:.1f}Mbps "
              f"({time.time() - t0:.0f}s)")
        outs[name] = out
    return outs


def frame_metrics(clips, ts_list):
    print("\n== 抽帧锐度指标(拉普拉斯方差,4 帧均值) ==")
    res = {}
    for name, p in clips.items():
        vals = []
        for i, ts in enumerate(ts_list):
            f = WORK / f"{name}_f{i}.png"
            grab(p, ts, f)
            vals.append(sharpness(f))
        res[name] = sum(vals) / len(vals)
        print(f"{name:<10} {res[name]:10.1f}")
    return res


def vlm_judge(pa, pb, q):
    """盲评: 随机左右,返回胜者 A/B/tie. q=帧对列表[(pngA,pngB)]."""
    wins = []
    for fa, fb in q:
        flip = random.random() < 0.5
        left, right = (fb, fa) if flip else (fa, fb)
        content = [{"type": "text", "text":
                    "同一镜头的两个版本(左=X,右=Y)。哪个整体画质更好?"
                    "考量: 清晰锐度、色彩层次与质感、是否有锐化晕或噪点。"
                    "只回答 X / Y / TIE,再加一句理由。"}]
        for p in (left, right):
            content.append({"type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64,"
                                         + llm._shrink_b64(str(p))}})
        body = {"model": VLM_MODEL, "messages": [
            {"role": "user", "content": content}], "max_tokens": 200}
        d = llm._post(body, timeout=240)
        ans = (d["choices"][0]["message"].get("content") or "").strip()
        pick = "TIE"
        if ans.upper().startswith("X"):
            pick = "B" if flip else "A"
        elif ans.upper().startswith("Y"):
            pick = "A" if flip else "B"
        wins.append((pick, ans[:60]))
    return wins


def _crop1000(png, out, x, y, w=960, h=540):
    """原生分辨率裁块(不缩图): VLM 审片默认 _shrink_b64 压 768px 会抹掉锐度差,
    锐度 A/B 必须用局部原尺寸裁块."""
    sh(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png),
        "-vf", f"crop={w}:{h}:{x}:{y}", str(out)])


def vlm_judge_native(png_a, png_b, region=(480, 270)):
    """原生裁块盲评一对帧: 返回胜者 A/B/TIE."""
    x, y = region
    ca, cb = WORK / "na.png", WORK / "nb.png"
    _crop1000(png_a, ca, x, y)
    _crop1000(png_b, cb, x, y)
    flip = random.random() < 0.5
    left, right = (cb, ca) if flip else (ca, cb)
    content = [{"type": "text", "text":
                "同源同镜头的两张原生分辨率局部图(左=X,右=Y)。哪张更清晰锐利"
                "(边缘与纹理更扎实、细节更清楚)?同时注意是否有锐化白边/晕轮。"
                "只回答 X 或 Y 或 TIE,加一句理由。"}]
    for p in (left, right):
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,"
                                     + llm._shrink_b64(str(p), maxdim=1280)}})
    d = llm._post({"model": VLM_MODEL, "messages": [
        {"role": "user", "content": content}], "max_tokens": 200}, timeout=240)
    ans = (d["choices"][0]["message"].get("content") or "").strip()
    if ans.upper().startswith("X"):
        return ("B" if flip else "A"), ans[:60]
    if ans.upper().startswith("Y"):
        return ("A" if flip else "B"), ans[:60]
    return "TIE", ans[:60]


def blind_compare(clips, ts_list):
    print("\n== VLM 盲评(glm-4.5v,每对 2 帧 × 2 轮) ==")
    tally = {}
    for pair in [("A_旧链", "B_感知链"), ("B_感知链", "C_温和LUT"),
                 ("B_感知链", "D_加强LUT")]:
        cnt = {"A": 0, "B": 0, "TIE": 0}
        for _ in range(2):
            frames = []
            for i in (0, 2):          # 每轮评 2 帧
                fa = WORK / f"{pair[0]}_f{i}.png"
                fb = WORK / f"{pair[1]}_f{i}.png"
                frames.append((fa, fb))
            for pick, why in vlm_judge(clips[pair[0]], clips[pair[1]], frames):
                cnt[pick] += 1
        w = max(cnt, key=cnt.get)
        tally[" vs ".join(pair)] = cnt
        print(f"{pair[0]} vs {pair[1]}: {cnt}  →  {w if w != 'TIE' else '平手'}")
    return tally


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
        else DEFAULT_SRC
    WORK.mkdir(exist_ok=True)
    print(f"源: {src}  时长 {duration(src):.1f}s")
    if "--skip-calib" not in sys.argv:
        calibrate(src)
    clips = encode_variants(src)
    dur = duration(src)
    ts_list = [dur * f for f in (0.1, 0.35, 0.6, 0.85)]
    metrics = frame_metrics(clips, ts_list)
    tally = blind_compare(clips, ts_list)
    report = {"src": str(src), "cas_strength": CAS_STRENGTH,
              "metrics": metrics, "vlm": tally,
              "size_mb": {k: round(v.stat().st_size / 1e6, 2) for k, v in clips.items()}}
    (ROOT / "quality_ab_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\n报告: {ROOT / 'quality_ab_report.json'}")


if __name__ == "__main__":
    main()
