#!/usr/bin/env python3
"""ab_upscale —— 超分模型 A/B: SPAN(主力) vs 4x-UltraSharp(盘上闲置).

同一条 regen 草稿分别走 master.upscale_clip(model=…)(含新感知链),
抽帧拉普拉斯方差 + glm-4.5v 盲评.胜者写回 sd/master.py 的 SPAN 常量.

用法: python3 scripts/ab_upscale.py [regen.mp4]     # 缺省 jiuwu-q1-s14
注意: 走 ComfyUI 8189,占用 GPU;与生成批互斥时先看护跑完再跑.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sd import master  # noqa: E402
from quality_ab import (WORK, duration, frame_metrics, grab,  # noqa: E402
                        sharpness, vlm_judge, blind_compare)

DEFAULT_SRC = ROOT / "projects" / "jiuwu" / "regen" / "jiuwu-q1-s14.mp4"


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    WORK.mkdir(exist_ok=True)
    master.ensure_server()
    clips = {}
    for name, model in (("SPAN", master.SPAN), ("UltraSharp", master.ULTRASHARP)):
        out = WORK / f"up_{name}.mp4"
        print(f"[ab_upscale] {name}({model}) 超分+感知链 …")
        path, secs = master.upscale_clip(src, out, model=model)
        print(f"[ab_upscale] {name} 完成 {secs:.0f}s → {path}")
        clips[name] = out
    dur = duration(clips["SPAN"])
    ts_list = [dur * f for f in (0.1, 0.35, 0.6, 0.85)]
    metrics = frame_metrics(clips, ts_list)
    tally = blind_compare(clips, ts_list)
    import json
    (ROOT / "ab_upscale_report.json").write_text(
        json.dumps({"src": str(src), "metrics": metrics, "vlm": tally},
                   ensure_ascii=False, indent=1))
    print("报告: ab_upscale_report.json")


if __name__ == "__main__":
    main()
