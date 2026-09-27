"""项目级创作 skills 注册表。

这些 skills 属于 suncut 运行时，而不是某次 Codex 会话。各 agent 在构造提示词时
按角色加载，保证部署到 DGX 后仍拥有同一套叙事、镜头、表演、声音和质控能力。
"""
from functools import lru_cache

from . import config


SKILLS_DIR = config.FRAMEWORK_ROOT / "agent_skills"

AGENT_SKILLS = {
    "casting": ("casting-continuity",),
    "materials": ("production-design",),
    "screenwriter": ("short-drama-writing", "editing-rhythm"),
    "storyboard": ("cinematic-direction", "performance-direction", "story-continuity"),
    "director": ("performance-direction", "story-continuity"),
    "reviewer": ("generated-media-qa", "short-drama-analysis", "story-continuity"),
    "dubbing": ("dialogue-performance", "sound-design"),
    "producer": ("editing-rhythm", "sound-design", "release-gate"),
}


@lru_cache(maxsize=32)
def load_skill(name):
    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        raise RuntimeError(f"缺少项目级 skill: {path}")
    text = path.read_text().strip()
    if not text:
        raise RuntimeError(f"项目级 skill 为空: {path}")
    return text


def prompt_for(agent):
    """返回可直接注入 LLM prompt 的精简技能合同。"""
    names = AGENT_SKILLS.get(agent, ())
    return "\n\n".join(f"【项目级 Skill · {name}】\n{load_skill(name)}" for name in names)


def inventory():
    """供 doctor/UI 展示当前八 agent 的技能绑定。"""
    return {agent: list(names) for agent, names in AGENT_SKILLS.items()}

