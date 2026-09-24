"""物料 agent —— 场景 DNA / 全剧统一音乐块 / 道具清单(供分镜逐字复用的英文封闭块)."""
import json

from . import config, llm

SYSTEM = ("你是短剧美术指导。产出的是『逐字块』: 下游分镜会原样粘贴、绝不改写,"
          "所以每块必须自成一体、封闭、具体(可枚举的物件优先于抽象形容词)。只输出 JSON。")


def run(proj, force=False):
    if proj.stage_done("materials") and not force:
        return proj.load_stage("materials")
    brief = (proj.path / "brief.txt").read_text().strip()
    cast = proj.load_stage("cast")
    cast_lines = "\n".join(
        f"- {r['story_role']}: {r['char']} | {r['profile']['face_dna'][:120]}... | {r.get('wardrobe_note', '')}"
        for r in cast["cast"])
    user = f"""【故事梗概】
{brief}

【已定演员】
{cast_lines}

为整部短剧准备物料。要求:
1. scenes: {max(2, min(4, proj.load_state()['shots']))} 个场景,必须有变化;每个场景一句**封闭英文场景DNA**(地点+显式点光源+氛围,如灯笼/霓虹灯箱/橱窗灯/路灯/月光/火光),点光源是硬要求
2. music_en: 全剧统一音乐块(英文): 风格 + {config.DEFAULT_BPM} BPM 固定,写明鼓点落在每一拍;全剧逐字复用只许改乐器点缀
3. props: 每场景 1-2 个道具,能反复出现的视觉记忆点优先;写中文名+一句英文描述
4. b_roll: 1-2 个空镜DNA(纯场景无人物,强化点光源氛围,供开场/转场),英文一句

只输出 JSON:
{{"scenes": [{{"id": "S1", "dna_en": "a small convenience store interior at night, ...",
              "light_cn": "冷白荧光灯+门口暖霓虹", "props": ["雨伞-透明伞..."]}}],
 "b_roll": [{{"id": "B1", "dna_en": "empty rain-soaked street at night, one warm streetlamp ..."}}],
 "music_en": "lo-fi city pop beat at {config.DEFAULT_BPM} BPM, soft kick drum on every beat, ...",
 "style_note_en": "photorealistic cinematic still, real scene"}}"""
    data = llm.chat_json(config.LLM_TEXT, SYSTEM, user)
    dna = " ".join(s["dna_en"] for s in data["scenes"]).lower()
    for kw in ("light", "neon", "lantern", "lamp", "glow", "moon", "fluorescent"):
        if kw in dna:
            break
    else:
        raise ValueError("场景 DNA 缺点光源关键词,重跑 materials")
    proj.save_stage("materials", data, meta={"scenes": [s["id"] for s in data["scenes"]]})
    return data
