"""Qwen-Image-2.1 适配器 —— 招聘 agent 的"给演员补参考图"通道.

工坊里只有部分角色有 ref2va 参考三件套(特写/正面/侧面);本模块:
1. 从现成的 Qwen 三视图裁出 front/side(ffmpeg 三等分)
2. 用 Qwen-Image-2.1 文生图补一张锁脸特写(桌面工作流 §2.2: 锁脸必须靠特写)
"""
import re
import subprocess
from pathlib import Path

from . import config

VENV_PY = config.HOME / "venvs/imagegen/bin/python"
MODEL = config.HOME / "models/Qwen-Image-2.1"

CLOSEUP_TMPL = """Photorealistic beauty close-up portrait for a live-action film production,
head and shoulders, of the exact same young woman: {face}
Wearing {outfit} (visible at shoulders). {makeup}
doe eyes with natural catchlights, visible pores and fine skin texture, soft film grain,
butterfly lighting with a soft rim light, shot on 85mm f/2.8, shallow depth of field,
neutral dark studio background, cinematic color grading, sharp focus on the eyes"""

CLOSEUP_NEG = ("塑料感皮肤, 过度磨皮, 蜡像感, CG渲染, 3D渲染, 插画, 动漫风格, 洋娃娃感, "
               "过度饱和, 美颜滤镜, 阴郁的眼神, 表情冷漠僵硬, 肤色惨白病态")


def _run_ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-300:])


def crop_views(char_dir: Path, out_dir: Path):
    """三视图(FRONT/SIDE/BACK 横排)三等分裁出 front/side 全身."""
    src = char_dir / "1_设定图/三视图.png"
    if not src.exists():
        raise FileNotFoundError(f"没有三视图: {src}")
    import json
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "json", str(src)],
                           capture_output=True, text=True)
    w, h = (lambda s: (s["streams"][0]["width"], s["streams"][0]["height"]))(
        json.loads(probe.stdout))
    third = w // 3
    outs = {}
    for i, key in ((0, "front"), (1, "side")):
        dst = out_dir / {"front": "02_正面全身.png", "side": "03_侧面全身.png"}[key]
        _run_ffmpeg(["-i", str(src), "-vf", f"crop={third}:{h}:{i * third}:0", str(dst)])
        outs[key] = dst
    return outs


def gen_closeup(char: dict, out_dir: Path, steps=25, width=1024, height=1280,
                seeds=None, pick_best=True):
    """Qwen-Image-2.1 文生图锁脸特写. 多种子出候选,VLM 对照三视图选最像的一张."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "01_正面特写.png"
    face, outfit = char["face_dna"], char["outfit_dna"]
    makeup = ("natural fresh makeup, healthy rosy complexion, a warm friendly expression"
              if "少年" not in face and "girl" not in face.lower()
              else "natural fresh complexion, lively curious expression")
    prompt = CLOSEUP_TMPL.format(face=face, outfit=outfit, makeup=makeup)
    seeds = seeds or [char.get("seed", 42) + off for off in (0, 777, 1234)][:3 if pick_best else 1]
    cands = []
    for s in seeds:
        c = out_dir / f"_closeup_cand_{s}.png"
        if not c.exists():
            _gen_one(prompt, s, c, steps, width, height)
        cands.append((s, c))
    if not pick_best or len(cands) == 1:
        cands[0][1].rename(dst)
        return dst
    best = _vlm_pick(char, cands)
    Path(best).rename(dst)
    for _, c in cands:
        c.unlink(missing_ok=True)
    return dst


def _gen_one(prompt, seed, dst, steps, width, height):
    script = f"""
import os
os.environ.setdefault("DIFFUSERS_ATTN_BACKEND", "_native_cudnn")
import torch
torch.set_float32_matmul_precision("high")
from diffusers import QwenImage21Pipeline
pipe = QwenImage21Pipeline.from_pretrained(r"{MODEL}", torch_dtype=torch.bfloat16).to("cuda")
try: pipe.vae.enable_tiling()
except Exception: pass
out = pipe(prompt={prompt!r}, negative_prompt={CLOSEUP_NEG!r}, true_cfg_scale=4.0,
           height={height}, width={width}, num_inference_steps={steps}, generator=torch.Generator("cuda").manual_seed({seed}))
img = out.images[0] if hasattr(out, "images") else out[0][0]
img.save(r"{dst}")
print("SAVED", r"{dst}")
"""
    tmp = dst.with_suffix(".py")
    tmp.write_text(script)
    r = subprocess.run([str(VENV_PY), str(tmp)], capture_output=True, text=True, timeout=1800)
    tmp.unlink(missing_ok=True)
    if r.returncode != 0 or not dst.exists():
        raise RuntimeError(f"Qwen 特写生成失败: {r.stderr[-500:]} {r.stdout[-300:]}")
    return dst


def _vlm_pick(char, cands):
    """VLM: 候选特写 vs 三视图裁出的正面全身,选同一人且最写实的一张."""
    from . import llm
    body = Path(char["dir"]) / "2_视频参考/02_正面全身.png"
    if not body.exists():
        body = next((Path(char["dir"]) / "1_设定图").glob("三视图*.png"), None)
    imgs = [str(p) for _, p in cands] + ([str(body)] if body else [])
    n = len(cands)
    text = (f"前{n}张是同一角色的特写候选图,最后一张是该角色的全身设定参考。"
            f"角色设定: {char['face_dna'][:300]}\n"
            f"哪张候选与设定是同一人且最写实(发型/瞳色/脸型/肤色匹配,无蜡像感)?\n"
            '只输出 JSON: {"best": 候选序号(1开始), "scores": [每张0-10], "reason": "一句话"}')
    d = llm.extract_json(llm.vision(text, imgs))
    i = max(0, min(n - 1, int(d.get("best", 1)) - 1))
    print(f"[招聘] 特写候选得分 {d.get('scores')} → 选 #{i + 1}: {d.get('reason', '')}")
    return cands[i][1]


def buildrefs(char: dict):
    """给工坊角色补齐 ref2va 参考三件套(已齐则跳过). 返回 refs dict."""
    char_dir = Path(char["dir"])
    out_dir = char_dir / "2_视频参考"
    out_dir.mkdir(exist_ok=True)
    have = {f.name[:2] for f in out_dir.glob("*.png")}
    if "01" not in have:
        print(f"[招聘] Qwen-Image-2.1 生成 {char['name']} 锁脸特写…")
        gen_closeup(char, out_dir)
    if "02" not in have or "03" not in have:
        print(f"[招聘] 裁切 {char['name']} 三视图 → 正面/侧面全身…")
        crop_views(char_dir, out_dir)
    refs = {}
    for f in sorted(out_dir.glob("*.png")):
        key = {"01": "closeup", "02": "front", "03": "side"}.get(f.name[:2])
        if key:
            refs[key] = str(f)
    return refs
