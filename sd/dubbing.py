"""配音师 agent —— 角色音色档案 + 后期 ADR + 全片 VO 音轨 + 预览混音.

设计(与重拍解耦): 配音只产出「全片一条 VO 音轨 + 时间表」:
  audio/vo/segNNN-<音色>.mp3   逐段配音(按剧本时间轴绝对定位)
  audio/vo_full.wav            全片人声轨(loudnorm -13 LUFS)
  audio/preview.mp4            当前最佳条 × 侧链压制混音预览(审听位)
  dubbing.json                 音色分配 + 分段时间表
真正的成片合成在制片交付时按「当时选出的条」进行 —— 重拍换条不失效
(时间轴使用编剧的连续剪辑时长)。BGM 由制片在最终混音时统一铺设，
配音阶段只引用已选曲目作审听预览。
"""
import json
import shutil
import subprocess
from pathlib import Path

from . import av, config, creative_skills, llm, musiclib

VOICE_SYSTEM = ("你是配音导演。根据角色外观气质,从音色池里为每个角色选最贴合的一条,"
                "再为旁白选一条。只输出 JSON。\n\n"
                + creative_skills.prompt_for("dubbing"))
MAX_RATE_BOOST = 12


def _edge_tts_bin():
    if config.EDGE_TTS.exists():
        return str(config.EDGE_TTS)
    p = shutil.which("edge-tts")
    if p:
        return p
    raise RuntimeError("edge-tts 不可用: 请 ~/venvs/sdapi/bin/pip install edge-tts")


