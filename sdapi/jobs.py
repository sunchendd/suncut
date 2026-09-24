"""jobs —— 任务模型与调度:按项目串行 + 全局 GPU 锁 + print 捕获 + gen-*.log tail.

并发规则(对应 sd 代码的已知坑):
1. state.json 是无锁读-改-写 → 同一项目同时只允许一个任务(否则 409);
2. ComfyUI 与 infer 互斥占卡 → generate/retake/regen/master/buildrefs/turntable
   共用一把全局 GPU 锁,物理上不可能并行占卡;
3. producer.produce 会 raise SystemExit → 统一按 BaseException 捕获归类.
"""
import json
import threading
import time
import traceback
import uuid
from collections import deque
from pathlib import Path

from sd import config as sd_config
from . import config as svc_config
from .hub import bus, print_hub

TERMINAL = ("done", "failed", "cancelled")


class JobCancelled(Exception):
    pass


class Job:
    def __init__(self, jid, jtype, title, project=None, gpu=False, pausable=False):
        self.id = jid
        self.type = jtype            # cast/…/pipeline/pool-buildrefs/doctor…
        self.title = title
        self.project = project
        self.gpu = gpu
        self.pausable = pausable
        self.status = "queued"       # queued/running/awaiting/done/failed/cancelled
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None
        self.error = None
        self.result = None
        self.meta = {}               # 阶段/门信息等
        self.log = deque(maxlen=svc_config.LOG_CAP)
        self._buf = ""
        self._log_lock = threading.Lock()
        self._gate = threading.Event()
        self._cancelled = False

    # ---------- 日志 ----------
    def log_write(self, s):
        with self._log_lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._emit(line)

    def log_flush_tail(self):
        with self._log_lock:
            if self._buf.strip():
                self._emit(self._buf)
            self._buf = ""

    def _emit(self, line):
        self.log.append(line)
        bus.publish("log", id=self.id, lines=[line])

    def log_lines(self, tail=None):
        with self._log_lock:
            lines = list(self.log)
        return lines[-tail:] if tail else lines

    # ---------- 状态 ----------
    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        bus.publish("job", job=self.dto())

    def dto(self):
        return {"id": self.id, "type": self.type, "title": self.title,
                "project": self.project, "gpu": self.gpu, "status": self.status,
                "created_at": self.created_at,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "duration": (self.finished_at or time.time()) - (self.started_at or self.created_at),
                "error": self.error, "result": self.result, "meta": self.meta}

    # ---------- 审批门 / 取消(仅 pausable 任务在阶段间隙生效) ----------
    def await_gate(self, gate, note, meta=None):
        """流水线在此挂起等人工放行;cancel 会在门上醒过来并终止."""
        self._gate.clear()
        self._set(status="awaiting")
        self.meta = {"gate": gate, "note": note, **(meta or {})}
        self._set()
        while True:
            if self._gate.wait(timeout=2):
                if self._cancelled:
                    raise JobCancelled(f"已在门 {gate} 处取消")
                self._set(status="running")
                return
            if self._cancelled:
                raise JobCancelled(f"已在门 {gate} 处取消")

    def resume(self):
        self._gate.set()

    def request_cancel(self):
        self._cancelled = True
        if self.status == "awaiting":
            self._gate.set()          # 让门上的线程醒来抛 JobCancelled
            return True
        return False                  # running 中:分步流水线在下一个门处停


class GenLogTailer(threading.Thread):
    """跟踪 runtime 下 gen-*.log 的新增内容,把 infer 进度灌进任务日志."""

    def __init__(self, job):
        super().__init__(daemon=True, name=f"tail-{job.id[:8]}")
        self.job = job
        d = Path(sd_config.SD_RUNTIME) / job.project
        self.watch_dir = d if d.exists() else None
        self._offsets = {}
        self._stop = threading.Event()

    def run(self):
        if not self.watch_dir:
            return
        while not self._stop.is_set() and self.job.status in ("queued", "running", "awaiting"):
            try:
                self._poll_once()
            except Exception:
                pass
            self._stop.wait(svc_config.TAIL_POLL)
        # 收尾读一次,避免最后一段日志丢失
        try:
            self._poll_once()
        except Exception:
            pass

    def _poll_once(self):
        hits = []
        for f in sorted(self.watch_dir.glob("gen-*.log")):
            st = f.stat()
            if f not in self._offsets:
                # 任务开始前就存在的旧日志:从当前末尾开始(只追增量)
                self._offsets[f] = st.st_size if st.st_mtime < self.job.created_at else 0
            off = self._offsets[f]
            if st.st_size > off:
                with open(f, "rb") as fh:
                    fh.seek(off)
                    chunk = fh.read()
                    self._offsets[f] = fh.tell()
                text = chunk.decode("utf-8", "replace")
                for line in text.splitlines():
                    if line.strip():
                        hits.append(f"[infer] {line}")
        if hits:
            with self.job._log_lock:
                for h in hits:
                    self.job.log.append(h)
            bus.publish("log", id=self.job.id, lines=hits)

    def stop(self):
        self._stop.set()


