"""分镜自动审稿器 —— 桌面工作流 §4.2 人工审稿清单的程序化部分.

对每镜 detailed_description 做确定性 lint;违规项反馈给 LLM 重写(带具体违规原因),
两轮仍不过则保留并记录 warning。DNA/音乐块不经过 LLM,不在 lint 范围内。
"""
import re

# (规则名, 正则, 说明) —— 命中即违规
RULES = [
    ("手部特写", re.compile(
        r"(close-?up (?:of|on)[^.]{0,30}\bhands?\b"
        r"|\bhands? (?:are )?(?:shown|visible|picking|reaching|counting)[^.]{0,30}close-?up"
        r"|\bfingers? (?:close-?up|detailed|delicately)"
        r"|(?:detailed|close) view of (?:her|the) hands?\b"
        r"|counting money|clenched fists? close)", re.I),
     "H3 手部是已知弱点,禁手部特写(用持物/袖口/桌面摆放代替)"),
    ("正面说话", re.compile(
        r"\b(she|he) (says|speaks|shouts|yells|whispers|mouths)\b(?![^.]{0,40}"
        r"(from behind|back to (?:the )?camera|in profile|over (?:her|his) shoulder))", re.I),
     "正面说话口型必穿帮,改旁白或背影/侧脸"),
    ("混乱快动作", re.compile(
        r"(rapid(?:ly)?|frantic(?:ally)?|furious(?:ly)?) (?:spin|dance|mov|flail|wave)", re.I),
     "快速混乱动作导致肢体崩坏,改 2-3 爆发点+慢过渡"),
    ("多镜头剪进单镜", re.compile(r"\b(cut to|cuts to|jump cut|montage of)\b", re.I),
     "单镜=单一连续运镜 no cuts,剪辑概念不进生成端"),
]

CAM_WORDS = {"push": "push-in", "push-in": "push-in", "pushes": "push-in",
             "pull": "pull-back", "pull-back": "pull-back", "pulls": "pull-back",
             "orbit": "orbit", "orbits": "orbit", "orbiting": "orbit",
             "track": "track", "tracks": "track", "tracking": "track",
             "static": "static", "locked": "static", "fixed camera": "static",
             "pan": "pan", "pans": "pan", "tilt": "tilt"}


# 动作节点过渡词: 一镜动作链过长时模型执行崩坏(实测 action 分低的主因)
_BEAT_MARKERS = re.compile(
    r"\b(then|before|after that|next|finally)\b|;\s*she\b|,\s*then\b", re.I)


def action_beats(dd):
    """估算动作节点数(过渡标记计数,含最低 1)."""
    return max(1, len(_BEAT_MARKERS.findall(dd)))


def lint_dd(dd):
    """返回违规列表 [(规则, 命中片段, 修法)]"""
    hits = []
    for name, pat, fix in RULES:
        m = pat.search(dd)
        if m:
            hits.append((name, m.group(0)[:60], fix))
    beats = action_beats(dd)
    if beats > 3:
        hits.append(("动作密度过高", f"{beats} 个动作节点",
                     "一镜最多 3 个动作节点(1 主爆发+1 次要+收势),多余动作砍掉或挪到邻镜"))
    return hits


def camera_of(shot_en, dd):
    text = (shot_en + " " + dd).lower()
    found = [v for k, v in CAM_WORDS.items() if k in text]
    return found[0] if found else "unknown"


def lint_batch(shots):
    """shots: [{id, shot_en, dd}]; 返回 (per_shot_hits, camera_list, variety_ok)"""
    per, cams = {}, []
    for s in shots:
        hits = lint_dd(s["dd"])
        if hits:
            per[s["id"]] = hits
        cams.append(camera_of(s.get("shot_en", ""), s["dd"]))
    variety_ok = len(shots) < 3 or len(set(cams)) >= 2
    return per, cams, variety_ok


def violations_feedback(hits):
    return ";".join(f"[{n}] 命中『{frag}』: {fix}" for n, frag, fix in hits)


def ensure_safety_phrases(dd):
    """程序化补齐压风格短语,不依赖 LLM 自觉."""
    add = []
    low = dd.lower()
    for phrase in ("no cuts", "no text"):
        if phrase not in low:
            add.append(phrase)
    if add:
        dd = dd.rstrip(". ") + ". " + ", ".join(add)
    return dd
