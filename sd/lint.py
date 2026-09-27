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


# ---------------- 框架升级(2026-09-26): 双人交互降级 / 人称 / 说的必须拍到 / 相邻镜去重 ----------------
# q6 形变事故教训: 一镜双主体 + 递物/接触交互 = ref2va 融合事故高发组合
INTERACTION_RE = re.compile(
    r"\b(hands? (?:it |them )?over|gives?|passes?|offers?|receiv\w+|"
    r"takes? (?:it|them) (?:from|out of)|shakes? hands?|hugs?|embrac\w+|"
    r"kisses?|high-?fives?|exchanges?)\b"
    r"|\b(?:press(?:es)?|places?|puts?|slips?|slides?)\b[^.;]{0,60}"
    r"\b(?:palm|hand|hands)\b", re.I)

PROP_LEXICON = {   # 台词/旁白点名的关键道具 → action_en 里必须出现的英文词
    "工牌": ("badge", "lanyard", "id card"), "信封": ("envelope", "wax seal"),
    "信纸": ("letter", "paper"), "地契": ("deed", "paper"),
    "种子": ("seed", "pouch"), "篮子": ("basket",), "鸡蛋": ("egg", "basket"),
    "背包": ("backpack", "bag"), "公文包": ("briefcase", "bag"),
    "照片": ("photo", "frame", "picture"), "手套": ("glove",),
}

_SCALE_ORDER = ("extreme wide", "over-the-shoulder", "close-up", "closeup",
                "close up", "medium close", "wide", "medium")
_STATIC_VERBS = re.compile(r"^\W*(stands?|walks?|sits?|stares?|looks?|gazes?|"
                           r"waits?|breathes?)\b", re.I)


# 动作节点过渡词: 一镜动作链过长时模型执行崩坏(实测 action 分低的主因)
_BEAT_MARKERS = re.compile(
    r"\b(then|before|after that|next|finally)\b|;\s*she\b|,\s*then\b", re.I)


def action_beats(dd):
    """估算动作节点数(过渡标记计数,含最低 1)."""
    return max(1, len(_BEAT_MARKERS.findall(dd)))


def lint_dd(dd, two_subject=False):
    """返回违规列表 [(规则, 命中片段, 修法)];two_subject=双主体镜时加查交互高危."""
    hits = []
    for name, pat, fix in RULES:
        m = pat.search(dd)
        if m:
            hits.append((name, m.group(0)[:60], fix))
    if two_subject:
        m = INTERACTION_RE.search(dd)
        if m:
            hits.append(("双人交互高危", m.group(0)[:60],
                         "一镜双主体禁止递物/接触交互(形变事故源): 改成一主体完成动作,"
                         "另一主体静立/背对,物品放桌面或已在自己手里"))
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
    """shots: [{id, shot_en, dd, two?}]; 返回 (per_shot_hits, camera_list, variety_ok)"""
    per, cams = {}, []
    for s in shots:
        hits = lint_dd(s["dd"], two_subject=bool(s.get("two")))
        if hits:
            per[s["id"]] = hits
        cams.append(camera_of(s.get("shot_en", ""), s["dd"]))
    variety_ok = len(shots) < 3 or len(set(cams)) >= 2
    return per, cams, variety_ok


def lint_person(narrations):
    """旁白叙事人称一致性: 全剧『我』与『他/她』并存即违规(台词不算,角色说话本就用我)."""
    text = " ".join(x for x in narrations if x)
    first, third = "我" in text, re.search(r"[他她]", text)
    if first and third:
        return ["旁白人称混用(『我』与『他/她』并存)——全剧统一为一种叙事人称"]
    return []


def lint_show_dont_tell(shots):
    """『说的必须拍到』: 台词/旁白点名的关键道具必须出现在该镜 action_en/shot_en."""
    hits = []
    for s in shots:
        said = " ".join([s.get("narration_cn") or ""] +
                        [d.get("line", "") for d in s.get("dialogue_cn") or []])
        need = {cn: en for cn, en in PROP_LEXICON.items() if cn in said}
        if not need:
            continue
        act = (s.get("action_en", "") + " " + s.get("shot_en", "")).lower()
        miss = [cn for cn, ens in need.items() if not any(e in act for e in ens)]
        if miss:
            hits.append((s["id"], miss))
    return hits


def lint_adjacent(shots):
    """相邻镜去重: 景别相同 或 首动词同类静态 → 节奏平移感(幻灯片感的本源之一)."""
    def scale_of(s):
        low = (s.get("shot_en", "") + " " + s.get("action_en", "")).lower()
        for w in _SCALE_ORDER:
            if w in low:
                return w
        return "?"
    hits = []
    for a, b in zip(shots, shots[1:]):
        sa, sb = scale_of(a), scale_of(b)
        if sa != "?" and sa == sb:
            hits.append((b["id"], f"景别与上一镜同为 {sa}"))
        va = _STATIC_VERBS.search(a.get("action_en", "") or "")
        vb = _STATIC_VERBS.search(b.get("action_en", "") or "")
        if va and vb and va.group(1).lower()[:4] == vb.group(1).lower()[:4]:
            hits.append((b["id"], f"与上一镜同为『{vb.group(1)}』静态动作"))
    return hits


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
