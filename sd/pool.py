"""演员库 —— 解析 AI角色工坊 的角色提示词.md 为可招募档案."""
import re
from pathlib import Path

from . import config


def scan(include_incomplete=False):
    """扫描工坊角色: FACE DNA / 默认穿搭 / seed / ref2va 参考图三件套.

    默认只返回参考图齐全(可直接开拍)的角色;include_incomplete=True 供招聘补图.
    """
    chars = []
    for d in sorted((config.WORKSHOP / "素材").iterdir()):
        md = d / "角色提示词.md"
        if not d.is_dir() or not md.exists():
            continue
        text = md.read_text(encoding="utf-8")

        def block_after(pattern):
            m = re.search(pattern + r"[^\n]*\n+\s*((?:>[^\n]*\n?)+)", text)
            if not m:
                return ""
            return " ".join(l.lstrip("> ").strip()
                            for l in m.group(1).splitlines() if l.strip()).strip()

        face = block_after(r"\*\*FACE\*\*")
        outfit = block_after(r"\*\*默认穿搭")
        portrait = block_after(r"\*\*参考立绘")
        seed = re.search(r"seed[：:]\s*(\d+)", text)
        refs = {}
        for f in sorted((d / "2_视频参考").glob("*.png")):
            key = {"01": "closeup", "02": "front", "03": "side"}.get(f.name[:2])
            if key:
                refs[key] = str(f)
        if not face:
            continue
        if not include_incomplete and not refs.get("closeup"):
            continue
        chars.append({"name": d.name, "face_dna": face,
                      "outfit_dna": outfit or "casual outfit per close-up reference",
                      "portrait": portrait if portrait and Path(portrait).exists() else None,
                      "look": "game" if "游戏还原" in text else "cn",
                      "seed": int(seed.group(1)) if seed else config.CHAR_SEED_BASE,
                      "refs": refs, "dir": str(d)})
    return chars


def scan_all():
    return scan(include_incomplete=True)


def brief(chars):
    """给选角 LLM 看的简况."""
    return "\n".join(
        f"- {c['name']} | {c['face_dna'][:110]}... | 参考图: {sorted(c['refs'])}"
        for c in chars)


def find(chars, name):
    for c in chars:
        if c["name"] == name:
            return c
    raise KeyError(f"演员库没有 {name};可选: {[c['name'] for c in chars]}")
