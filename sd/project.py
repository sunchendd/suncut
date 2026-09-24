"""项目工作区 —— 每部短剧一个目录,阶段产物 + state.json 断点续跑."""
import json
import time
from pathlib import Path

from . import config


class Project:
    def __init__(self, name):
        self.name = name
        self.path = config.PROJECTS / name
        self.state_file = self.path / "state.json"

    def create(self, brief, shots):
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "brief.txt").write_text(brief.strip() + "\n")
        st = {"name": self.name, "created": time.strftime("%F %T"),
              "shots": shots, "stages": {}}
        self._write_state(st)
        return self

    def exists(self):
        return self.state_file.exists()

    def load_state(self):
        return json.loads(self.state_file.read_text())

    def _write_state(self, st):
        self.state_file.write_text(json.dumps(st, ensure_ascii=False, indent=1))

    def save_stage(self, stage, data, meta=None):
        st = self.load_state()
        st["stages"][stage] = {"done": time.strftime("%F %T"), "meta": meta or {}}
        self._write_state(st)
        (self.path / f"{stage}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1))

    def load_stage(self, stage):
        f = self.path / f"{stage}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def stage_done(self, stage):
        return stage in self.load_state().get("stages", {})

    @staticmethod
    def list_all():
        if not config.PROJECTS.exists():
            return []
        return sorted(p.name for p in config.PROJECTS.iterdir()
                      if (p / "state.json").exists())
