#!/usr/bin/env python3
"""stardew_refit —— 官方立绘 → VLM 精修 DNA → 重置计划(29 人).

步骤: 读立绘(stardew_refs/<名>.png) + 现有 DNA(素材库/名单兜底)
      → glm-4.5v 精读像素立绘,逐项对齐发色/发型/瞳色/肤色/服装
      → 落盘 stardew_refit_plan.json;--submit 直接提交 /api/audition/refit
用法: python3 scripts/stardew_refit.py [--submit] [--only 名字1,名字2]
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sd import llm, pool  # noqa: E402
import importlib.util  # noqa: E402

BASE = "http://127.0.0.1:8620"
REFS = Path(__file__).resolve().parent.parent / "stardew_refs"

_spec = importlib.util.spec_from_file_location(
    "sc", Path(__file__).resolve().parent / "stardew_cast.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)
CAST_BY_NAME = {n: (p, f, o) for n, p, f, o in sc.CAST}

REFINE_TMPL = """这是游戏《星露谷物语》角色「{name}」的官方像素立绘。
该角色当前的写实化 DNA(可能偏离立绘):
face: {face}
outfit: {outfit}

请精读立绘的每一项视觉特征,然后**修订** DNA 使其与立绘严格一致:
- 发色(精确色名,如 dyed deep violet / sandy blond with darker roots)、发型长度与造型
- 瞳色、肤色、脸型、可见的表情气质
- 服装与配饰:颜色/款式/层次逐项照立绘描述(立绘只到胸像,下半身按原 DNA 保留)
- 保留原 DNA 里的年龄/体型/职业气质词(立绘看不出),其余以立绘为准
- 输出仍是"写实真人摄影提示词"风格的一段英文,不要出现 pixel/cartoon/game art 字样
只输出 JSON: {{"face_dna": "英文一段", "outfit_dna": "英文一段", "changed": ["改动点1","改动点2"]}}"""


def current_dna(name):
    chars = pool.scan_all()
    for c in chars:
        if c["name"].endswith(f"_{name}"):
            return c["face_dna"], c["outfit_dna"]
    if name in CAST_BY_NAME:
        return CAST_BY_NAME[name][1], CAST_BY_NAME[name][2]
    raise KeyError(f"找不到 {name} 的现有 DNA")


def refine(name, face, outfit, retries=2):
    text = REFINE_TMPL.format(name=name, face=face, outfit=outfit)
    for i in range(retries + 1):
        try:
            out = llm.vision(text, [str(REFS / f"{name}.png")])
            d = llm.extract_json(out)
            if len(d.get("face_dna", "")) >= 40 and len(d.get("outfit_dna", "")) >= 20:
                return d
        except Exception as e:
            print(f"  [{name}] 重试{i + 1}: {str(e)[:80]}")
            time.sleep(2)
    raise RuntimeError(f"{name} VLM 精修失败")


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    plan = []
    for png in sorted(REFS.glob("*.png")):
        name = png.stem
        if only and name not in only:
            continue
        face, outfit = current_dna(name)
        d = refine(name, face, outfit)
        pos = CAST_BY_NAME.get(name, ("",))[0] if name in CAST_BY_NAME else ""
        if not pos:                                 # 原有 4 人的定位从素材 md 读
            pos = ""
        plan.append({"name": name, "positioning_cn": pos,
                     "face_dna": d["face_dna"], "outfit_dna": d["outfit_dna"],
                     "portrait": str(png), "ref_changed": d.get("changed", [])})
        print(f"[精修] {name}: {'; '.join(d.get('changed', [])[:3])}")
    out = Path(__file__).resolve().parent.parent / "stardew_refit_plan.json"
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    print(f"\n{len(plan)} 人重置计划 → {out}")
    if "--submit" in sys.argv:
        body = json.dumps({"plan": plan}).encode()
        req = urllib.request.Request(BASE + "/api/audition/refit", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        print("job:", d["job_id"], "|", d["job"]["title"])
        open("/tmp/stardew_refit_jid", "w").write(d["job_id"])


if __name__ == "__main__":
    main()
