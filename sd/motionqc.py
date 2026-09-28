"""逐镜客观运动质检：用帧差为审片 agent 补上时间轴证据。"""
import re
import statistics
import subprocess

W, H = 168, 96


def _frames(path):
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={W}:{H}",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, timeout=120)
    count = len(result.stdout) // (W * H)
    return [result.stdout[i * W * H:(i + 1) * W * H] for i in range(count)]


def _mean_diff(a, b, box=None):
    if not box:
        return sum(abs(x - y) for x, y in zip(a, b)) / (W * H)
    x0, y0, x1, y1 = box
    total = count = 0
    for y in range(y0, y1):
        offset = y * W
        for x in range(x0, x1):
            total += abs(a[offset + x] - b[offset + x])
            count += 1
    return total / count


def analyze(path):
    """返回可复核的运动指标；解码问题不阻塞人工/视觉审片。"""
    try:
        frames = _frames(path)
    except Exception:
        return None
    if len(frames) < 12:
        return None
    diffs = [_mean_diff(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    center = (W // 3, H // 4, 2 * W // 3, 3 * H // 4)
    edge = (0, 0, W // 6, H)
    center_diffs = [_mean_diff(frames[i], frames[i + 1], center) for i in range(len(frames) - 1)]
    edge_diffs = [_mean_diff(frames[i], frames[i + 1], edge) for i in range(len(frames) - 1)]
    mean = statistics.mean(diffs)
    edge_mean = statistics.mean(edge_diffs)
    return {
        "mean_diff": round(mean, 2),
        "motion_cv": round(statistics.pstdev(diffs) / mean, 3) if mean > .01 else 0.0,
        "center_edge": round(statistics.mean(center_diffs) / edge_mean, 2) if edge_mean > .01 else 0.0,
        "near_static_pct": round(100 * sum(d < 1.5 for d in diffs) / len(diffs), 1),
        "frames": len(frames),
    }


_LOCOMOTION = ("walk", "stride", "cross", "march", "jog", "run", "stroll",
               "steps forward", "moves across", "approaches", "advances")
_STATIC_REVEAL = re.compile(r"\b(?:static|locked-?off|still|rests?)\b", re.I)
_PROP_REVEAL = re.compile(r"\b(?:key|envelope|letter|photo|ring|coin)\b", re.I)
_DESTINATION = re.compile(r"\b(?:from|toward|towards|along|across|past|into|to the)\b", re.I)


def allows_low_motion(intent=""):
    """静态道具揭示及有空间终点的跟拍，交给视觉审片而不被帧差直接拒绝。"""
    low = intent.lower()
    return (bool(_STATIC_REVEAL.search(intent) and _PROP_REVEAL.search(intent)) or
            (any(word in low for word in _LOCOMOTION) and bool(_DESTINATION.search(intent))))


def hard_failure(metrics, intent=""):
    return bool(metrics and not allows_low_motion(intent) and
                (metrics["mean_diff"] < 2.5 or metrics["near_static_pct"] > 60))


def flags(metrics, intent=""):
    if not metrics:
        return []
    flags = []
    if metrics["mean_diff"] < 2.5:
        flags.append(f"近乎静止(平均帧差{metrics['mean_diff']})，缺少可见运动")
    if metrics["motion_cv"] < .12 and metrics["mean_diff"] >= 2.5:
        flags.append(f"匀速无起伏(变异系数{metrics['motion_cv']}<0.12)，机械感风险高")
    low = intent.lower()
    if (any(word in low for word in _LOCOMOTION) and .8 <= metrics["center_edge"] <= 1.6
            and metrics["mean_diff"] >= 2.5):
        flags.append("位移存疑：行走镜需要明确空间终点和背景视差")
    if metrics["near_static_pct"] > 40:
        flags.append(f"大段死帧({metrics['near_static_pct']}%)")
    return flags
