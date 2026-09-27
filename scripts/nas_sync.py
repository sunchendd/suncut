#!/usr/bin/env python3
"""nas_sync —— 全量把已交付项目同步到绿联 NAS(短剧工坊/)。

幂等(同名同大小跳过),NAS 离线时只警告不报错。平时交付会自动单项目同步,
此脚本用于: 首次回填 / NAS 长期离线后的补齐 / 手动校对。

用法: cd ~/Desktop/suncut && python3 scripts/nas_sync.py [--dry]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sd import config, producer  # noqa: E402
from sd.project import Project  # noqa: E402


def sync_project(name, dry=False):
    proj = Project(name)
    if not proj.exists():
        return []
    script = proj.load_stage("script") or {}
    title = script.get("title_cn", name)
    key = f"{title}-{name}"
    files = {}
    # 桌面交付面: 短剧-*<项目名>* (mp4 各规格 + 封面)
    for f in sorted(config.DESKTOP.glob(f"短剧-*{name}*")):
        if f.is_file() and f.suffix in (".mp4", ".jpg"):
            files[f] = f.name
    # 项目内: 母版交付 + 制作报告
    for f in sorted((proj.path / "deliver").glob("*.mp4")):
        pass                                            # 交付 mp4 已含在桌面匹配里
    rep = proj.path / "制作报告.md"
    if rep.exists():
        files[rep] = rep.name
    if not files:
        return []
    if dry:
        print(f"[dry] {key}: {list(files.values())}")
        return []
    return producer._nas_sync(files, "成片", key)


def main():
    dry = "--dry" in sys.argv
    if not config.NAS_ROOT.exists():
        print(f"NAS 未挂载: {config.NAS_ROOT}(检查 /mnt/ugreen 或 fstab automount)")
        sys.exit(1)
    total = []
    for d in sorted((ROOT / "projects").iterdir()):
        if (d / "state.json").exists():
            total += sync_project(d.name, dry=dry)
    print(f"{'[dry] ' if dry else ''}同步完成: {len(total)} 个文件" +
          (f" → {config.NAS_ROOT}" if not dry else ""))


if __name__ == "__main__":
    main()
