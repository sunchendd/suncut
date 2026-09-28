"""server —— FastAPI 应用:REST + WebSocket + 静态前端 + 媒体网关.

启动: ~/venvs/sdapi/bin/python -m uvicorn sdapi.server:app --port 8620
      (必须从 shortdrama/ 目录或经 scripts/sdapi-serve.sh 启动;强制单 worker,
       进程内任务调度依赖单进程语义 —— 与 showvi 同款约束)
"""
import asyncio
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sd import director, lint
from sd.project import Project

from . import config as svc_config
from .agents import OPS, OP_TITLES, build_op
from . import detail
from .hub import Heartbeat, bus, print_hub
from .jobs import BusyError, manager
from .media import serve as serve_media


@asynccontextmanager
async def lifespan(app):
    print_hub.install()
    bus.attach_loop(asyncio.get_running_loop())
    asyncio.ensure_future(Heartbeat(bus).run())
    yield


app = FastAPI(title="shortdrama 工作台", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ================================================================ 异常与启动
@app.exception_handler(BusyError)
async def _busy(request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# ================================================================ 读接口
@app.get("/api/health")
def api_health():
    import time as _t
    return {"ok": True, "name": "suncut-sdapi", "version": app.version,
            "now": _t.strftime("%F %T"),
            "active_jobs": len([j for j in manager.list() if j.status in ("queued", "running", "awaiting")]),
            "history_jobs": len(manager.list())}


@app.get("/api/overview")
def api_overview():
    return detail.overview()


@app.get("/api/projects")
def api_projects():
    return {"projects": Project.list_all()}


class NewProject(BaseModel):
    name: str
    brief: str
    shots: int = 4
    orientation: str = "landscape"     # 仅 landscape；生成端原生 16:9
    resolution: str = "1080p"          # 1080p | 720p | 480p


@app.post("/api/projects")
def api_new_project(p: NewProject):
    from sd import config as sd_config
    if not re.fullmatch(r"[\w\u4e00-\u9fff-]+", p.name):
        raise HTTPException(422, "项目名只能含中文/字母/数字/下划线/连字符")
    proj = Project(p.name)
    if proj.exists():
        raise HTTPException(409, f"项目已存在: {p.name}")
    if not p.brief.strip():
        raise HTTPException(422, "brief 不能为空")
    if p.orientation not in sd_config.ORIENTATIONS:
        raise HTTPException(422, f"orientation 只能是 {list(sd_config.ORIENTATIONS)}")
    if p.resolution not in sd_config.RESOLUTIONS:
        raise HTTPException(422, f"resolution 只能是 {list(sd_config.RESOLUTIONS)}")
    proj.create(p.brief, max(1, min(p.shots, 12)),
                orientation=p.orientation, resolution=p.resolution)
    return {"ok": True, "name": p.name}


@app.get("/api/projects/{name}")
def api_project(name: str):
    d = detail.project_detail(name)
    if d is None:
        raise HTTPException(404, f"项目不存在: {name}")
    return d


@app.get("/api/projects/{name}/stage/{stage}")
def api_stage(name: str, stage: str):
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    data = proj.load_stage(stage)
    if data is None:
        raise HTTPException(404, f"阶段 {stage} 尚无产物")
    return data


@app.get("/api/pool")
def api_pool():
    return {"actors": detail.pool_list()}


@app.get("/api/config")
def api_config():
    from sd import config as sd_config
    return {"host": svc_config.HOST, "port": svc_config.PORT,
            "projects": str(sd_config.PROJECTS),
            "runtime": str(sd_config.SD_RUNTIME),
            "workshop": str(sd_config.WORKSHOP),
            "asset_lib": str(sd_config.ASSET_LIB),
            "desktop": str(sd_config.DESKTOP),
            "models": {"text": sd_config.LLM_TEXT, "fast": sd_config.LLM_FAST,
                       "vision": sd_config.LLM_VISION},
            "video": {"w": sd_config.VIDEO_W, "h": sd_config.VIDEO_H,
                      "seconds": round(sd_config.SHOT_SECONDS, 2)},
            "comfyui": "http://127.0.0.1:8189",
            "media_roots": [str(r) for r in svc_config.MEDIA_ROOTS]}


# ================================================================ 任务提交
class RunBody(BaseModel):
    op: str
    force: bool = False
    mode: str = "stepwise"          # pipeline: stepwise | auto
    auto_retake: bool = True        # produce
    case: str | None = None
    advice: str = ""
    steps: int = 14
    seed: int | None = None
    subs: bool = False              # deliver/master: 烧字幕


PROJECT_OPS = {"cast", "cast_manual", "materials", "outline", "script", "storyboard",
               "generate", "review", "dub", "deliver", "master", "retake", "retake_failed",
               "regen", "produce", "pipeline"}


@app.post("/api/projects/{name}/run")
def api_run(name: str, b: RunBody):
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    if b.op not in PROJECT_OPS:
        raise HTTPException(422, f"未知 op: {b.op}")
    if b.op in ("retake", "regen") and not b.case:
        raise HTTPException(422, "缺少 case")
    ctx = {"name": name, "force": b.force, "mode": b.mode,
           "auto_retake": b.auto_retake, "case": b.case,
           "advice": b.advice, "steps": b.steps, "seed": b.seed,
           "subs": b.subs}
    title = OP_TITLES.get(b.op, b.op)
    if b.case:
        title += f" {b.case}"
    if b.force:
        title += " (force)"
    if b.subs and b.op in ("deliver", "master"):
        title += " 📝"
    fn, gpu, tail = build_op(b.op, ctx)
    job = manager.submit(b.op, title, fn, project=name, gpu=gpu,
                         pausable=(b.op == "pipeline"), tail_gen=tail)
    return {"job_id": job.id, "job": job.dto()}


@app.post("/api/pool/{char}/run")
def api_pool_run(char: str, b: RunBody):
    if b.op not in ("buildrefs", "turntable"):
        raise HTTPException(422, "演员库只支持 buildrefs / turntable")
    fn, gpu, tail = build_op(b.op, {"char": char})
    job = manager.submit(b.op, f"{OP_TITLES[b.op]} · {char}", fn, gpu=gpu, tail_gen=tail)
    return {"job_id": job.id, "job": job.dto()}


class DoctorBody(BaseModel):
    llm: bool = False


@app.post("/api/doctor")
def api_doctor(b: DoctorBody = None):
    body = b or DoctorBody()
    fn, gpu, tail = build_op("doctor", {"llm": body.llm})
    job = manager.submit("doctor", "环境预检" + ("(含LLM实测)" if body.llm else ""), fn)
    return {"job_id": job.id, "job": job.dto()}


# ================================================================ 签约新演员(候选区/试镜/入库)
class CardsBody(BaseModel):
    requirement: str
    count: int = 3


@app.post("/api/audition/cards")
def api_audition_cards(b: CardsBody):
    """招聘要求 → 人设卡[](秒级,零 GPU;不落盘,前端可编辑后再生成)."""
    from sd import audition as A
    if not b.requirement.strip():
        raise HTTPException(422, "招聘要求不能为空")
    try:
        cards = A.make_cards(b.requirement, max(1, min(b.count, 8)))
    except Exception as e:
        raise HTTPException(502, f"人设卡生成失败: {e}")
    return {"cards": cards}


class AuditionGenerateBody(BaseModel):
    cards: list[dict]


@app.post("/api/audition/generate")
def api_audition_generate(b: AuditionGenerateBody):
    if not b.cards:
        raise HTTPException(422, "cards 为空")
    fn, gpu, tail = build_op("audition.generate", {"cards": b.cards})
    job = manager.submit("audition.generate",
                         f"生成试镜照 ×{len(b.cards)}", fn, gpu=gpu, tail_gen=tail)
    return {"job_id": job.id, "job": job.dto()}


@app.get("/api/audition")
def api_audition_list():
    from sd import audition as A
    return {"candidates": A.list_candidates()}


def _audition_name(name: str):
    """候选名白名单校验(防路径穿越:sign 会移动目录,必须严格)."""
    import re as _re
    if not _re.fullmatch(r"[\w\u4e00-\u9fff-]{1,24}", name):
        raise HTTPException(422, "非法候选名")
    return name


class SignBody(BaseModel):
    name_override: str | None = None


@app.post("/api/audition/{name}/sign")
def api_audition_sign(name: str, b: SignBody = None):
    _audition_name(name)
    ov = (b or SignBody()).name_override
    if ov:
        _audition_name(ov)
    fn, gpu, tail = build_op("audition.sign",
                             {"name": name, "name_override": ov})
    job = manager.submit("audition.sign", f"签约入库 · {name}", fn, gpu=gpu, tail_gen=tail)
    return {"job_id": job.id, "job": job.dto()}


@app.post("/api/audition/{name}/reroll")
def api_audition_reroll(name: str):
    _audition_name(name)
    fn, gpu, tail = build_op("audition.reroll", {"name": name})
    job = manager.submit("audition.reroll", f"重掷试镜照 · {name}", fn, gpu=gpu, tail_gen=tail)
    return {"job_id": job.id, "job": job.dto()}


@app.post("/api/audition/{name}/discard")
def api_audition_discard(name: str):
    _audition_name(name)
    from sd import audition as A
    try:
        A.discard(name)
    except KeyError as e:
        raise HTTPException(404, str(e))
    bus.publish("project", name=name)
    return {"ok": True}


class BatchBody(BaseModel):
    requirement: str = "多样化配角"
    count: int = 5
    direct_sign: bool = True


@app.post("/api/audition/batch")
def api_audition_batch(b: BatchBody):
    fn, gpu, tail = build_op("audition.batch",
                             {"requirement": b.requirement, "count": max(1, min(b.count, 10)),
                              "direct_sign": b.direct_sign})
    n = max(1, min(b.count, 10))
    job = manager.submit("audition.batch",
                         f"批量签约{'入库' if b.direct_sign else '试镜'} ×{n}", fn, gpu=gpu)
    return {"job_id": job.id, "job": job.dto()}


class SignCardsBody(BaseModel):
    cards: list[dict]                # [{name, positioning_cn, face_dna, outfit_dna, seed?, look?}]


@app.post("/api/audition/sign-cards")
def api_audition_sign_cards(b: SignCardsBody):
    """按既定名单批量签约(卡直入全链;look=game 为游戏还原外观模式)."""
    import re as _re
    if not b.cards:
        raise HTTPException(422, "cards 为空")
    if len(b.cards) > 40:
        raise HTTPException(422, "单批最多 40 人")
    seen = set()
    for c in b.cards:
        if not _re.fullmatch(r"[\w\u4e00-\u9fff-]{1,24}", str(c.get("name", ""))):
            raise HTTPException(422, f"非法 name: {c.get('name')!r}")
        if c["name"] in seen:
            raise HTTPException(422, f"名单重复: {c['name']}")
        seen.add(c["name"])
        if len(str(c.get("face_dna", ""))) < 40:
            raise HTTPException(422, f"{c['name']} face_dna 过短(≥40 字符)")
        if len(str(c.get("outfit_dna", ""))) < 20:
            raise HTTPException(422, f"{c['name']} outfit_dna 过短(≥20 字符)")
        if c.get("look") not in (None, "cn", "game"):
            raise HTTPException(422, f"{c['name']} look 只能是 cn/game")
    import random as _rand
    cards = [{**c, "seed": int(c.get("seed") or _rand.randint(1_000_000, 9_999_999))}
             for c in b.cards]
    fn, gpu, tail = build_op("audition.sign_cards", {"cards": cards})
    job = manager.submit("audition.sign_cards",
                         f"按名单批量签约 ×{len(cards)}", fn, gpu=gpu)
    return {"job_id": job.id, "job": job.dto()}


class RefitBody(BaseModel):
    plan: list[dict]               # [{name, positioning_cn?, face_dna, outfit_dna, portrait, seed?}]


@app.post("/api/audition/refit")
def api_audition_refit(b: RefitBody):
    """按官方立绘批量重置演员参考图(VLM 精修 DNA + Qwen2.1 看图重出全套)."""
    import re as _re
    from pathlib import Path as _Path
    if not b.plan:
        raise HTTPException(422, "plan 为空")
    if len(b.plan) > 40:
        raise HTTPException(422, "单批最多 40 人")
    seen = set()
    for c in b.plan:
        if not _re.fullmatch(r"[\w\u4e00-\u9fff-]{1,24}", str(c.get("name", ""))):
            raise HTTPException(422, f"非法 name: {c.get('name')!r}")
        if c["name"] in seen:
            raise HTTPException(422, f"名单重复: {c['name']}")
        seen.add(c["name"])
        if len(str(c.get("face_dna", ""))) < 40:
            raise HTTPException(422, f"{c['name']} face_dna 过短")
        if len(str(c.get("outfit_dna", ""))) < 20:
            raise HTTPException(422, f"{c['name']} outfit_dna 过短")
        p = c.get("portrait")
        if not p or not _Path(p).exists():
            raise HTTPException(422, f"{c['name']} portrait 不存在: {p}")
    fn, gpu, tail = build_op("audition.refit", {"plan": b.plan})
    job = manager.submit("audition.refit",
                         f"按立绘批量重置 ×{len(b.plan)}", fn, gpu=gpu)
    return {"job_id": job.id, "job": job.dto()}


# ================================================================ 任务查询与控制
@app.get("/api/jobs")
def api_jobs(project: str | None = None):
    return {"jobs": [j.dto() for j in reversed(manager.list(project=project))]}


@app.get("/api/jobs/{jid}")
def api_job(jid: str, tail: int = 400):
    j = manager.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在")
    d = j.dto()
    d["log"] = j.log_lines(tail)
    return d


@app.post("/api/jobs/{jid}/resume")
def api_job_resume(jid: str):
    j = manager.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在")
    if j.status != "awaiting":
        raise HTTPException(409, f"任务不在审批门上(当前 {j.status})")
    j.resume()
    return {"ok": True, "job": j.dto()}


@app.post("/api/jobs/{jid}/cancel")
def api_job_cancel(jid: str):
    j = manager.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在")
    if j.status in ("done", "failed", "cancelled"):
        raise HTTPException(409, "任务已结束")
    if not j.request_cancel():
        raise HTTPException(409, "任务正在执行中,仅能在阶段间隙/审批门处取消;生成类任务请等其自然结束(产物可断点续跑)")
    return {"ok": True, "job": j.dto()}


# ================================================================ 人工编辑位
class DDBody(BaseModel):
    case: str
    dd: str


@app.post("/api/projects/{name}/dd")
def api_edit_dd(name: str, b: DDBody):
    """外科手术式 dd 编辑:过 lint 闸,DNA/音乐段逐字保留(_rebuild_prompt)."""
    proj = Project(name)
    sb = proj.load_stage("storyboard")
    if not sb or not sb.get("jsonl"):
        raise HTTPException(404, "分镜尚未生成")
    jf = Path(sb["jsonl"])
    if not jf.exists():
        raise HTTPException(404, f"prompts.jsonl 不存在: {jf}")
    rows = [json.loads(l) for l in jf.read_text().splitlines() if l.strip()]
    row = next((r for r in rows if r["case_id"] == b.case), None)
    if row is None:
        raise HTTPException(404, f"没有镜头 {b.case}")

    dd_new = b.dd.strip()
    hits = lint.lint_dd(dd_new)
    if hits:
        return JSONResponse(status_code=422, content={
            "detail": "lint 未通过(动作≤3节点/禁手部特写/禁正面说话/禁混乱快动作)",
            "hits": [{"rule": h[0], "match": h[1], "fix": h[2]} for h in hits],
            "dd": dd_new})
    if row.get("task") == "ref2va" and "<Subject 1>" not in dd_new:
        dd_new = "<Subject 1> " + dd_new
    row["prompt"] = director._rebuild_prompt(row["prompt"], dd_new)
    row["dd"] = dd_new
    tmp = jf.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    tmp.replace(jf)
    return {"ok": True, "case": b.case, "dd": dd_new}


class BriefBody(BaseModel):
    brief: str


@app.post("/api/projects/{name}/brief")
def api_edit_brief(name: str, b: BriefBody):
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    if not b.brief.strip():
        raise HTTPException(422, "brief 不能为空")
    (proj.path / "brief.txt").write_text(b.brief.strip() + "\n")
    return {"ok": True, "warning": "brief 已更新;已完成的阶段不会自动重做,需在对应 agent 面板里 force 重跑"}


class HumanBody(BaseModel):
    case: str
    approved: bool
    note: str = ""


@app.post("/api/projects/{name}/review/human")
def api_human_review(name: str, b: HumanBody):
    """人工审片标记:approved=false 即否决(工作台会引导发起带 advice 的重拍)."""
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    if b.approved and not b.note.strip():
        raise HTTPException(422, "人工通过必须写明判断理由")
    import time as _t
    rv = proj.load_stage("review") or {}
    reviewed = next((r for r in rv.get("results", []) if r.get("case") == b.case), None)
    if not reviewed or not reviewed.get("video"):
        raise HTTPException(409, "该镜没有绑定具体视频的有效审片结果，请先重新审片")
    f = proj.path / "review" / "human.json"
    data = {}
    if f.exists():
        try:
            data = json.loads(f.read_text())
        except Exception:
            data = {}
    data[b.case] = {"approved": b.approved, "note": b.note.strip(),
                    "video": reviewed["video"],
                    "machine_verdict": reviewed.get("verdict"),
                    "at": _t.strftime("%F %T")}
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    bus.publish("project", name=name)
    return {"ok": True, "human": data[b.case]}


# ================================================================ 资产库(道具/场地)
@app.get("/api/assets")
def api_assets_list(kind: str | None = None):
    from sd import assetlib
    kinds = [kind] if kind else list(assetlib.KINDS)
    if kind and kind not in assetlib.KINDS:
        raise HTTPException(422, f"kind 只能是 {list(assetlib.KINDS)}")
    return {k: assetlib.list_assets(k) for k in kinds}


class AssetBody(BaseModel):
    kind: str
    asset: dict


@app.post("/api/assets")
def api_assets_save(b: AssetBody):
    from sd import assetlib
    try:
        a = assetlib.save(b.kind, b.asset)
    except ValueError as e:
        raise HTTPException(422, str(e))
    bus.publish("assets", kind=b.kind)
    return {"ok": True, "asset": a}


@app.delete("/api/assets/{kind}/{asset_id}")
def api_assets_delete(kind: str, asset_id: str):
    from sd import assetlib
    try:
        assetlib.remove(kind, asset_id)
    except (ValueError, KeyError) as e:
        raise HTTPException(404, str(e))
    bus.publish("assets", kind=kind)
    return {"ok": True}


class AssetsPickBody(BaseModel):
    scenes: list[str] = []
    props: list[str] = []


@app.post("/api/projects/{name}/assets")
def api_assets_pick(name: str, b: AssetsPickBody):
    """项目预选场地/道具(服化道阶段前挑库;锁定场地逐字复用)."""
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    from sd import assetlib
    for sid in b.scenes:
        if not assetlib.get("scene", sid):
            raise HTTPException(404, f"场地不存在: {sid}")
    for pid in b.props:
        if not assetlib.get("prop", pid):
            raise HTTPException(404, f"道具不存在: {pid}")
    pick = proj.save_assets_pick(b.scenes[:4], b.props[:6])
    bus.publish("project", name=name)
    warn = ""
    if proj.stage_done("materials"):
        warn = "服化道已生成;预选要在服化道面板 force 重跑才生效"
    return {"ok": True, "pick": pick, "warning": warn}


# ================================================================ 手动选角 / 项目设置 / BGM
class ManualCastBody(BaseModel):
    cast: list[dict]            # [{story_role, char, reason?, wardrobe_note?}] ×1-2


@app.post("/api/projects/{name}/cast")
def api_manual_cast(name: str, b: ManualCastBody):
    from sd import pool as sd_pool
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    if not 1 <= len(b.cast) <= 2:
        raise HTTPException(422, "选角 1-2 人")
    chars = {c["name"] for c in sd_pool.scan_all()}
    bad = [c.get("char") for c in b.cast if c.get("char") not in chars]
    if bad:
        raise HTTPException(404, f"演员库没有: {bad}")
    dup = len({c.get("char") for c in b.cast}) != len(b.cast)
    if dup:
        raise HTTPException(422, "选角重复")
    fn, gpu, tail = build_op("cast_manual", {"name": name, "cast": b.cast})
    names = "、".join(c["char"] for c in b.cast)
    job = manager.submit("cast_manual", f"手动选角 · {names}", fn,
                         project=name, gpu=gpu, tail_gen=tail)
    return {"job_id": job.id, "job": job.dto()}


class SettingsBody(BaseModel):
    orientation: str | None = None
    resolution: str | None = None


@app.post("/api/projects/{name}/settings")
def api_settings(name: str, b: SettingsBody):
    from sd import config as sd_config
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    if b.orientation is not None and b.orientation not in sd_config.ORIENTATIONS:
        raise HTTPException(422, f"orientation 只能是 {list(sd_config.ORIENTATIONS)}")
    if b.resolution is not None and b.resolution not in sd_config.RESOLUTIONS:
        raise HTTPException(422, f"resolution 只能是 {list(sd_config.RESOLUTIONS)}")
    s = proj.update_settings(orientation=b.orientation, resolution=b.resolution)
    bus.publish("project", name=name)
    warn = "已交付过的话需重新交付才生效" if proj.stage_done("deliver") else ""
    return {"ok": True, "settings": s, "warning": warn}


@app.get("/api/music-library")
def api_music_library():
    from sd import musiclib
    return {"tracks": musiclib.catalog()}


class MusicSelectionBody(BaseModel):
    track_id: str


@app.post("/api/projects/{name}/bgm/library")
def api_select_library_bgm(name: str, b: MusicSelectionBody):
    from sd import musiclib
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    try:
        picked = musiclib.write_selection(proj, b.track_id)
        picked = musiclib.materialize_selected_bgm(proj)
    except musiclib.MusicLibraryError as e:
        raise HTTPException(422, str(e)) from e
    bus.publish("project", name=name)
    return {"ok": True, "bgm": picked}


@app.post("/api/projects/{name}/bgm")
async def api_upload_bgm(name: str, request: Request):
    """上传全片 BGM 替换文件(audio/bgm.*;配音/交付时循环铺底并侧链让路人声)."""
    from fastapi.responses import JSONResponse
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    ct = (request.headers.get("content-type") or "").split(";")[0].strip()
    ext = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
           "audio/x-wav": ".wav", "audio/flac": ".flac", "audio/mp4": ".m4a",
           "audio/x-m4a": ".m4a", "application/octet-stream": ".bin"}.get(ct)
    if ext is None:
        raise HTTPException(422, f"不支持的音频类型: {ct}(支持 mp3/wav/flac/m4a)")
    body = await request.body()
    if not body:
        raise HTTPException(422, "空文件")
    if len(body) > 80 << 20:
        raise HTTPException(413, "文件过大(>80M)")
    if ext == ".bin":                      # 探测法兜底: magic bytes
        magic = body[:16]
        ext = (".mp3" if magic[:3] == b"ID3" or (magic[:2] == b"\xff\xfb" or magic[:2] == b"\xff\xf3")
               else ".wav" if magic[:4] == b"RIFF" else ".flac" if magic[:4] == b"fLaC"
               else None)
        if ext is None:
            raise HTTPException(422, "无法识别的音频格式(支持 mp3/wav/flac/m4a)")
    audio_dir = proj.path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for old in audio_dir.glob("bgm.*"):    # 替换式: 只保留一份
        old.unlink()
    # 上传素材覆盖曲库选择，避免交付时误用旧的授权台账。
    from sd import musiclib
    musiclib.selection_path(proj).unlink(missing_ok=True)
    f = audio_dir / f"bgm{ext}"
    f.write_bytes(body)
    import subprocess as _sp
    r = _sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(f)], capture_output=True, text=True)
    try:
        dur = float(r.stdout.strip())
    except ValueError:
        f.unlink()
        raise HTTPException(422, "不是有效的音频文件")
    bus.publish("project", name=name)
    return JSONResponse({"ok": True, "bgm": str(f), "duration": round(dur, 1),
                         "note": "配音/交付时自动循环铺底;删除该文件即恢复视频原声"})


