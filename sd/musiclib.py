"""制片 BGM 曲库：授权台账、项目选择和可复现的素材落位。"""
import json
import shutil
from pathlib import Path

from . import config


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
    path = config.MUSIC_LIBRARY / track.get("file", "")
    if not path.is_file():
        raise MusicLibraryError(f"曲目文件不存在: {path}")
    data = {"track_id": track_id, "source": source, "file": str(path),
            "title": track.get("title", track_id), "rights": track["rights"],
            "mood_tags": track.get("mood_tags", []), "bpm": track.get("bpm")}
    selection_path(proj).parent.mkdir(parents=True, exist_ok=True)
    selection_path(proj).write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data


def selected_track(proj):
    """项目上传优先；否则只采用已批准且文件存在的曲库选择。"""
    picked = selection(proj)
    if picked and picked.get("source") == "library" and picked.get("rights", {}).get("approved"):
        path = Path(picked.get("materialized_file") or picked.get("file", ""))
        if path.is_file():
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