def _tts(text, voice, out_path, rate_pct=0):
    cmd = [_edge_tts_bin(), "--voice", voice, "--text", text,
           "--write-media", str(out_path)]
    if rate_pct:
        cmd += ["--rate", f"+{rate_pct}%"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 800:
        raise RuntimeError(f"TTS 失败({voice} rate+{rate_pct}%): "
                           f"{(r.stderr or r.stdout or '')[-200:]}")


def _segments(proj_name, script, narrator_voice, voices):
    """剧本 → VO 段时间表(与编剧 SRT 同一套剪辑表时间槽公式,声画同步)."""
    from .screenwriter import _durations
    segs = []
    t = 0.0
    for shot, S in zip(script["shots"], _durations(script["shots"])):
        t0 = t
        t = t0 + S
        events = []
        for d in shot.get("dialogue_cn") or []:
            events.append((d["line"], voices.get(d["who"], narrator_voice), d["who"]))
        if (shot.get("narration_cn") or "").strip():
            events.append((shot["narration_cn"].strip(), narrator_voice, "旁白"))
        m = len(events)
        lead = max(0.12, min(0.6, float(shot.get("voice_lead_s", 0.25))))
        tail = max(0.12, min(0.5, float(shot.get("voice_tail_s", 0.20))))
        for j, (text, voice, who) in enumerate(events):
            slot = (S - lead - tail) / m
            segs.append({"case": f"{proj_name}-{shot['id']}", "shot": shot["id"],
                         "who": who, "text": text, "voice": voice,
                         "t_start": round(t0 + lead + j * slot, 3),
                         "t_end": round(t0 + lead + (j + 1) * slot - 0.10, 3)})
    return segs


def _voice_overrides(proj):
    """允许项目逐角色覆写；自定义/克隆音色必须带书面授权引用。"""
    path = proj.path / "audio" / config.VOICE_PROFILES_FILE
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _assign_voices(proj, cast, narrator_default):
    """LLM 初选、项目覆盖、同剧角色去重，形成可审计的声音档案。"""
    overrides = _voice_overrides(proj)
    pool = "\n".join(f"- {k}" for k in config.TTS_VOICES)
    roles = "\n".join(f"- {r['story_role']}: {r['profile']['face_dna'][:100]}"
                      for r in cast["cast"])
    try:
        d = llm.chat_json(config.LLM_FAST, VOICE_SYSTEM,
                          f"【音色池】\n{pool}\n\n【角色】\n{roles}\n\n"
                          '只输出 JSON: {"roles": {"主角": "池内音色名"}, '
                          '"narrator": "池内音色名"}')
        voices = {k: v for k, v in d.get("roles", {}).items() if v in config.TTS_VOICES}
        narr = d.get("narrator") if d.get("narrator") in config.TTS_VOICES else narrator_default
    except Exception:
        voices, narr = {}, narrator_default
    used = set()
    available = list(config.TTS_VOICES)
    profiles = {}
    for r in cast["cast"]:
        role = r["story_role"]
        override = (overrides.get("roles") or {}).get(role, {})
        voice = override.get("voice") if isinstance(override, dict) else None
        if voice not in config.TTS_VOICES:
            voice = voices.get(role)
        if voice in used:                           # 同剧角色默认不共用声线
            voice = next((v for v in available if v not in used and v != narr), voice)
        voice = voice if voice in config.TTS_VOICES else next(
            (v for v in available if v not in used), narr)
        source = override.get("source", "provider_generic_tts") if isinstance(override, dict) else "provider_generic_tts"
        consent = override.get("consent_reference", "") if isinstance(override, dict) else ""
        if source in ("custom_voice", "voice_clone") and not consent.strip():
            raise RuntimeError(f"{role} 使用自定义/克隆音色必须提供 consent_reference")
        voices[role] = voice
        used.add(voice)
        profiles[role] = {"voice": voice, "voice_id": config.TTS_VOICES[voice],
                          "source": source, "consent_reference": consent,
                          "performance": (override.get("performance", "") if isinstance(override, dict) else "")}
        r["voice_profile"] = profiles[role]
    narrator_override = overrides.get("narrator") or {}
    narrator = narrator_override.get("voice", narr) if isinstance(narrator_override, dict) else narr
    if narrator not in config.TTS_VOICES:
        narrator = narr
    narrator_profile = {"voice": narrator, "voice_id": config.TTS_VOICES[narrator],
                        "source": (narrator_override.get("source", "provider_generic_tts") if isinstance(narrator_override, dict) else "provider_generic_tts"),
                        "consent_reference": (narrator_override.get("consent_reference", "") if isinstance(narrator_override, dict) else "")}
    if narrator_profile["source"] in ("custom_voice", "voice_clone") and not narrator_profile["consent_reference"].strip():
        raise RuntimeError("旁白使用自定义/克隆音色必须提供 consent_reference")
    return voices, narrator, {"roles": profiles, "narrator": narrator_profile}


def _build_vo_track(proj, segs, vo_dir, total_s):
    """逐段 TTS；只允许轻微提速，放不下就阻断并要求改词/改剪辑。"""
    for k, seg in enumerate(segs, 1):
        seg["file"] = str(vo_dir / f"seg{k:03d}.mp3")
        window = seg["t_end"] - seg["t_start"]
        _tts(seg["text"], config.TTS_VOICES[seg["voice"]], Path(seg["file"]))
        dur = av.probe_duration(seg["file"])
        rate_boost = 0
        if dur > window + 0.15:
            rate = min(MAX_RATE_BOOST, max(1, int((dur / max(window, 0.5) - 1) * 100) + 3))
            _tts(seg["text"], config.TTS_VOICES[seg["voice"]], Path(seg["file"]), rate)
            dur = av.probe_duration(seg["file"])
            rate_boost = rate
        if dur > window + 0.20:
            raise RuntimeError(
                f"自然语速放不进时槽: {seg['case']} {seg['who']}『{seg['text']}』"
                f" 需 {dur:.2f}s / 可用 {window:.2f}s；请缩短台词或延长 edit_duration_s，"
                f"系统拒绝超过 +{MAX_RATE_BOOST}% 的机械加速")
        seg["dur"] = round(dur, 3)
        seg["rate_boost"] = rate_boost
        print(f"[配音] seg{k:03d} {seg['who']}({seg['voice']}) {seg['dur']}s "
              f"@{seg['t_start']}s: {seg['text'][:20]}")
    # 静音基底 + 全段 adelay 对位混合 → loudnorm 到 -13 LUFS
    n = len(segs)
    inputs = ["-f", "lavfi", "-t", f"{total_s:.3f}",
              "-i", "anullsrc=r=48000:cl=stereo"]
    parts = []
    for k, seg in enumerate(segs, 1):
        inputs += ["-i", seg["file"]]
        ms = int(seg["t_start"] * 1000)
        parts.append(f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:"
                     f"channel_layouts=stereo,adelay={ms}|{ms}[d{k}]")
    parts.append("".join(f"[d{i}]" for i in range(1, n + 1)) +
                 f"amix=inputs={n}:duration=longest:normalize=0,"
                 "loudnorm=I=-13:TP=-1.2:LRA=9[aout]")
    out = proj.path / "audio" / "vo_full.wav"
    av.run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
            "-filter_complex", ";".join(parts), "-map", "[aout]", str(out)])
    return str(out)