@app.delete("/api/projects/{name}/bgm")
def api_delete_bgm(name: str):
    proj = Project(name)
    if not proj.exists():
        raise HTTPException(404, "项目不存在")
    removed = False
    audio_dir = proj.path / "audio"
    if audio_dir.exists():
        for old in audio_dir.glob("bgm.*"):
            old.unlink()
            removed = True
    from sd import musiclib
    if musiclib.selection_path(proj).exists():
        musiclib.selection_path(proj).unlink()
        removed = True
    bus.publish("project", name=name)
    return {"ok": True, "removed": removed}


# ================================================================ 媒体与日志
@app.get("/api/media")
def api_media(request: Request, path: str, download: bool = False):
    return serve_media(request, path=path, download=download)


@app.get("/api/projects/{name}/log/{which}")
def api_gen_log(name: str, which: str, tail: int = 200):
    """查看 runtime 下的 gen-*.log(仅白名单根内、防穿越)."""
    from sd import config as sd_config
    p = (Path(sd_config.SD_RUNTIME) / name / f"gen-{which}.log")
    if not p.exists():
        raise HTTPException(404, "日志不存在")
    lines = p.read_text(errors="replace").splitlines()
    return {"name": p.name, "lines": lines[-tail:]}


# ================================================================ WebSocket
@app.websocket("/api/ws")
async def api_ws(ws: WebSocket):
    await ws.accept()
    bus.connect(ws)
    try:
        await ws.send_text(json.dumps(
            {"type": "hello", "jobs": [j.dto() for j in manager.list()[:30]],
             "t": time.strftime("%F %T")}, ensure_ascii=False))
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        bus.disconnect(ws)


# ================================================================ 静态前端
@app.get("/")
async def index():
    return FileResponse(svc_config.STATIC_DIR / "index.html",
                        headers={"Cache-Control": "no-store"})


class NoCacheStaticFiles(StaticFiles):
    """改完即生效(showvi 同款):本地工作台不做静态缓存,杜绝浏览器旧 JS."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-store"
        return resp


app.mount("/static", NoCacheStaticFiles(directory=str(svc_config.STATIC_DIR)),
          name="static")
