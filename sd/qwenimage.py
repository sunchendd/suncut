"""Qwen-Image-2.1 适配器 —— 招聘 agent 的"给演员补参考图"通道.

工坊里只有部分角色有 ref2va 参考三件套(特写/正面/侧面);本模块:
1. 从现成的 Qwen 三视图裁出 front/side(ffmpeg 三等分)
2. 用 Qwen-Image-2.1 文生图补一张锁脸特写(桌面工作流 §2.2: 锁脸必须靠特写)
"""
import re
import subprocess
import time
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
    out_dir.mkdir(parents=True, exist_ok=True)   # 裁切输出目录不预建会被 ffmpeg 拒写
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
    """Qwen-Image-2.1 文生图锁脸特写. 多种子出候选,VLM 对照三视图选最像的一张.

    char 带 portrait(参考立绘路径)时走参考图条件生成,五官/发色/服装贴立绘。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "01_正面特写.png"
    face, outfit = char["face_dna"], char["outfit_dna"]
    makeup = ("natural fresh makeup, healthy rosy complexion, a warm friendly expression"
              if "少年" not in face and "girl" not in face.lower()
              else "natural fresh complexion, lively curious expression")
    prompt = CLOSEUP_TMPL.format(face=face, outfit=outfit, makeup=makeup)
    if char.get("portrait"):
        prompt = ("Recreate the exact character from the reference portrait as a "
                  "photorealistic live-action person for a film production, keeping the "
                  "identical hairstyle, hair color, eye color, skin tone and outfit "
                  "colors. " + prompt)
    refs = [char["portrait"]] if char.get("portrait") else None
    seeds = seeds or [char.get("seed", 42) + off for off in (0, 777, 1234)][:3 if pick_best else 1]
    cands = []
    for s in seeds:
        c = out_dir / f"_closeup_cand_{s}.png"
        if not c.exists():
            _gen_one(prompt, s, c, steps, width, height, ref_images=refs)
        cands.append((s, c))
    if not pick_best or len(cands) == 1:
        cands[0][1].rename(dst)
        return dst
    best = _vlm_pick(char, cands)
    Path(best).rename(dst)
    for _, c in cands:
        c.unlink(missing_ok=True)
    return dst


def _gen_one(prompt, seed, dst, steps, width, height, neg=None, timeout=1800,
             ref_images=None):
    """文生图 / 参考图条件生成(ref_images=参考图路径列表时,Qwen2.1 原生看图还原)."""
    ref_code = ""
    if ref_images:
        ref_code = ("from PIL import Image\n"
                    "refs = [Image.open(" + repr(str(ref_images[0])) +
                    ").convert('RGB').resize((512, 512))]\n"
                    + "".join("refs.append(Image.open(" + repr(str(p)) +
                              ").convert('RGB').resize((512, 512)))\n"
                              for p in ref_images[1:]))
    img_kw = "image=refs, " if ref_images else ""
    script = f"""
import os, time, sys
os.environ.setdefault("DIFFUSERS_ATTN_BACKEND", "_native_cudnn")
_t0 = time.time()
def _say(msg):
    try: print(msg, flush=True)
    except (BrokenPipeError, OSError):   # 父进程(服务)重启后管道断,静默继续跑完存盘
        pass
def _cb(p, i, t, kw):
    if i % 5 == 0 or i == {steps} - 1:
        _say(f"STEP {{i + 1}}/{{{steps}}} {{time.time() - _t0}}s")
    return kw   # diffusers 要求回调返回 callback_kwargs
{ref_code}
import torch
torch.set_float32_matmul_precision("high")
from diffusers import QwenImage21Pipeline
pipe = QwenImage21Pipeline.from_pretrained(r"{MODEL}", torch_dtype=torch.bfloat16).to("cuda")
try: pipe.vae.enable_tiling()
except Exception: pass
try:
    pipe.set_progress_bar_config(disable=True)
except Exception: pass
kw = dict(callback_on_step_end=_cb)
out = pipe(prompt={prompt!r}, {img_kw}negative_prompt={neg or CLOSEUP_NEG!r}, true_cfg_scale=4.0,
           height={height}, width={width}, num_inference_steps={steps},
           generator=torch.Generator("cuda").manual_seed({seed}), **kw)
