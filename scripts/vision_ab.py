#!/usr/bin/env python3
"""vision_ab —— 审片模型 A/B: glm-4.5v vs glm-5.3-flash.

对已有项目的审片帧跑真实评审 prompt(与 reviewer.review_one 同款),
每案例每模型重复 N 次,以归档的双次均值分(regen_scores.json / review.json)
为参照,量化: 平均绝对偏差 / 方差(稳定性) / 时延。
用法: python3 scripts/vision_ab.py [项目名 ...]   (缺省 taideng jiuwu)
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sd import config, llm, reviewer  # noqa: E402
from sd.project import Project  # noqa: E402

MODELS = ["glm-4.5v", "glm-5.3-flash"]
REPEATS = 2


def vision_as(text, image_paths, model):
    """llm.vision 的模型可参数化版(其余行为逐字一致)."""
    content = [{"type": "text", "text": text}]
    for p in image_paths:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + llm._shrink_b64(p)}})
    body = {"model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 4000}
    d = llm._post(body, timeout=240)
    out = (d["choices"][0]["message"].get("content") or "").strip()
    if not out:
        raise llm.LLMError("vision 空回复")
    return out


def load_ref_scores(proj):
    """参照分: 优先 regen_scores.json(14步重生版逐镜终验),否则 review.json."""
    for f in ("review/regen_scores.json", "review.json"):
        p = proj.path / f
        if p.exists():
            d = json.loads(p.read_text())
            if isinstance(d, dict) and d.get("results"):
                return {r["case"]: {k: r.get(k) for k in ("identity", "action", "composition")}
                        for r in d["results"] if r.get("identity") is not None}
    return {}


def main(names):
    report = []
    for name in names:
        proj = Project(name)
        if not proj.exists():
            continue
        sb = proj.load_stage("storyboard")
        script = proj.load_stage("script")
        cast_stage = proj.load_stage("cast")
        cast_by_name = {r["char"]: r["profile"] for r in cast_stage["cast"]}
        ref_scores = load_ref_scores(proj)
        rows = [json.loads(l) for l in open(sb["jsonl"]) if l.strip()]
        # 只测有归档参照分且帧齐的案例
        cases = []
        for s in script["shots"]:
            case = f"{name}-{s['id']}"
            fr = [proj.path / "review" / f"{case}-f{k}.jpg" for k in range(3)]
            if ref_scores.get(case) and all(f.exists() for f in fr):
                cases.append((s, case, fr))
        print(f"== {name}: {len(cases)} 案例可测")
        for s, case, fr in cases:
            in_cast = [cast_by_name[n] for n in s.get("cast", [])][:2] or \
                      [cast_by_name[cast_stage["cast"][0]["char"]]]
            ref_imgs = [p for prof in in_cast
                        for p in (prof["refs"]["closeup"], prof["refs"]["front"])]
            refs_desc = (f"前{len(ref_imgs)}张图是角色参考图(每位角色两张:头部特写+全身正面,"
                         f"顺序对应镜中 Subject 编号)," if ref_imgs else "本镜是无人物空镜,")
            dd = next((r["dd"] for r in rows if r["case_id"] == case), "")
            text = reviewer.PROMPT_TMPL.format(
                refs_desc=refs_desc, w=config.VIDEO_W, h=config.VIDEO_H, dd=dd)
            for model in MODELS:
                runs, times = [], []
                for rep in range(REPEATS):
                    t0 = time.time()
                    try:
                        v = llm.extract_json(vision_as(text, ref_imgs + fr, model))
                        runs.append({k: v.get(k) for k in ("identity", "action", "composition")})
                    except Exception as e:
                        runs.append({"error": str(e)[:120]})
                    times.append(time.time() - t0)
                ref = ref_scores[case]
                ok_runs = [r for r in runs if "error" not in r]
                dev = [abs(r[k] - ref[k]) for r in ok_runs
                       for k in ("identity", "action", "composition") if k in r]
                spread = [max(r[k] for r in ok_runs) - min(r[k] for r in ok_runs)
                          for k in ("identity", "action", "composition")
                          if all(k in r for r in ok_runs)] if ok_runs else []
                report.append({
                    "case": case, "model": model,
                    "ref": ref,
                    "runs": runs,
                    "avg_dev": round(sum(dev) / len(dev), 2) if dev else None,
                    "spread": max(spread) if spread else None,
                    "avg_secs": round(sum(times) / len(times), 1),
                    "errors": len(runs) - len(ok_runs),
                })
                print(f"  {case} {model:14s} dev={report[-1]['avg_dev']} "
                      f"spread={report[-1]['spread']} {report[-1]['avg_secs']}s "
                      f"err={report[-1]['errors']}")
    out = Path(config.FRAMEWORK_ROOT) / "vision_ab_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    # 汇总
    for model in MODELS:
        rs = [r for r in report if r["model"] == model]
        devs = [r["avg_dev"] for r in rs if r["avg_dev"] is not None]
        spreads = [r["spread"] for r in rs if r["spread"] is not None]
        errs = sum(r["errors"] for r in rs)
        print(f"\n[{model}] 案例数={len(rs)} 平均偏差={sum(devs)/len(devs):.2f} "
              f"同案例极差(稳定性)={sum(spreads)/len(spreads):.2f} "
              f"平均时延={sum(r['avg_secs'] for r in rs)/len(rs):.1f}s 错误={errs}")
    print(f"\n明细已落盘 {out}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["taideng", "jiuwu"])
