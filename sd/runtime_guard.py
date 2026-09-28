"""DGX Spark 推理启动前的资源保护。

GB10 使用统一内存：推理越界常先拖慢 SSH/桌面服务，而不一定出现传统独显的
“显存不足”。本模块只在启动新 infer 前阻断明显过载，不替代系统级监控。
"""
import subprocess

from . import config


def _meminfo(text):
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields and fields[0].isdigit():
            values[key] = int(fields[0]) * 1024
    return values


def snapshot(meminfo_text=None, loadavg_text=None, ps_text=None):
    if meminfo_text is None:
        try:
            meminfo_text = open("/proc/meminfo").read()
        except OSError:
            meminfo_text = ""
    if loadavg_text is None:
        try:
            loadavg_text = open("/proc/loadavg").read()
        except OSError:
            loadavg_text = ""
    if ps_text is None:
        try:
            ps_text = subprocess.run(["ps", "-eo", "args"], capture_output=True,
                                     text=True, timeout=5).stdout
        except Exception:
            ps_text = ""
    mem = _meminfo(meminfo_text)
    available = mem.get("MemAvailable", 0)
    total = mem.get("MemTotal", 0)
    swap_total = mem.get("SwapTotal", 0)
    swap_used = max(0, swap_total - mem.get("SwapFree", swap_total))
    try:
        load1 = float(loadavg_text.split()[0])
    except (ValueError, IndexError):
        load1 = None
    return {
        "available_bytes": available,
        "total_bytes": total,
        "swap_used_bytes": swap_used,
        "load1": load1,
        "infer_processes": sum("infer.py" in line for line in ps_text.splitlines()),
    }


def start_blocker(info, min_headroom_gb=None):
    """返回拒绝原因；None 表示可安全尝试启动（不是性能保证）。"""
    headroom = (config.MIN_INFER_HEADROOM_GB if min_headroom_gb is None
                else float(min_headroom_gb)) * 1024 ** 3
    if info["infer_processes"]:
        return "已有 Sol-H3 推理进程，拒绝并发启动以保护统一内存"
    if info["available_bytes"] and info["available_bytes"] < headroom:
        free = info["available_bytes"] / 1024 ** 3
        return f"可用统一内存仅 {free:.1f}GB，低于启动余量 {headroom / 1024 ** 3:.0f}GB"
    if info["swap_used_bytes"] > 8 * 1024 ** 3:
        used = info["swap_used_bytes"] / 1024 ** 3
        return f"交换空间已使用 {used:.1f}GB，先等待/清理后再启动推理"
    return None


def assert_can_start():
    reason = start_blocker(snapshot())
    if reason:
        raise RuntimeError("DGX Spark 资源保护闸：" + reason)