img = out.images[0] if hasattr(out, "images") else out[0][0]
img.save(r"{dst}")
_say("SAVED " + r"{dst}" + f" {{time.time() - _t0:.0f}}s")
"""
    tmp = dst.with_suffix(".py")
    tmp.write_text(script)
    errfile = dst.with_suffix(".stderr")
    with open(errfile, "w") as ef:
        proc = subprocess.Popen([str(VENV_PY), str(tmp)], stdout=subprocess.PIPE,
                                stderr=ef, text=True)
        import time as _t
        deadline = _t.time() + timeout
        try:
            for line in proc.stdout:
                print(f"[imagegen] {line.rstrip()}")
                if _t.time() > deadline:
                    proc.kill()
                    raise RuntimeError("图像生成超时被杀")
        finally:
            proc.wait()
    tmp.unlink(missing_ok=True)
    err = errfile.read_text() if errfile.exists() else ""
    errfile.unlink(missing_ok=True)
    if proc.returncode != 0 or not dst.exists():
        raise RuntimeError(f"Qwen 图像生成失败: rc={proc.returncode} stderr={err[-800:]}")
    return dst


def _gen_many(jobs, ref_images=None, timeout=2700):
    """一次加载模型,顺序生成多张图(省去每张 ~160s 的重复加载).

    jobs: [{prompt, seed, dst, width, height, steps, neg?}, ...]
    已存在的 dst 自动跳过(断点续跑);任一张失败即抛错(调用方决定回退)。
    """
    import json as _json
    all_jobs = list(jobs)
    jobs = [j for j in jobs if not Path(j["dst"]).exists()]
    if not jobs:
        return [str(Path(j["dst"])) for j in all_jobs]
    ref_code = ""
    if ref_images:
        ref_code = ("from PIL import Image\n"
                    "refs = [Image.open(" + repr(str(ref_images[0])) +
                    ").convert('RGB').resize((512, 512))]\n"
                    + "".join("refs.append(Image.open(" + repr(str(p)) +
                              ").convert('RGB').resize((512, 512)))\n"
                              for p in ref_images[1:]))
    plan = _json.dumps([{k: (str(v) if k == "dst" else v) for k, v in j.items()
                         if k in ("prompt", "seed", "dst", "width", "height", "steps", "neg")}
                        for j in jobs], ensure_ascii=False)
    script = f"""
import os, time, json
os.environ.setdefault("DIFFUSERS_ATTN_BACKEND", "_native_cudnn")
_t0 = time.time()
def _say(msg):
    try: print(msg, flush=True)
    except (BrokenPipeError, OSError):
        pass
{ref_code}
import torch
torch.set_float32_matmul_precision("high")
from diffusers import QwenImage21Pipeline
pipe = QwenImage21Pipeline.from_pretrained(r"{MODEL}", torch_dtype=torch.bfloat16).to("cuda")
try: pipe.vae.enable_tiling()
except Exception: pass
try: pipe.set_progress_bar_config(disable=True)
except Exception: pass
_jobs = json.loads({plan!r})
for i, j in enumerate(_jobs, 1):
    _say("JOB %d/%d %s ..." % (i, len(_jobs), os.path.basename(j["dst"])))
    t1 = time.time()
    def _cb(p, step, t, kw):
        if step % 10 == 0:
            _say("  STEP %d/%d %.0fs" % (step + 1, j["steps"], time.time() - t1))
        return kw
    out = pipe(prompt=j["prompt"], image=(refs if {bool(ref_images)} else None),
               negative_prompt=j.get("neg"), true_cfg_scale=4.0,
               height=j["height"], width=j["width"],
               num_inference_steps=j["steps"],
               generator=torch.Generator("cuda").manual_seed(j["seed"]),
               callback_on_step_end=_cb)
    img = out.images[0] if hasattr(out, "images") else out[0][0]
    img.save(j["dst"])
    _say("SAVED %s %.0fs" % (j["dst"], time.time() - t1))
_say("ALL_DONE %.0fs" % (time.time() - _t0))
"""
    first = Path(jobs[0]["dst"])
    tmp = first.with_name(f"_bundle_{int(time.time())}.py")
    tmp.write_text(script)
    errfile = tmp.with_suffix(".stderr")
    with open(errfile, "w") as ef:
        proc = subprocess.Popen([str(VENV_PY), str(tmp)], stdout=subprocess.PIPE,
                                stderr=ef, text=True)
        deadline = time.time() + timeout * max(1, len(jobs))
        try:
            for line in proc.stdout:
                print(f"[imagegen] {line.rstrip()}")
                if time.time() > deadline:
                    proc.kill()
                    raise RuntimeError("批量图像生成超时被杀")
        finally:
            proc.wait()
    tmp.unlink(missing_ok=True)
    err = errfile.read_text() if errfile.exists() else ""
    errfile.unlink(missing_ok=True)
    missing = [j["dst"] for j in jobs if not Path(j["dst"]).exists()]
    if proc.returncode != 0 or missing:
        raise RuntimeError(f"批量生成失败 rc={proc.returncode} 未产出{missing[:2]} "
                           f"stderr={err[-500:]}")
    return [str(Path(j["dst"])) for j in all_jobs]


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