def run(proj, force=False):
    if proj.stage_done("dub") and not force:
        return proj.load_stage("dub")
    script = proj.load_stage("script")
    if not script:
        raise RuntimeError("先跑编剧,有台词/旁白才能配音")
    cast = proj.load_stage("cast")
    audio_dir = proj.path / "audio"
    vo_dir = audio_dir / "vo"
    vo_dir.mkdir(parents=True, exist_ok=True)
    for f in vo_dir.glob("seg*.mp3"):             # force 重配: 清旧段
        f.unlink()

    voices, narrator, voice_profiles = _assign_voices(proj, cast, config.NARRATOR_DEFAULT)
    # 选角档案与本项目可编辑的声音档案保持一致，重拍不会丢角色声音。
    proj.save_stage("cast", cast, meta={"cast": [r["char"] for r in cast["cast"]]})
    profile_path = audio_dir / config.VOICE_PROFILES_FILE
    if not profile_path.exists():
        profile_path.write_text(json.dumps(voice_profiles, ensure_ascii=False, indent=1))
    print(f"[配音] 音色分配: 角色 {voices} | 旁白 {narrator}")
    segs = _segments(proj.name, script, narrator, voices)
    data = {"voices": voices, "narrator": narrator, "voice_profiles": voice_profiles,
            "voice_ids": {k: config.TTS_VOICES[k] for k in
                          set(list(voices.values()) + [narrator])}}
    if not segs:
        data.update({"segments": [], "vo_full": None,
                     "note": "剧本无台词无旁白,空音轨"})
        proj.save_stage("dub", data, meta={"segments": 0})
        return data
    from .screenwriter import _durations
    total_s = sum(_durations(script["shots"]))    # 剪辑表实际总长(short 镜已裁)
    vo_full = _build_vo_track(proj, segs, vo_dir, total_s)
    data["segments"] = segs
    data["vo_full"] = vo_full
    data["bgm_preview"] = musiclib.selected_track(proj)

    # 预览混音: 当前最佳条拼一下 → 侧链压制混 VO(审听位,交付时会重新按选条做)
    try:
        seg_files, pick_log = av.pick_best(proj, require_approved=False)
        base = audio_dir / "preview-base.mp4"
        from .producer import _edit_ranges
        av.smart_concat(seg_files, _edit_ranges(proj, pick_log), base)
        bgm = (data["bgm_preview"] or {}).get("file")
        av.mix_vo(base, vo_full, audio_dir / "preview.mp4", bgm=bgm)
        base.unlink(missing_ok=True)
        data["preview"] = str(audio_dir / "preview.mp4")
        print(f"[配音] 预览混音完成: {data['preview']}")
    except Exception as e:                        # 无生成产物时预览跳过,不阻塞
        data["preview"] = None
        data["preview_error"] = str(e)[:200]
        print(f"[配音] 预览混音跳过: {e}")
    proj.save_stage("dub", data, meta={"segments": len(segs), "narrator": narrator})
    return data
