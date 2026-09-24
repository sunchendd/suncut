"""导演 agent —— 调 Sol-H3 infer.py 批量生成(草稿档) / 单镜重拍.

重拍 v2: 审片建议经 LLM 外科手术式改写该镜 detailed_description
(DNA/音乐块仍由程序从原 prompt 切割复用,绝不整段重写),再换 seed 重跑。
"""
import json
import re
import subprocess

from . import config, llm
from .lint import lint_dd, violations_feedback

MP4_REL = "stage2/refined_1344x768_121f.mp4"

# 任务对应的 prepare.py 产物(t2va 用 paths.json,ref2va/fl2va 有专用 paths)
PATHS_BY_TASK = {"t2va": "paths.json", "ref2va": "paths-ref2va.json",
                 "fl2va": "paths-fl2va.json"}


def _existing_outputs(proj, case_ids):
    """扫历史 gen-* 目录,复用已成功的镜头(换批不重跑);优先首轮产物."""
    found = {}
    dirs = sorted((config.SD_RUNTIME / proj.name).glob("gen-*/batch"),
                  key=lambda d: (0 if d.parent.name == "gen-a1" else 1, str(d)))
    for d in dirs:
        for case in case_ids:
            mp4 = d / case / MP4_REL
            if mp4.exists() and case not in found:
                found[case] = str(mp4)
    return found

REWRITE_SYSTEM = ("你是导演执行重拍修订。只改 detailed_description 以落实审片建议,"
                  "保持: <Subject 1> 开头、单一连续运镜、**1 主爆发+最多1次要+收势(≤3节点,"
                  "审片动作分低通常是动作太密)**、无手部特写、正脸不说话、"
                  "场景与原意不变、英文一段。只输出 JSON。")


def _run_infer(rows, outdir, log_path, timeout=7200):
    jf = outdir.with_suffix(".jsonl")
    jf.parent.mkdir(parents=True, exist_ok=True)
    jf.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    batch_dir = outdir / "batch"   # 不得预建: infer.py 要求输出目录全新(exist_ok=False)
    n = 1
    while batch_dir.exists():      # 残留的半成品目录(被杀进程遗留)自动避开
        done = all((batch_dir / r["case_id"] / MP4_REL).exists() for r in rows)
        if done:
            return 0, batch_dir    # 完整产物直接复用
        n += 1
        batch_dir = outdir.parent / f"{outdir.name}-{n}" / "batch"
    paths = PATHS_BY_TASK.get(rows[0].get("task", "ref2va"), "paths-ref2va.json")
    inner = (f"cd {config.SOL_PKG} && python3 infer.py --paths {paths} "
             f"--prompts {jf} --output-dir {batch_dir}")
    cmd = f"export {config.INFER_ENV}; sg docker -c '{inner}'"
    with open(log_path, "w") as log:
        r = subprocess.run(["bash", "-c", cmd], stdout=log,
                           stderr=subprocess.STDOUT, timeout=timeout)
    return r.returncode, batch_dir


def _collect(batch_dir, rows):
    videos = {}
    for row in rows:
        mp4 = batch_dir / row["case_id"] / MP4_REL
        videos[row["case_id"]] = str(mp4) if mp4.exists() else None
    return videos


def shoot(proj, force=False):
    """草稿档全片生成。infer.py 一批只能跑一个 task,按 ref2va/t2va 自动分批."""
    if proj.stage_done("generate") and not force:
        return proj.load_stage("generate")["videos"]
    sb = proj.load_stage("storyboard")
    rows = [json.loads(l) for l in open(sb["jsonl"])]
    videos = _existing_outputs(proj, [r["case_id"] for r in rows])   # 复用历史成功镜头
    if len(videos) == len(rows):
        proj.save_stage("generate", {"videos": videos, "attempt": "a1"},
                        meta={"shots": len(videos), "reused": True})
        return videos
    for gi, task in enumerate(dict.fromkeys(r.get("task", "ref2va") for r in rows)):
        grp = [r for r in rows if r.get("task", "ref2va") == task
               and r["case_id"] not in videos]
        if not grp:
            continue
        outdir = config.SD_RUNTIME / proj.name / (f"gen-a1" if gi == 0 else f"gen-a1-{task}")
        log = outdir.with_suffix(".log")
        print(f"[导演] 开拍 {len(grp)} 镜 task={task} (草稿档),日志 {log}")
        code, batch_dir = _run_infer(grp, outdir, log)
        videos.update({k: v for k, v in _collect(batch_dir, grp).items() if v})
    # 历史坑(工作流§5.3): worker 超时/重编译崩溃 → 验证产物后重跑缺失镜(历史 100% 恢复)
    for attempt in (2, 3):
        missing_rows = [r for r in rows if not videos.get(r["case_id"])]
        if not missing_rows:
            break
        outdir = config.SD_RUNTIME / proj.name / f"gen-a1-retry{attempt}"
        print(f"[导演] 缺 {len(missing_rows)} 镜,重跑(第{attempt - 1}次): {outdir.name}")
        code, batch_dir = _run_infer(missing_rows, outdir, outdir.with_suffix(".log"))
        videos.update({k: v for k, v in _collect(batch_dir, missing_rows).items() if v})
    missing = [r["case_id"] for r in rows if not videos.get(r["case_id"])]
    if missing:
        raise RuntimeError(f"infer 重跑后仍缺 {len(missing)} 镜: {missing}")
    if len(videos) != len(rows):
        raise RuntimeError(f"产物数不符: {len(videos)}/{len(rows)}")
    proj.save_stage("generate", {"videos": videos, "attempt": "a1"},
                    meta={"shots": len(videos)})
    state = proj.load_state()
    if "review" in state.get("stages", {}):   # 视频集变了,旧审片作废
        state["stages"].pop("review")
        proj._write_state(state)
    return videos


