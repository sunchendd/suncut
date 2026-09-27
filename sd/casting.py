"""招聘 agent —— 从演员库(AI角色工坊)为故事选角,坚持"角色最少够用"原则."""
import json

from . import config, creative_skills, llm, pool, qwenimage

SYSTEM = ("你是短剧选角导演。铁律:角色越少越好——60秒内单主角最佳,最多加一位对手;"
          "群演一律不招(用空镜/画外音代替);单镜头最多 2 人同框。只输出 JSON。")


def run(proj, force=False):
    if proj.stage_done("cast") and not force:
        return proj.load_stage("cast")
    brief = (proj.path / "brief.txt").read_text().strip()
    chars = pool.scan()
    if not chars:
        raise RuntimeError(f"演员库为空: {config.WORKSHOP}")
    user = f"""【故事梗概】
{brief}

【演员库(名字 | 外观DNA摘要 | 已有参考图)】
{pool.brief(chars)}

为这个故事选角。硬性规则:
1. 出镜角色最多 2 个(能 1 个就 1 个);功能性路人一律不选
2. 只能从演员库里按名字选,说明适配理由
3. wardrobe_note 指明用默认穿搭还是衣柜某套(如"默认穿搭")

只输出 JSON:
{{"cast": [{{"story_role": "主角", "char": "角色B_浅粉少女", "reason": "一句话", "wardrobe_note": "默认穿搭"}}],
 "extras_plan": "不需要群演的原因/空镜替代方案"}}"""
    data = llm.chat_json(config.LLM_TEXT,
                         SYSTEM + "\n\n" + creative_skills.prompt_for("casting"), user)
    return _finalize(proj, data, chars)


def run_manual(proj, cast):
    """手动选角(工作台): cast = [{story_role, char, reason?, wardrobe_note?}] ×1-2.

    允许选资料不全的演员(自动补三视图);数据形状与 LLM 选角完全一致,
    后续物料/编剧/分镜零改动。
    """
    if not cast:
        raise ValueError("手动选角至少 1 人")
    chars = pool.scan_all()          # 手动模式放开 complete 限制,缺图自动补
    if not chars:
        raise RuntimeError(f"演员库为空: {config.WORKSHOP}")
    data = {"cast": [], "extras_plan": "人工选角,无群演(空镜/画外音代替)"}
    for c in cast[:2]:
        if not (c.get("char") or "").strip():
            raise ValueError("char 不能为空")
        data["cast"].append({
            "story_role": (c.get("story_role") or "").strip() or "主角",
            "char": c["char"].strip(),
            "reason": (c.get("reason") or "").strip() or "人工指定",
            "wardrobe_note": (c.get("wardrobe_note") or "").strip() or "默认穿搭"})
    return _finalize(proj, data, chars)


def _finalize(proj, data, chars):
    names = []
    for role in data.get("cast", []):
        c = pool.find(chars, role["char"])   # 库里没有 → KeyError,上游显式报错
        if not all(k in c["refs"] for k in ("closeup", "front", "side")):
            c["refs"] = qwenimage.buildrefs(c)   # 招聘补图: Qwen特写 + 三视图裁切
        role["profile"] = {k: c[k] for k in ("name", "face_dna", "outfit_dna", "seed", "refs")}
        names.append(role["char"])
    if not 1 <= len(names) <= 2:
        raise ValueError(f"选角数量违规(1-2 个): {names}")
    if len(names) != len(set(names)):
        raise ValueError(f"选角重复: {names}")
    proj.save_stage("cast", data, meta={"cast": names})
    return data
