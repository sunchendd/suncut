"""指标采集 —— 每阶段耗时/审片分/重拍数,优化循环的度量底座."""
import json
import time
from pathlib import Path


class Metrics:
    def __init__(self, proj):
        self.proj = proj
        self.file = proj.path / "metrics.json"
        self.data = json.loads(self.file.read_text()) if self.file.exists() else {"stages": []}

    def mark(self, stage, seconds, meta=None):
        self.data["stages"].append({"stage": stage, "s": round(seconds, 1),
                                    "at": time.strftime("%F %T"), "meta": meta or {}})
        self.file.write_text(json.dumps(self.data, ensure_ascii=False, indent=1))

    def summary(self):
        agg = {}
        for s in self.data["stages"]:
            agg.setdefault(s["stage"], []).append(s)
        lines = []
        total = 0.0
        for stage, items in agg.items():
            secs = sum(i["s"] for i in items)
            total += secs
            extra = ""
            if stage == "review":
                scores = [i["meta"].get("passed") for i in items if i["meta"].get("passed")]
                if scores:
                    extra = f" | 过片率 {' -> '.join(str(x) for x in scores)}"
            if stage == "generate":
                shots = sum(i["meta"].get("shots", 0) for i in items)
                extra = f" | {secs / max(shots, 1):.0f}s/镜" if shots else ""
            lines.append(f"{stage:12s} x{len(items)}  {secs:7.1f}s{extra}")
        lines.append(f"{'合计':12s}      {total:7.1f}s")
        return "\n".join(lines)


class stopwatch:
    """with stopwatch(proj,'generate',shots=4): ..."""

    def __init__(self, proj, stage, **meta):
        self.m, self.stage, self.meta = Metrics(proj), stage, meta

    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *exc):
        self.m.mark(self.stage, time.time() - self.t0, self.meta)
        return False
