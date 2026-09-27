"""完整候选条 verdict 与发布闸门的单一事实源。"""
import json
from pathlib import Path


CORE_SCORES = ("identity", "action", "composition", "story_facts",
               "motion_naturalness", "performance")


class QualityGateError(RuntimeError):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


def human_reviews(proj):
    path = proj.path / "review" / "human.json"
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def review_is_pass(review):
    """只认完整 verdict；旧版只有三维 scores 的记录不再冒充已通过。"""
    if not review or review.get("verdict") != "pass":
        return False
    if review.get("text_artifacts") is not False:
        return False
    return all(isinstance(review.get(k), (int, float)) for k in CORE_SCORES)


def human_waiver_is_valid(human, video):
    """人工例外必须通过、写原因，并绑定这一个具体视频，防止重拍后沿用。"""
    return bool(human and human.get("approved") is True
                and (human.get("note") or "").strip()
                and human.get("video") == str(video))


def candidate_disposition(review, human, video):
    if review_is_pass(review):
        return "pass"
    if human_waiver_is_valid(human, video):
        return "waived"
    return "hold"


def score_total(review):
    if not review:
        return -1
    return sum(float(review.get(k, 0) or 0) for k in CORE_SCORES)


def assert_release_ready(pick_log, consistency=None):
    holds = [p for p in pick_log if p.get("disposition") not in ("pass", "waived")]
    consistency_bad = bool(consistency and consistency.get("checked")
                           and consistency.get("consistent") is False)
    if holds or consistency_bad:
        report = {
            "ready": False,
            "holds": [{"case": p.get("case"), "picked": p.get("picked"),
                       "verdict": (p.get("review") or {}).get("verdict"),
                       "reason": (p.get("review") or {}).get("advice_cn")
                                 or (p.get("review") or {}).get("advice")
                                 or "候选条未完整通过"} for p in holds],
            "consistency": consistency or {},
        }
        cases = ", ".join(x["case"] for x in report["holds"])
        why = f"未批准镜头: {cases}" if cases else "跨镜一致性未通过"
        raise QualityGateError(f"发布闸门阻断：{why}", report)
    return {"ready": True, "holds": [], "consistency": consistency or {}}

