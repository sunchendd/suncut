"""交付增强 —— 封面(最佳帧+剧名字卡) + 自动制作报告(可审阅可追溯)."""
import json
import subprocess
from pathlib import Path

from . import config
from .metrics import Metrics

FONT_TTC = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
VENV_PY = config.HOME / "venvs/imagegen/bin/python"

# ffmpeg drawtext 对 ttc 多 face 会取错 face 出豆腐块, 用 PIL 按 face 名精确选 SC
_PIL_TITLE = (
    "import sys\n"
    "from PIL import Image, ImageDraw, ImageFont\n"
    "src, dst, title, tagline = sys.argv[1:5]\n"
    "im = Image.open(src).convert('RGB')\n"
    "W, H = im.size\n"
    "def load(face_hint, size):\n"
    "    for idx in range(8):\n"
    "        try:\n"
    "            f = ImageFont.truetype(FONT_PATH, size, index=idx)\n"
    "            if face_hint in ' '.join(f.getname()):\n"
    "                return f\n"
    "        except Exception:\n"
    "            break\n"
    "    return ImageFont.truetype(FONT_PATH, size)\n"
    "FONT_PATH = " + repr(FONT_TTC) + "\n"
    "# 中上区域渐变压暗,字卡更醒目\n"
    "grad = Image.new('L', (1, H), 0)\n"
    "for y in range(H):\n"
    "    t = 1 - min(1, abs(y - H * 0.30) / (H * 0.30))\n"
    "    grad.putpixel((0, y), int(150 * t))\n"
    "im = Image.composite(Image.new('RGB', (W, H), (0, 0, 0)), im, grad.resize((W, H)))\n"
    "d = ImageDraw.Draw(im)\n"
    "def center(text, font, y, fill, stroke):\n"
    "    bb = d.textbbox((0, 0), text, font=font, stroke_width=stroke)\n"
    "    d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], y), text, font=font, fill=fill,\n"
    "           stroke_width=stroke, stroke_fill=(0, 0, 0))\n"
    "f1 = load('SC', int(W * 0.115))\n"
    "f2 = load('SC', int(W * 0.040))\n"
    "center(title, f1, int(H * 0.24), (255, 255, 255), 6)\n"
    "center(tagline, f2, int(H * 0.24) + f1.size + int(W * 0.06), (235, 235, 235), 4)\n"
    "im.save(dst, quality=92)\n"
    "print('COVER_OK', dst)\n"
)


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    return r


def make_cover(proj):
    """最佳镜头(审片分最高)中段帧 → 竖版 1080x1920 → PIL 字卡(剧名+logline)."""
    rv = proj.load_stage("review")
    if not rv or not rv["results"]:
        raise RuntimeError("没有审片结果,无法选封面帧")
    best = max(rv["results"],
               key=lambda r: (r.get("identity", 0) + r.get("composition", 0)
                              + r.get("action", 0)) if r.get("video") else -1)
    video = best.get("video")
    if not video or not Path(video).exists():
        raise RuntimeError("最佳镜头视频缺失")
    script = proj.load_stage("script")
    title = script.get("title_cn", proj.name)
    tagline = script.get("logline", "")[:20]
    frame = proj.path / "_cover_frame.png"
    cover = proj.path / "cover.jpg"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
          "-vf", "select=eq(n\\,60),crop=432:768:456:0,scale=1080:1920:flags=lanczos,"
          "eq=saturation=1.05",
          "-frames:v", "1", str(frame)])
    py = proj.path / "_cover_title.py"
    py.write_text(_PIL_TITLE)
    r = subprocess.run([str(VENV_PY), str(py), str(frame), str(cover),
                        title, tagline], capture_output=True, text=True, timeout=120)
    frame.unlink(missing_ok=True)
    py.unlink(missing_ok=True)
    if r.returncode != 0 or not cover.exists():
        raise RuntimeError("封面字卡失败: " + r.stderr[-300:])
    dst = config.DESKTOP / f"短剧-{title}-{proj.name}-封面.jpg"
    dst.write_bytes(cover.read_bytes())
    return {"cover": str(cover), "desktop": str(dst)}


def write_report(proj):
    """制作报告: 剧目/选角/逐镜(审片分/重拍/选条)/耗时/产物路径."""
    script = proj.load_stage("script") or {}
    cast = proj.load_stage("cast") or {"cast": []}
    mats = proj.load_stage("materials") or {"scenes": []}
    rv = proj.load_stage("review") or {"results": []}
    picks = json.loads((proj.path / "picks.json").read_text()) if (
        proj.path / "picks.json").exists() else []
    state = proj.load_state()
    takes = state.get("takes", {})
    sc_by = {s["id"]: s for s in script.get("shots", [])}
    rv_by = {r["case"]: r for r in rv.get("results", [])}

    lines = [f"# 制作报告 · {script.get('title_cn', proj.name)}", "",
             f"> {script.get('logline', '')}", "",
             f"- 生成时间: {state.get('created', '')}",
             f"- 镜数: {len(script.get('shots', []))} × {config.SHOT_SECONDS:.2f}s"
             f" = {len(script.get('shots', [])) * config.SHOT_SECONDS:.1f}s",
             f"- 音乐: {mats.get('music_en', '')[:80]}…", "", "## 选角", ""]
    for r in cast["cast"]:
        lines.append(f"- **{r['char']}**({r['story_role']}): {r.get('reason', '')}"
                     f" | seed={r['profile'].get('seed')}")
    lines += ["", "## 逐镜", "",
              "| 镜 | 场景 | 出场 | 旁白 | 身份/动作/构图 | 选条 |", "|---|---|---|---|---|---|"]
    for p in picks:
        shot = sc_by.get(p["case"].split("-")[-1], {})
        r = rv_by.get(p["case"], {})
        n_take = len(takes.get(p["case"], []))
        lines.append(
            f"| {shot.get('id', '?')} | {shot.get('scene', '?')} | "
            f"{'+'.join(shot.get('cast', [])) or '空镜'} | {shot.get('narration_cn', '')} | "
            f"{r.get('identity', '-')}/{r.get('action', '-')}/{r.get('composition', '-')}"
            f"{f'(重拍{n_take})' if n_take else ''} | `{Path(p['picked']).name}` |")
    lines += ["", "## 阶段耗时", "", "```", Metrics(proj).summary(), "```", "", "## 产物", ""]
    for p in sorted((proj.path).glob("*.mp4")):
        lines.append(f"- {p.name} ({p.stat().st_size / 1e6:.1f}MB)")
    for d in sorted(config.DESKTOP.glob(f"短剧-*{proj.name}*")):
        lines.append(f"- 桌面/{d.name}")
    rep = proj.path / "制作报告.md"
    rep.write_text("\n".join(lines) + "\n")
    return str(rep)
