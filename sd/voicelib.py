"""配音演员资产库：把“角色”与“可授权的声音资产”分开管理。"""
import json
from pathlib import Path

from . import config

ROOT = config.FRAMEWORK_ROOT / "voice_library"
CATALOG = ROOT / "catalog.json"


def voices():
    try:
        data = json.loads(CATALOG.read_text())
    except FileNotFoundError:
        return []
    return [v for v in data.get("voices", [])
            if v.get("id") and v.get("rights", {}).get("approved")]


def by_id(voice_id):
    return next((v for v in voices() if v["id"] == voice_id), None)


def edge_voices():
    return {v["id"]: v for v in voices() if v.get("engine") == "edge_tts"}


def validate_selection(voice_id, consent_reference=""):
    v = by_id(voice_id)
    if not v:
        raise ValueError(f"音色不可用或未授权: {voice_id}")
    if v.get("engine") == "cosyvoice" and not consent_reference.strip():
        raise ValueError("CosyVoice 真人/克隆音色必须提供 consent_reference")
    return v