class HistJob:
    """重启前已终态的历史任务(只读,从 jobs.jsonl 恢复;不支持 resume/cancel)."""

    def __init__(self, d):
        self.__dict__.update({k: v for k, v in d.items() if k != "log"})
        self._hist_log = d.get("log") or []

    def dto(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def log_lines(self, tail=None):
        return self._hist_log[-tail:] if tail else self._hist_log


class JobManager:
    def __init__(self):
        self.jobs = {}                       # id -> Job(进程内活跃)
        self._project_running = {}           # name -> job_id
        self._proj_lock = threading.Lock()
        self.gpu_lock = threading.RLock()    # 全局单卡锁
        self._order = []
        self._hist = {}                      # id -> HistJob(jobs.jsonl 恢复)
        self._hist_file = Path(sd_config.FRAMEWORK_ROOT) / "jobs.jsonl"
        self._load_history()

    def _load_history(self):
        if not self._hist_file.exists():
            return
        try:
            for line in self._hist_file.read_text().splitlines()[-300:]:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if isinstance(d, dict) and d.get("id"):
                    self._hist[d["id"]] = HistJob(d)
        except Exception:
            pass

    def _persist(self, job):
        """终态任务追加落盘(doit with log tail),重启后可查历史;超 2000 行轮转留尾 500."""
        try:
            d = job.dto()
            d["log"] = job.log_lines(60)
            if self._hist_file.exists():
                n = sum(1 for _ in open(self._hist_file))
                if n > 2000:
                    lines = self._hist_file.read_text().splitlines()[-500:]
                    self._hist_file.write_text("\n".join(lines) + "\n")
            with open(self._hist_file, "a") as f:
                f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
            self._hist[job.id] = HistJob(d)
        except Exception:
            pass

    # ---------- 查询 ----------
    def get(self, jid):
        return self.jobs.get(jid) or self._hist.get(jid)

    def list(self, project=None):
        js = [self.jobs[i] for i in self._order] + list(self._hist.values())
        if project:
            js = [j for j in js if j.project == project]
        return sorted(js, key=lambda j: j.created_at, reverse=True)

    def active_of_project(self, name):
        jid = self._project_running.get(name)
        return self.jobs.get(jid) if jid else None

    # ---------- 提交 ----------
    def submit(self, jtype, title, fn, project=None, gpu=False, pausable=False,
               tail_gen=False):
        with self._proj_lock:
            if project and project in self._project_running:
                busy = self.jobs[self._project_running[project]]
                raise BusyError(f"项目 {project} 正在跑「{busy.title}」({busy.status})")
            jid = uuid.uuid4().hex[:10]
            job = Job(jid, jtype, title, project=project, gpu=gpu, pausable=pausable)
            self.jobs[jid] = job
            self._order.append(jid)
            if project:
                self._project_running[project] = jid
        job._set(status="queued")
        t = threading.Thread(target=self._run, args=(job, fn, tail_gen),
                             daemon=True, name=f"job-{jid[:8]}")
        t.start()
        return job

    def _run(self, job, fn, tail_gen):
        tailer = GenLogTailer(job) if (tail_gen and job.project) else None
        job._set(status="running", started_at=time.time())
        print_hub.bind(job)
        if tailer:
            tailer.start()
        try:
            if job.gpu:
                if self.gpu_lock.acquire(blocking=False):
                    self.gpu_lock.release()
                else:
                    job._set(meta={**job.meta, "stage": "等待GPU",
                                   "stage_label": "等待 GPU(前序任务占用)"})
                with self.gpu_lock:
                    job.result = fn(job)
            else:
                job.result = fn(job)
            job.log_flush_tail()
            job._set(status="done", finished_at=time.time(),
                     meta={**job.meta, "stage": "完成"})
        except JobCancelled as e:
            job._set(status="cancelled", finished_at=time.time(), error=str(e))
        except SystemExit as e:                       # producer.produce 的正常退出码
            if e.code in (None, 0):
                job._set(status="done", finished_at=time.time())
            else:
                job._set(status="failed", finished_at=time.time(),
                         error=str(e.code))
        except BaseException as e:                    # noqa: BLE001 —— 服务层必须兜住一切
            job.log_lines()                           # 触发 dto 之外无副作用
            job._set(status="failed", finished_at=time.time(),
                     error=f"{type(e).__name__}: {e}",
                     meta={**job.meta, "trace": traceback.format_exc()[-2000:]})
        finally:
            print_hub.unbind()
            if tailer:
                tailer.stop()
            with self._proj_lock:
                if job.project and self._project_running.get(job.project) == job.id:
                    self._project_running.pop(job.project, None)
            if job.status in TERMINAL:
                self._persist(job)
            job._set()


class BusyError(RuntimeError):
    pass


manager = JobManager()
