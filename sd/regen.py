"""母版档 v2 —— res_multistep14 本地重生成(非超分,真母版).

本地节点链(无云端 API): UNET int8 ref2va + qwen TE + MiniMaxH3ReferenceToVideo
(本地 r2v 条件化) + KSamplerSelect(res_multistep, Spectrum 注册) + 14 步.
可选 turbo(8步+LoRA) 为"日常档".
"""
import json
import re
import time
import urllib.request
from pathlib import Path

from . import config

COMFY = "http://127.0.0.1:8189"
INPUT_DIR = Path("/home/sunchendd/sol-h3-spark-runtime/comfyui/input")

UNET_R2V = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
CLIP_QWEN = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VAE_VIDEO = "minimax_h3_video_vae_fp16.safetensors"
VAE_AUDIO = "minimax_h3_audio_vae_fp32.safetensors"


def _req(path, data=None, timeout=120):
    req = urllib.request.Request(COMFY + path,
                                 data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _stage_ref(src: Path):
    dst = INPUT_DIR / f"sdm-{re.sub(r'[^A-Za-z0-9_.-]', '_', src.stem)}{src.suffix}"
    if not dst.exists():
        dst.write_bytes(src.read_bytes())
    return dst.name


def build_workflow(row, seed, steps=14, sampler="res_multistep",
                   width=1344, height=768, length=124):
    imgs = []
    for i, ref in enumerate(row.get("references", [])):
        nid = f"ref{i}"
        imgs.append((nid, {
            "class_type": "LoadImage",
            "inputs": {"image": _stage_ref(Path(ref["path"]))}}))
    ref_links = [[nid, 0] for nid, _ in imgs]
    wf = {nid: node for nid, node in imgs}
    wf.update({
        "clip": {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": CLIP_QWEN, "type": "minimax",
                            "device": "default"}},
        "unet": {"class_type": "UNETLoader",
                 "inputs": {"unet_name": UNET_R2V, "weight_dtype": "default"}},
        "vae_v": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_VIDEO}},
        "vae_a": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_AUDIO}},
        "cond": {"class_type": "MiniMaxH3ReferenceToVideo",
                 "inputs": {"clip": ["clip", 0], "prompt": row["prompt"],
                            "width": width, "height": height, "length": length,
                            "ref_image_size": "match",
                            "vae": ["vae_v", 0], "audio_vae": ["vae_a", 0],
                            "ref_images": ref_links}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "guider": {"class_type": "BasicGuider",
                   "inputs": {"model": ["unet", 0], "conditioning": ["cond", 0]}},
        "sampler": {"class_type": "KSamplerSelect",
                    "inputs": {"sampler_name": sampler}},
        "sigmas": {"class_type": "BasicScheduler",
                   "inputs": {"model": ["unet", 0], "scheduler": "simple",
                              "steps": steps, "denoise": 1.0}},
        "ksample": {"class_type": "SamplerCustomAdvanced",
                    "inputs": {"noise": ["noise", 0], "guider": ["guider", 0],
                               "sampler": ["sampler", 0], "sigmas": ["sigmas", 0],
                               "latent_image": ["cond", 1]}},
        "dec": {"class_type": "VAEDecode",
                "inputs": {"samples": ["ksample", 0], "vae": ["vae_v", 0]}},
        "dec_a": {"class_type": "VAEDecodeAudio",
                  "inputs": {"samples": ["ksample", 0], "vae": ["vae_a", 0]}},
        "cv": {"class_type": "CreateVideo",
               "inputs": {"images": ["dec", 0], "fps": 24, "audio": ["dec_a", 0]}},
        "save": {"class_type": "SaveVideo",
                 "inputs": {"video": ["cv", 0],
                            "filename_prefix": f"regen/{row['case_id']}",
                            "format": "auto"}},
    })
    return wf


def regen(row, seed=None, steps=14, sampler="res_multistep",
          width=1344, height=768, timeout=3600):
    """提交重生成工作流,轮询取回 mp4 路径."""
    seed = seed if seed is not None else row.get("seed", 42)
    wf = build_workflow(row, seed, steps=steps, sampler=sampler,
                        width=width, height=height)
    prompt_id = _req("/prompt", {"prompt": wf, "client_id": "sd-regen"})["prompt_id"]
    t0 = time.time()
    while True:
        h = _req(f"/history/{prompt_id}")
        if prompt_id in h:
            status = h[prompt_id].get("status", {})
            if status.get("status_str") == "error":
                msgs = str(h[prompt_id].get("messages"))[:600]
                raise RuntimeError(f"regen 执行错误: {msgs}")
            break
        if time.time() - t0 > timeout:
            raise RuntimeError("regen 超时")
        time.sleep(5)
    gifs = [g for v in h[prompt_id]["outputs"].values() for g in v.get("gifs", [])]
    vids = [g for v in h[prompt_id]["outputs"].values() for g in v.get("videos", [])]
    out = vids or gifs
    if not out:   # SaveVideo 记录也可能在 images 里(animated);兜底按前缀扫盘
        import subprocess as sp
        r = sp.run(["find", "/home/sunchendd/sol-h3-spark-runtime/comfyui/output/regen",
                    "-name", f"{row['case_id']}*.mp4"], capture_output=True, text=True)
        files = sorted(r.stdout.split(), key=lambda p: Path(p).stat().st_mtime if Path(p).exists() else 0)
        if files:
            return files[-1], time.time() - t0
        raise RuntimeError("regen 无视频输出: " + str(h[prompt_id]["outputs"])[:300])
    im = out[0]
    src = Path("/home/sunchendd/sol-h3-spark-runtime/comfyui/output") / \
        im.get("subfolder", "") / im["filename"]
    if not src.exists():
        raise RuntimeError(f"regen 产物缺失: {src}")
    return str(src), time.time() - t0


def run(proj, case_id, steps=14, sampler="res_multistep", seed=None):
    sb = proj.load_stage("storyboard")
    row = next((r for r in (json.loads(l) for l in open(sb["jsonl"]))
                if r["case_id"] == case_id), None)
    if row is None:
        raise KeyError(f"没有镜头 {case_id}")
    out = proj.path / "regen" / f"{case_id}-s{steps}.mp4"
    out.parent.mkdir(exist_ok=True)
    try:
        path, secs = regen(row, seed=seed, steps=steps, sampler=sampler)
    except RuntimeError as e:
        if "CUBLAS" in str(e) or "1344" not in str(e):
            raise
        # int8 栈高分辨率 CUBLAS 兜底: 降到 832x480 再试
        path, secs = regen(row, seed=seed, steps=steps, sampler=sampler,
                           width=832, height=480)
    out.write_bytes(Path(path).read_bytes())
    print(f"[regen] {case_id} {steps}步 {secs:.0f}s → {out}")
    return str(out)
