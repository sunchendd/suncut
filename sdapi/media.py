"""media —— 白名单根内的文件服务,支持 HTTP Range(视频拖动进度条必需)."""
import mimetypes
import os
from pathlib import Path

from fastapi import HTTPException, Query
from fastapi.responses import StreamingResponse

from . import config as svc_config

CHUNK = 1 << 20

TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".png": "image/png", ".webp": "image/webp", ".srt": "text/plain; charset=utf-8",
         ".log": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
         ".md": "text/plain; charset=utf-8", ".json": "application/json",
         ".jsonl": "text/plain; charset=utf-8",
         ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
         ".m4a": "audio/mp4"}


def _resolve(path: str) -> Path:
    p = Path(path)
    try:
        rp = p.resolve()
    except Exception:
        raise HTTPException(400, "非法路径")
    for root in svc_config.MEDIA_ROOTS:
        try:
            rp.relative_to(root.resolve())
            break
        except ValueError:
            continue
    else:
        raise HTTPException(403, f"路径不在白名单根内: {path}")
    if not rp.is_file():
        raise HTTPException(404, "文件不存在")
    if rp.suffix.lower() not in TYPES:
        raise HTTPException(415, f"不支持的文件类型: {rp.suffix}")
    return rp


def serve(request, path: str = Query(...), download: bool = False):
    rp = _resolve(path)
    size = rp.stat().st_size
    ctype = TYPES.get(rp.suffix.lower()) or mimetypes.guess_type(str(rp))[0] or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{rp.name}"'

    rng = request.headers.get("range")
    if rng and rng.startswith("bytes="):
        try:
            start_s, end_s = rng[6:].split("-", 1)
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                raise HTTPException(416, "范围越界")
        except ValueError:
            raise HTTPException(416, "Range 头格式错误")

        def gen():
            with open(rp, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                    yield chunk
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(gen(), status_code=206, media_type=ctype,
                                 headers={**headers, "Content-Length": str(end - start + 1)})

    def gen_full():
        with open(rp, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                yield chunk
    return StreamingResponse(gen_full(), media_type=ctype,
                             headers={**headers, "Content-Length": str(size)})
