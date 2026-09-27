"""制片 BGM 曲库：授权台账、项目选择和可复现的素材落位。"""
import json
import hashlib
import shutil
from pathlib import Path

from . import config, llm


class MusicLibraryError(RuntimeError):
    pass


def catalog():
    """读取曲库目录；无曲库时返回空，而不是臆造一条无授权音乐。"""
    try:
        raw = json.loads(config.MUSIC_CATALOG.read_text())
        tracks = raw.get("tracks", []) if isinstance(raw, dict) else []
    except FileNotFoundError:
        tracks = []
    except json.JSONDecodeError as e:
        raise MusicLibraryError(f"曲库 catalog.json 不是有效 JSON: {e}") from e
    return [t for t in tracks if isinstance(t, dict) and t.get("id")]


def track_path(track):
    return config.MUSIC_LIBRARY / track.get("file", "")


def is_ready(track):
    """曲目需完整落盘；登记摘要的曲目还要防止截断或被替换。"""
    path = track_path(track)
    minimum_bytes = max(1024, int(track.get("minimum_bytes", 0)))
    if not path.is_file() or path.stat().st_size < minimum_bytes:
        return False
    expected = track.get("sha256")
    if not expected:
        return True
    return hashlib.sha256(path.read_bytes()).hexdigest().lower() == str(expected).lower()


def selection_path(proj):
    return proj.path / "audio" / config.MUSIC_SELECTION_FILE


def selection(proj):
    try:
        return json.loads(selection_path(proj).read_text())
    except Exception:
        return None


def write_selection(proj, track_id, source="library"):
    track = next((t for t in catalog() if t["id"] == track_id), None)
    if not track:
        raise MusicLibraryError(f"曲库中没有曲目: {track_id}")
    if not track.get("rights", {}).get("approved"):
        raise MusicLibraryError(f"曲目未标记为授权可用: {track_id}")
    path = track_path(track)
    if not is_ready(track):
        raise MusicLibraryError(f"曲目不存在、尚未下载完整或校验失败: {path}")
    data = {"track_id": track_id, "source": source, "file": str(path),
            "title": track.get("title", track_id), "rights": track["rights"],
            "mood_tags": track.get("mood_tags", []), "bpm": track.get("bpm")}
    selection_path(proj).parent.mkdir(parents=True, exist_ok=True)
    selection_path(proj).write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data


def choose_for_project(proj):
    """配乐 agent 只在经过授权的本地目录中选曲，不能搜索或臆造外部音乐。"""
    existing = selected_track(proj)
    if existing:
        return existing
    tracks = catalog()
    approved = [t for t in tracks if t.get("rights", {}).get("approved") and is_ready(t)]
    if not approved:
        raise MusicLibraryError("曲库没有可用的已授权曲目")
    brief = (proj.path / "brief.txt").read_text().strip()
    try:
        script = proj.load_stage("script") or {}
        palette = [{"id": t["id"], "title": t.get("title", t["id"]),
                    "mood_tags": t.get("mood_tags", []), "bpm": t.get("bpm"),
                    "instrumental": t.get("instrumental", True)} for t in approved]
        out = llm.chat_json(config.LLM_FAST,
            "你是制片配乐 agent。只从给定、已授权的曲目中选一首全片主 BGM。"
            "优先纯音乐，按叙事弧线、旁白可懂度和节奏选择；只输出 JSON。",
            f"故事：{brief}\n剧本：{script.get('logline','')}\n可选曲目：{json.dumps(palette, ensure_ascii=False)}\n"
            '输出 {"track_id":"...","reason":"..."}')
        track_id = out.get("track_id")
        reason = out.get("reason", "配乐 agent 自动选择")
    except Exception:
        track_id, reason = approved[0]["id"], "配乐 agent 回退至曲库首个已授权曲目"
    if track_id not in {t["id"] for t in approved}:
        track_id, reason = approved[0]["id"], "配乐 agent 输出无效，回退至首个已授权曲目"
    data = write_selection(proj, track_id, source="library")
    data["selection_reason"] = reason
    selection_path(proj).write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data


def selected_track(proj):
    """项目上传优先；否则只采用已批准且文件存在的曲库选择。"""
    picked = selection(proj)
    if picked and picked.get("source") == "library" and picked.get("rights", {}).get("approved"):
        path = Path(picked.get("materialized_file") or picked.get("file", ""))
        track = next((t for t in catalog() if t["id"] == picked.get("track_id")), None)
        if path.is_file() and (picked.get("materialized_file") or (track and is_ready(track))):
            return {**picked, "file": str(path)}
    direct = _project_bgm(proj)
    if direct:
        return {"source": "project_upload", "file": str(direct), "rights": {"approved": False}}
    return None


def materialize_selected_bgm(proj):
    """把选中的曲库素材复制到项目 audio/bgm.*，便于交付包自包含。"""
    picked = selected_track(proj)
    if not picked or picked["source"] != "library":
        return picked
    src = Path(picked["file"])
    dst = proj.path / "audio" / f"bgm{src.suffix.lower()}"
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dst)
    picked = {**picked, "materialized_file": str(dst)}
    selection_path(proj).write_text(json.dumps(picked, ensure_ascii=False, indent=1))
    return picked


def _project_bgm(proj):
    for ext in (".mp3", ".wav", ".flac", ".m4a"):
        path = proj.path / "audio" / f"bgm{ext}"
        if path.is_file():
            return path
    return None
