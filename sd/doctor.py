"""sd doctor —— 运维预检: 开拍前把环境问题一次性暴露."""
import json
import shutil
import subprocess
from pathlib import Path

from . import config


def _gb(x):
    return f"{x / 1024 / 1024 / 1024:.0f}GB"


def run(quick_llm=False):
    ok, warn = [], []

    def check(name, cond, detail=""):
        (ok if cond else warn).append(f"{'✓' if cond else '✗'} {name} {detail}")

    # 基础工具
    for tool in ("ffmpeg", "ffprobe"):
        check(f"工具 {tool}", shutil.which(tool) is not None)

    # 磁盘(runtime 根 + 工程)
    for label, p in (("runtime", config.RUNTIME), ("工程", config.PROJECTS)):
        if p.exists():
            u = shutil.disk_usage(str(p))
            check(f"磁盘 {label} 剩余", u.free > 50 * 1024**3, _gb(u.free))

    # 内存(GB10 统一内存)
    with open("/proc/meminfo") as f:
        mem = {l.split(":")[0]: int(l.split()[1]) for l in f if ":" in l}
    avail = mem.get("MemAvailable", 0) * 1024
    check("可用内存", avail > 40 * 1024**3, _gb(avail))

    # GPU 常驻大进程(infer.py; ComfyUI 空闲不算,单独查队列)
    r = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True)
    busy = [l for l in r.stdout.splitlines() if "infer.py" in l]
    comfy_note = ""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8189/queue", timeout=3) as q:
            qd = json.load(q)
        n_run = len(qd.get("queue_running", [])) + len(qd.get("queue_pending", []))
        if n_run:
            busy.append(f"ComfyUI 队列 {n_run} 任务")
    except Exception:
        pass
    check("GPU 空闲(无推理任务)", not busy, "; ".join(busy[:2]) + comfy_note)

    # docker
    r = subprocess.run(["sg", "docker", "-c", "docker version --format {{.Server.Version}}"],
                       capture_output=True, text=True, timeout=30)
    check("docker(infer 依赖)", r.returncode == 0, r.stdout.strip()[:20])

    # Sol-H3 关键文件
    for name, p in (("infer.py", config.SOL_PKG / "infer.py"),
                    ("paths.json(t2va)", config.SOL_PKG / "paths.json"),
                    ("paths-ref2va.json", config.SOL_PKG / "paths-ref2va.json")):
        check(f"Sol-H3 {name}", p.exists(), str(p))

    # 演员库
    from . import pool
    chars = pool.scan_all()
    ready = pool.scan()
    check("演员库", len(ready) >= 1, f"{len(ready)}/{len(chars)} 可开拍"
          f"({' '.join(c['name'] for c in ready)})")

    # 智谱 key
    try:
        key = config.zhipu_key()
        check("智谱 key", len(key) > 20)
        if quick_llm:
            from . import llm
            llm.chat(config.LLM_FAST, "ping", "回复:pong", max_tokens=512)
            ok.append("✓ LLM 实调")
    except Exception as e:
        warn.append(f"✗ 智谱 key {e}")

    # ComfyUI 8189(母版档,可选)
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8189/system_stats", timeout=3):
            ok.append("✓ ComfyUI 8189 在线(母版档可用)")
    except Exception:
        warn.append("- ComfyUI 8189 离线(母版档将自动拉起,约1分钟)")

    print("\n".join(ok))
    if warn:
        print("\n".join(warn))
        print(f"\n结论: {len(ok)} 项通过, {len(warn)} 项需注意")
        return False
    print(f"\n结论: 全部 {len(ok)} 项通过,可开拍")
    return True
