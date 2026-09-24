"""母版档 —— 草稿(infer.py 1344x768) → ComfyUI SPANx2 神经超分 → lanczos 1920x1088
→ PNG 无损 → ffmpeg CRF14 编码(1080p 清晰版链, 桌面工作流 §质量阶梯 日常+档).

对应经验: SaveVideo 'auto' 码率会压碎细节,母版必须 PNG+自编码;
SPAN supersample-then-downscale 优于直接放大; 基准分辨率决定观感.
"""
import json
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from . import config

COMFY = "http://127.0.0.1:8189"
SPAN = "2xNomosUni_span_multijpg.safetensors"
ULTRASHARP = "4x-UltraSharp.pth"


def _req(path, data=None, timeout=120):
    req = urllib.request.Request(COMFY + path,
                                 data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


INPUT_DIR = Path("/home/sunchendd/sol-h3-spark-runtime/comfyui/input")


def _upload(video: Path):
    """ComfyUI 跑在宿主机: 直接落到 input 目录(video_upload 端点 405)."""
    dst = INPUT_DIR / f"sdm-{video.stem[:24]}{video.suffix}"
    dst.write_bytes(video.read_bytes())
    return dst.name


def _workflow(video_name, model=SPAN, width=1920, height=1088, prefix="master"):
    return {
        "1": {"class_type": "LoadVideo", "inputs": {"file": video_name}},
        "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
        "3": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": model}},
        "4": {"class_type": "ImageUpscaleWithModel",
              "inputs": {"upscale_model": ["3", 0], "image": ["2", 0]}},
        "5": {"class_type": "ImageScale",
              "inputs": {"upscale_method": "lanczos", "width": width,
                         "height": height, "crop": "disabled", "image": ["4", 0]}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0],
                                                    "filename_prefix": prefix}},
    }


def upscale_clip(draft: Path, out_mp4: Path, model=SPAN, crf=14,
                 width=1920, height=1088, timeout=3600):
    """单条草稿 → 1080p 母版. 返回 (out_mp4, 耗时秒)."""
    t0 = time.time()
    name = _upload(draft)
    wf = _workflow(name, model=model, width=width, height=height,
                   prefix=f"{draft.stem[:20]}")
    prompt_id = _req("/prompt", {"prompt": wf, "client_id": "sd-master"})["prompt_id"]
    while True:
        h = _req(f"/history/{prompt_id}")
        if prompt_id in h:
            break
        time.sleep(3)
    outputs = h[prompt_id]["outputs"]
    images = [im for v in outputs.values() for im in v.get("images", [])
              if im.get("type") == "output"]   # LoadVideo 也回写 input 记录,只取真输出
    if not images:
        raise RuntimeError(f"母版超分无输出: {h[prompt_id].get('status')}")
    # ComfyUI 在宿主机: PNG 直接落在 output 目录,无需 /view 下载
    out_dir = INPUT_DIR.parent / "output"
    frame_dir = out_mp4.parent / f"{out_mp4.stem}_png"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for i, im in enumerate(sorted(images, key=lambda x: x["filename"])):
        src = out_dir / im.get("subfolder", "") / im["filename"]
        dst = frame_dir / f"f_{i:05d}_.png"
        if src != dst:
            src.replace(dst) if src.parent == frame_dir else dst.write_bytes(src.read_bytes())
    # PNG → CRF14 + 原音轨
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "24",
         "-i", str(frame_dir / "f_%05d_.png"), "-i", str(draft),
         "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", str(crf),
         "-preset", "slow", "-c:a", "copy", str(out_mp4)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("母版编码失败: " + r.stderr[-300:])
    return out_mp4, time.time() - t0


def ensure_server():
    """8189 不在则拉起(NVFP4 栈); 在则直接用."""
    try:
        _req("/system_stats", timeout=5)
        return True
    except Exception:
        pass
    subprocess.Popen(
        ["bash", str(config.SOL_PKG / "run-comfyui-nvfp4.sh")],
        stdout=open("/tmp/comfy8189.log", "w"), stderr=subprocess.STDOUT,
        start_new_session=True)
    for _ in range(60):
        time.sleep(5)
        try:
            _req("/system_stats", timeout=5)
            return True
        except Exception:
            continue
    raise RuntimeError("ComfyUI 8189 启动超时(见 /tmp/comfy8189.log)")


def run(proj, force=False):
    """整片母版化: 交付选条(picks)逐镜超分, 重拼 1080p 横版+竖版到桌面."""
    if proj.stage_done("master") and not force:
        return proj.load_stage("master")
    picks = json.loads((proj.path / "picks.json").read_text())
    ensure_server()
    outs = []
    for p in picks:
        draft = Path(p["picked"])
        out = proj.path / "master" / f"{p['case']}-1080p.mp4"
        out.parent.mkdir(exist_ok=True)
        if out.exists():
            outs.append(str(out))
            continue
        print(f"[母版] 超分 {p['case']} …")
        path, secs = upscale_clip(draft, out)
        print(f"[母版] {p['case']} 完成 {secs:.0f}s")
        outs.append(str(path))
    data = {"clips": outs}
    proj.save_stage("master", data, meta={"clips": len(outs)})
    return data
