"""H3 转台参考集 —— t2va 让角色原地缓转,抽帧得多角度参考(漫剧工作流已验证法).

自动补图(Qwen 特写+三视图裁切)的角色身份锁 8-9 分,转台帧参考可再强化:
姿势自然连续、光影统一、视角真实。抽帧 8/60/110 ≈ 正面/四分之三/侧面。
"""
import json
import re
import subprocess
from pathlib import Path

from . import config


def turntable(char, backup=True):
    """给角色生成转台视频并替换 2_视频参考 的 02/03(原裁切图存 归档/转台备份/)."""
    from .director import _run_infer
    safe = re.sub(r"[^A-Za-z0-9_-]", "", char["name"]) or "tt"
    proj_dir = f"turntable-{safe}"
    outdir = config.SD_RUNTIME / proj_dir
    prompt = (f"detailed_description: a full-body character reference turntable of a young "
              f"woman: {char['face_dna']} She wears {char['outfit_dna']}. She stands in a "
              f"relaxed neutral pose and slowly rotates on the spot from a front-facing view "
              f"to a three-quarter view to a side view over five seconds, fixed camera at "
              f"chest height, even soft studio lighting, clean plain background, "
              f"photorealistic real person, no cuts, no text. "
              f"overall_soundscape: quiet room tone. "
              f"non_diegetic_music: none")
    row = {"case_id": proj_dir, "seed": char["seed"], "task": "t2va",
           "references": [], "prompt": prompt}
    log = config.SD_RUNTIME / proj_dir / "gen.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    code, batch = _run_infer([row], outdir, log)
    video = batch / proj_dir / "stage2/refined_1344x768_121f.mp4"
    if not video.exists():
        raise RuntimeError(f"转台生成失败(日志 {log})")

    ref_dir = Path(char["dir"]) / "2_视频参考"
    bak = Path(char["dir"]) / "归档" / "转台备份"
    if backup:
        bak.mkdir(parents=True, exist_ok=True)
    saved = {}
    for frame, name in ((8, "02_正面全身.png"), (110, "03_侧面全身.png")):
        dst = ref_dir / name
        if backup and dst.exists():
            b = bak / name
            i = 1
            while b.exists():
                b = bak / f"{name[:-4]}_{i}.png"
                i += 1
            dst.replace(b)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
                            "-vf", f"select=eq(n\\,{frame})",
                            "-vsync", "vfr", "-frames:v", "1", str(dst)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not dst.exists():
            raise RuntimeError(f"抽帧失败 {name}: {r.stderr[-200:]}")
        saved[name] = str(dst)
    return {"video": str(video), "refs": saved, "note": "02/03 已替换为转台帧(原三视图裁切在 归档/转台备份)"}
