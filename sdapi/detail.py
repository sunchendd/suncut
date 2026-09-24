"""detail —— 读模型:把 projects/<name>/ 下散落的 JSON 拼成前端可直接渲染的一份详情.

原则: 只读、容错(任何阶段缺失都置 None),绝不触发生成动作.
"""
import json
import time
from pathlib import Path

from sd import config as sd_config, lint
from sd.metrics import Metrics
from sd.project import Project

from .jobs import manager

STAGE_ORDER = ["cast", "materials", "script", "storyboard", "generate", "review", "deliver"]
DELIVER_EXTS = {".mp4", ".jpg", ".png", ".md", ".srt", ".txt"}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def _file_dto(p):
    st = p.stat()
    return {"path": str(p), "name": p.name, "size": st.st_size,
            "mtime": time.strftime("%F %T", time.localtime(st.st_mtime))}


def overview():
    out = []
    for name in Project.list_all():
        proj = Project(name)
        state = _read_json(proj.state_file) or {}
        latest = 0
        if proj.path.exists():
            latest = max((f.stat().st_mtime for f in proj.path.iterdir()
                          if f.is_file()), default=0)
        gen = _read_json(proj.path / "generate.json") or {}
        rv = _read_json(proj.path / "review.json") or {}
        out.append({
            "name": name, "created": state.get("created"), "shots": state.get("shots"),
            "title": (_read_json(proj.path / "script.json") or {}).get("title_cn"),
            "stages": {k: v.get("done") for k, v in state.get("stages", {}).items()},
            "review_pass": f"{rv.get('passed')}/{rv.get('total')}" if rv.get("total") else None,
            "videos": len(gen.get("videos") or {}),
            "updated": time.strftime("%F %T", time.localtime(latest)) if latest else None,
            "busy": (manager.active_of_project(name) or None) and
                    manager.active_of_project(name).dto(),
        })
    out.sort(key=lambda x: x.get("updated") or "", reverse=True)
    # 演员库/候选区统计(扫目录,轻量)
    actors_ready = actors_total = 0
    try:
        from sd import pool as sd_pool
        chars = sd_pool.scan()
        actors_ready, actors_total = len(chars), len(sd_pool.scan_all())
    except Exception:
        pass
    from sd.audition import CANDIDATES
    candidates = (len([d for d in CANDIDATES.iterdir() if d.is_dir()])
                  if CANDIDATES.exists() else 0)
    return {"projects": out,
            "jobs": [j.dto() for j in manager.list()[:15]],
            "actors": {"ready": actors_ready, "total": actors_total},
            "candidates": candidates}


def project_detail(name):
    proj = Project(name)
    if not proj.exists():
        return None
    state = proj.load_state()
    script = proj.load_stage("script") or {}
    sb = proj.load_stage("storyboard") or {}
    generate = proj.load_stage("generate") or {}
    review = proj.load_stage("review") or {}
    human = _read_json(proj.path / "review" / "human.json") or {}

    rows = {}
    if sb.get("jsonl") and Path(sb["jsonl"]).exists():
        try:
            rows = {r["case_id"]: r
                    for r in (json.loads(l) for l in open(sb["jsonl"])
                              if l.strip())}
        except Exception:
            rows = {}

    shots = script.get("shots") or []
    cases = []
    for i, sh in enumerate(shots):
        cid = f"{name}-{sh.get('id', 'q' + str(i + 1))}"
        row = rows.get(cid, {})
        rv = next((r for r in (review.get("results") or []) if r.get("case") == cid), None)
        takes = (state.get("takes") or {}).get(cid, [])
        frames_dir = proj.path / "review"
        cases.append({
            "case": cid,
            "shot": sh,
            "task": row.get("task"), "seed": row.get("seed"), "dd": row.get("dd"),
            "soundscape": row.get("soundscape"), "note": row.get("note"),
            "camera": (lint.camera_of(sh.get("shot_en", ""), row.get("dd", ""))
                       if sh.get("shot_en") and row.get("dd") else None),
            "video": (generate.get("videos") or {}).get(cid),
            "review": rv,
            "gen_scores": (state.get("gen_scores") or {}).get(cid),
            "takes": [{**t, "idx": i2} for i2, t in enumerate(takes)],
            "human": human.get(cid),
            "frames": [str(frames_dir / f"{cid}-f{k}.jpg") for k in range(3)
                       if (frames_dir / f"{cid}-f{k}.jpg").exists()],
            "sheet": str(frames_dir / f"{cid}-sheet.jpg")
                     if (frames_dir / f"{cid}-sheet.jpg").exists() else None,
        })
    # 分镜里可能存在剧本之外的 case(理论上不会,防御性补上)
    known = {c["case"] for c in cases}
    for cid, row in rows.items():
        if cid not in known:
            cases.append({"case": cid, "shot": None, "task": row.get("task"),
                          "seed": row.get("seed"), "dd": row.get("dd"),
                          "soundscape": row.get("soundscape"), "note": row.get("note"),
                          "camera": None,
                          "video": (generate.get("videos") or {}).get(cid),
                          "review": next((r for r in (review.get("results") or [])
                                          if r.get("case") == cid), None),
                          "gen_scores": (state.get("gen_scores") or {}).get(cid),
                          "takes": [], "human": None, "frames": [], "sheet": None})

    deliverables = []
    if proj.path.exists():
        for p in sorted(proj.path.iterdir()):
            if p.is_file() and p.suffix.lower() in DELIVER_EXTS:
                deliverables.append(_file_dto(p))
        for sub in ("master", "regen"):
            d = proj.path / sub
            if d.exists():
                for p in sorted(d.iterdir()):
                    if p.is_file() and p.suffix.lower() == ".mp4":
                        deliverables.append(_file_dto(p))

    gen_logs = []
    rt = Path(sd_config.SD_RUNTIME) / name
    if rt.exists():
        gen_logs = [_file_dto(p) | {"mtime": time.strftime(
                        "%F %T", time.localtime(p.stat().st_mtime))}
                    for p in sorted(rt.glob("gen-*.log"))]

    try:
        metrics_summary = Metrics(proj).summary()
    except Exception:
        metrics_summary = None

    brief = ""
    bf = proj.path / "brief.txt"
    if bf.exists():
        brief = bf.read_text()

    return {"name": name, "created": state.get("created"), "shots": state.get("shots"),
            "brief": brief,
            "stages": state.get("stages", {}),
            "cast": proj.load_stage("cast") or {},
            "materials": proj.load_stage("materials") or {},
            "script": script, "storyboard": sb, "generate": generate,
            "review": review, "human": human,
            "review_stale": ("review" not in (state.get("stages") or {})
                             and bool(review.get("results"))),
            "cases": cases, "deliverables": deliverables,
            "picks": _read_json(proj.path / "picks.json") or [],
            "gen_logs": gen_logs, "metrics_summary": metrics_summary,
            "project_dir": str(proj.path),
            "busy": (manager.active_of_project(name) or None) and
                    manager.active_of_project(name).dto()}


def pool_list():
    from sd import pool as sd_pool
    chars = sd_pool.scan_all()
    out = []
    for c in chars:
        refs = c.get("refs") or {}
        out.append({"name": c["name"],
                    "face_dna": c.get("face_dna"), "outfit_dna": c.get("outfit_dna"),
                    "seed": c.get("seed"), "dir": c.get("dir"),
                    "refs": {k: str(v) for k, v in refs.items() if v},
                    "complete": all(refs.get(k) for k in ("closeup", "front", "side"))})
    return out
