#!/usr/bin/env python3
"""sign_retry —— 候选区自愈: 重签「产物文件已齐全」但失败的候选(纯 LLM 步骤,不占 GPU).

只处理 三视图已存在 且 (特写已定 或 3 张特写候选已在) 的候选 ——
其余(三视图都没出来的)留给批量任务断点续跑,避免抢 GPU。
用法: python3 scripts/sign_retry.py [--dry]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sd import audition as A  # noqa: E402


def main(dry=False):
    if not A.CANDIDATES.exists():
        print("候选区为空")
        return
    signed, skipped, failed = [], [], []
    for d in sorted(A.CANDIDATES.iterdir()):
        if not d.is_dir() or not (d / "角色提示词.md").exists():
            continue
        turn = d / "1_设定图" / "三视图.png"
        refs = d / "2_视频参考"
        ready = (refs / "01_正面特写.png").exists() or \
            bool(list(refs.glob("_closeup_cand_*.png")))
        if not (turn.exists() and ready):
            skipped.append(d.name)               # 产物不全 → 不碰(交给断点续跑)
            continue
        if dry:
            print(f"[dry] 可重签: {d.name}")
            continue
        try:
            final = A.sign(d.name)
            signed.append(f"{d.name}→{final}")
            print(f"[自愈] {d.name} → {final}")
        except Exception as e:
            failed.append(f"{d.name}: {str(e)[:120]}")
            print(f"[自愈] {d.name} 仍失败: {e}")
    print(f"\n重签 {len(signed)} / 跳过(产物不全) {len(skipped)} / 仍失败 {len(failed)}")
    if skipped:
        print("跳过名单:", ", ".join(skipped))


if __name__ == "__main__":
    main("--dry" in sys.argv)
