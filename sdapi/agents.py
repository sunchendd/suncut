"""agents —— 7 个 agent 的服务化门面:把 sd/ 的同步函数包装成可提交的任务体.

约定: 所有 op 形如 fn(job, **ctx),由 JobManager 在工作线程里调用;
print 输出被 PrintHub 自动收进任务日志,长耗时的 infer 进度由 GenLogTailer 追加.
"""
import json

from sd import (casting, config as sd_config, director, doctor, materials,
                producer, qwenimage, regen as regen_mod, report, reviewer,
                screenwriter, storyboard, turntable)
from sd.metrics import Metrics, stopwatch
from sd.project import Project

from .jobs import manager

STAGES = [
    ("cast", "1/7 招聘选角", casting.run, False),
    ("materials", "2/7 场景物料", materials.run, False),
    ("script", "3/7 编剧", screenwriter.run, False),
    ("storyboard", "4/7 分镜", storyboard.run, False),
    ("generate", "5/7 导演开拍", director.shoot, True),
    ("review", "6/7 审片", reviewer.review, False),
    ("deliver", "7/7 制片交付", producer.deliver, False),
]


def _stage(job, name, label):
    job.meta = {**job.meta, "stage": name, "stage_label": label}
    job._set()


# ---------------------------------------------------------------- 单阶段 op
def op_simple(stage):
    _, label, fn, _gpu = next(s for s in STAGES if s[0] == stage)

    def run(job, name=None, force=False, **_):
        proj = Project(name)
        with stopwatch(proj, stage):
            _stage(job, stage, label)
            return fn(proj, force=force)
    run.__name__ = f"op_{stage}"
    return run


def op_retake(job, name=None, case=None, advice="", **_):
    proj = Project(name)
    _stage(job, "retake", f"重拍 {case}")
    with stopwatch(proj, "retake", case=case):
        mp4 = director.retake(proj, case, advice=advice)
    return {"mp4": mp4}


def op_regen(job, name=None, case=None, steps=14, seed=None, sampler="res_multistep", **_):
    proj = Project(name)
    _stage(job, "regen", f"14步重生成 {case}")
    with stopwatch(proj, "regen", case=case):
        mp4, secs = regen_mod.run(proj, case, steps=steps, sampler=sampler, seed=seed)
    return {"mp4": mp4, "seconds": secs}


def op_master(job, name=None, force=False, **_):
    proj = Project(name)
    _stage(job, "master", "母版超分交付")
    producer.deliver_master(proj, force=force)
    return "母版已交付"


def op_produce(job, name=None, auto_retake=True, force_stage=None, **_):
    """全自动档:直接走 sd 自带的 produce(含自动重拍≤2轮)."""
    _stage(job, "produce", "全自动流水线")
    return producer.produce(name, auto_retake=auto_retake, force_stage=force_stage)


# ---------------------------------------------------------------- 分步流水线
def op_pipeline(job, name=None, mode="stepwise", **_):
    """编排版 produce:阶段间可挂人工审批门,审片后必停一档(质量控制位).

    mode=auto   : 除审片门外一路到底(门自动放行);
    mode=stepwise: 每个阶段完成都挂起等人工放行.
    """
    proj = Project(name)
    if not proj.exists():
        raise RuntimeError(f"项目不存在: {name}")
    auto = mode == "auto"
    gate = (lambda *a, **k: None) if auto else job.await_gate

    for stage, label, fn, _gpu in STAGES[:4]:
        with stopwatch(proj, stage):
            _stage(job, stage, label)
            fn(proj, force=False)
        if not auto:
            gate(f"{stage}_done", f"{label}完成 —— 请在工作台审阅后放行",
                 meta={"artifact": stage})

    with manager.gpu_lock():
        with stopwatch(proj, "generate"):
            _stage(job, "generate", "5/7 导演开拍")
            director.shoot(proj, force=False)

    with stopwatch(proj, "review"):
        _stage(job, "review", "6/7 审片")
        rv = reviewer.review(proj, force=False)
    Metrics(proj).mark("review", 0.0, {"passed": f"{rv['passed']}/{rv['total']}"})
    failing = [{"case": r["case"], "advice": r.get("advice_cn") or r.get("advice") or ""}
               for r in rv.get("results", [])
               if r.get("verdict") in ("retake", "fail")]
    # 审片后必停:人工可逐镜重拍/否决,再放行交付(这是网页工作台的核心质控位)
    job.await_gate("review_done",
                   f"审片 {rv['passed']}/{rv['total']} 过 —— 可重拍失败镜或直接放行交付",
                   meta={"failing": failing, "passed": rv["passed"], "total": rv["total"]})

    with stopwatch(proj, "deliver"):
        _stage(job, "deliver", "7/7 制片交付")
        producer.deliver(proj, force=False)
    try:
        report.make_cover(proj)
        report.write_report(proj)
    except Exception as e:                          # 封面/报告失败不阻塞交付
        job.log_write(f"[制片] 封面/报告生成失败(不影响交付): {e}\n")
    return {"passed": rv["passed"], "total": rv["total"],
            "failing": [f["case"] for f in failing]}


# ---------------------------------------------------------------- 演员库 / 系统
def op_buildrefs(job, char=None, **_):
    from sd import pool as sd_pool
    chars = sd_pool.scan_all()
    c = sd_pool.find(chars, char)
    job.log_write(f"[招聘] 为 {c['name']} 补三视图特写(Qwen 出图×3种子)…\n")
    return qwenimage.buildrefs(c)


def op_turntable(job, char=None, **_):
    from sd import pool as sd_pool
    chars = sd_pool.scan_all()
    c = sd_pool.find(chars, char)
    job.log_write(f"[招聘] 生成 {c['name']} 转台参考集…\n")
    return turntable.turntable(c)


def op_doctor(job, llm=False, **_):
    _stage(job, "doctor", "环境预检")
    ok = doctor.run(quick_llm=bool(llm))
    job.log_write("\n[doctor] 结论: " + ("全部通过" if ok else "存在未通过项,详见上方") + "\n")
    return {"ok": bool(ok)}


# ---------------------------------------------------------------- op 注册表
# (提交参数校验后的) op 名 -> (callable, gpu, tail_gen)
OPS = {
    "cast":         (op_simple("cast"), False, False),
    "materials":    (op_simple("materials"), False, False),
    "script":       (op_simple("script"), False, False),
    "storyboard":   (op_simple("storyboard"), False, False),
    "generate":     (op_simple("generate"), True, True),
    "review":       (op_simple("review"), False, False),
    "deliver":      (op_simple("deliver"), False, False),
    "master":       (op_master, True, False),
    "retake":       (op_retake, True, True),
    "regen":        (op_regen, True, False),
    "produce":      (op_produce, True, True),
    "pipeline":     (op_pipeline, False, True),
    "buildrefs":    (op_buildrefs, True, False),
    "turntable":    (op_turntable, True, True),
    "doctor":       (op_doctor, False, False),
}

OP_TITLES = {"cast": "招聘选角", "materials": "场景物料", "script": "编剧",
             "storyboard": "分镜", "generate": "导演开拍", "review": "审片",
             "deliver": "制片交付", "master": "母版超分", "retake": "单镜重拍",
             "regen": "14步重生成", "produce": "全自动流水线",
             "pipeline": "分步流水线", "buildrefs": "补角色参考图",
             "turntable": "转台参考集", "doctor": "环境预检"}


def build_op(op, ctx):
    """把 ctx 闭包进统一签名的任务体."""
    fn, gpu, tail = OPS[op]

    def wrapped(job):
        return fn(job, **ctx)
    return wrapped, gpu, tail