def retake(proj, case_id, advice="", force=False):
    """单镜重拍 v2: 审片建议改写 dd(带 lint 闸) + 换 seed;无建议时仅换 seed."""
    sb = proj.load_stage("storyboard")
    rows = {r["case_id"]: r for r in (json.loads(l) for l in open(sb["jsonl"]))}
    if case_id not in rows:
        raise KeyError(f"没有镜头 {case_id}")
    state = proj.load_state()
    takes = state.get("takes", {}).get(case_id, [])
    new_seed = rows[case_id]["seed"] + config.RETAKE_SEED_STEP * (len(takes) + 1)
    row = dict(rows[case_id])
    row["seed"] = new_seed

    if advice:
        dd = row.get("dd") or _dd_of(row["prompt"])
        user = (f"【原 detailed_description】\n{dd}\n\n【审片建议(必须落实)】\n{advice}\n\n"
                '只输出 JSON: {"detailed_description": "修订后的英文一段"}')
        fixed = llm.chat_json(config.LLM_TEXT, REWRITE_SYSTEM, user)
        dd_new = fixed["detailed_description"].strip()
        hits = lint_dd(dd_new)
        if hits:   # 修订稿违规 → 再修一轮
            fixed = llm.chat_json(config.LLM_TEXT, REWRITE_SYSTEM,
                                  user + "\n\n【你的修订违规了,必须消除】\n" + violations_feedback(hits))
            dd_new = fixed["detailed_description"].strip()
        if "<Subject 1>" not in dd_new:
            dd_new = "<Subject 1> " + dd_new
        row["prompt"] = _rebuild_prompt(row["prompt"], dd_new)
        row["dd"] = dd_new
        row["note"] = f"{row['note']} | 重拍v2({advice[:40]})"

    attempt = f"r{len(takes) + 1}"
    outdir = config.SD_RUNTIME / proj.name / f"gen-{case_id.split('-')[-1]}-{attempt}"
    log = outdir.with_suffix(".log")
    print(f"[导演] 重拍 {case_id} seed={new_seed}"
          f"{'+修订dd' if advice else '(仅换seed)'},日志 {log}")
    code, batch_dir = _run_infer([row], outdir, log)
    videos = _collect(batch_dir, [row])
    mp4 = videos[case_id]
    if not mp4:
        raise RuntimeError(f"重拍失败(退出码{code},日志 {log})")
    takes.append({"seed": new_seed, "mp4": mp4, "advice": advice})
    state.setdefault("takes", {})[case_id] = takes
    state["stages"].pop("review", None)   # 视频变了,旧审片作废
    proj._write_state(state)
    return mp4


def _dd_of(prompt):
    m = re.search(r"detailed_description:\s*(.*?)\s*overall_soundscape:", prompt, re.S)
    return m.group(1).strip() if m else prompt


def _rebuild_prompt(old_prompt, new_dd):
    """从原 prompt 切割出 subject 前缀与尾段(声音/音乐逐字复用),只替换 dd."""
    m = re.search(r"^(.*?detailed_description:\s*)", old_prompt, re.S)
    prefix = m.group(1)
    tail = re.search(r"(\.?\s*overall_soundscape:\s*.*)$", old_prompt, re.S)
    tail_txt = tail.group(1).strip() if tail else ""
    dd_clean = new_dd.strip().rstrip(". ")
    return f"{prefix}{dd_clean} {tail_txt}"
