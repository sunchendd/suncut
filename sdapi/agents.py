"""agents —— 8 个 agent 的服务化门面:把 sd/ 的同步函数包装成可提交的任务体.

约定: 所有 op 形如 fn(job, **ctx),由 JobManager 在工作线程里调用;
print 输出被 PrintHub 自动收进任务日志,长耗时的 infer 进度由 GenLogTailer 追加.
"""
import json

from sd import (casting, config as sd_config, director, doctor, dubbing,
                materials, producer, qwenimage, regen as regen_mod, report,
                reviewer, screenwriter, storyboard, turntable)
from sd.metrics import Metrics, stopwatch
from sd.project import Project

from .jobs import manager

STAGES = [
    ("cast", "1/8 招聘选角", casting.run, False),
    ("materials", "2/8 服化道", materials.run, False),
    ("script", "3/8 编剧", screenwriter.run, False),
    ("storyboard", "4/8 分镜", storyboard.run, False),
    ("generate", "5/8 导演开拍", director.shoot, True),
    ("review", "6/8 审片", reviewer.review, False),
    ("dub", "7/8 配音配乐", dubbing.run, False),
    ("deliver", "8/8 制片交付", producer.deliver, False),
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


def op_outline(job, name=None, force=False, **_):
    """两段式编剧第一段: 叙事大纲(钩子/情绪曲线/意象库),可独立运行审阅."""
    proj = Project(name)
    _stage(job, "outline", "3/8 编剧·叙事大纲")
    with stopwatch(proj, "outline"):
        return screenwriter.run_outline(proj, force=force)


def op_cast_manual(job, name=None, cast=None, **_):
    """手动选角(工作台): 1-2 名演员 + 角色名;缺三视图自动补(GPU)."""
    proj = Project(name)
    _stage(job, "cast", "1/8 招聘选角(手动)")
    with stopwatch(proj, "cast"):
        return casting.run_manual(proj, cast or [])


def op_deliver(job, name=None, force=False, subs=False, **_):
    """交付(可选字幕烧录;配音产物存在时自动混入)."""
    proj = Project(name)
    _stage(job, "deliver", "8/8 制片交付" + ("(烧字幕)" if subs else ""))
    with stopwatch(proj, "deliver"):
        return producer.deliver(proj, force=force, subs=bool(subs))


def op_master(job, name=None, force=False, subs=False, **_):
    proj = Project(name)
    _stage(job, "master", "母版超分交付")
    producer.deliver_master(proj, force=force, subs=bool(subs))
    return "母版已交付"


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


def op_retake_failed(job, name=None, **_):
    """一键重拍全部未过镜(分步流水线的审片门配套;人工翻案的不算)."""
    proj = Project(name)
    rv = proj.load_stage("review") or {}
    human = {}
    hf = (proj.path / "review" / "human.json")
    if hf.exists():
        try:
            import json as _json
            human = _json.loads(hf.read_text())
        except Exception:
            human = {}
    todo = []
    for r in rv.get("results", []):
        h = human.get(r["case"]) or {}
        if r.get("verdict") in ("retake", "fail") and not h.get("approved"):
            todo.append((r["case"], r.get("advice_cn") or r.get("advice") or ""))
    if not todo:
        job.log_write("[审片] 没有未过镜(或均已人工翻案),无需重拍\n")
        return {"retaken": []}
    job.log_write(f"[审片] 待重拍 {len(todo)} 镜: {', '.join(c for c, _ in todo)}\n")
    for i, (case, advice) in enumerate(todo, 1):
        _stage(job, "retake", f"批量重拍 {i}/{len(todo)} · {case}")
        with stopwatch(proj, "retake", case=case):
            director.retake(proj, case, advice=advice)
    job.log_write("[审片] 全部重拍完成,请重新审片(force)\n")
    return {"retaken": [c for c, _ in todo]}


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
        if stage == "script" and not proj.stage_done("script"):
            # 两段式编剧: 剧本未成先出叙事大纲(stepwise 挂审阅门,老项目剧本已成则跳过)
            _stage(job, "outline", "3/8 编剧·叙事大纲")
            screenwriter.run_outline(proj)
            if not auto:
                gate("outline_done", "叙事大纲完成 —— 审阅钩子/情绪曲线/意象库后放行",
                     meta={"artifact": "outline"})
        with stopwatch(proj, stage):
            _stage(job, stage, label)
            fn(proj, force=False)
        if not auto:
            gate(f"{stage}_done", f"{label}完成 —— 请在工作台审阅后放行",
                 meta={"artifact": stage})

    with manager.gpu_lock:
        with stopwatch(proj, "generate"):
            _stage(job, "generate", "5/8 导演开拍")
            director.shoot(proj, force=False)

    with stopwatch(proj, "review"):
        _stage(job, "review", "6/8 审片")
        rv = reviewer.review(proj, force=False)
    Metrics(proj).mark("review", 0.0, {"passed": f"{rv['passed']}/{rv['total']}"})
    # 人工审片标记参与判定:人工翻案(通过)的未过镜不算失败;人工否决的过镜算失败
    import json as _json
    from pathlib import Path as _Path
    human = {}
    hf = _Path(proj.path) / "review" / "human.json"
    if hf.exists():
        try: human = _json.loads(hf.read_text())
        except Exception: human = {}
    failing, overridden = [], []
    for r in rv.get("results", []):
        h = human.get(r["case"]) or {}
        if r.get("verdict") in ("retake", "fail"):
            if h.get("approved"):
                overridden.append(r["case"])      # VLM 未过但人工翻案
                continue
            failing.append({"case": r["case"],
                            "advice": r.get("advice_cn") or r.get("advice") or ""})
        elif h and not h.get("approved"):
            failing.append({"case": r["case"],
                            "advice": (h.get("note") or "人工否决") + "(人工否决)"})
    # 审片后必停:人工可逐镜重拍/否决,再放行交付(这是网页工作台的核心质控位)
    job.await_gate("review_done",
                   f"审片 {rv['passed']}/{rv['total']} 过"
                   + (f",人工翻案 {len(overridden)} 镜" if overridden else "")
                   + " —— 可重拍失败镜或直接放行交付",
                   meta={"failing": failing, "passed": rv["passed"], "total": rv["total"],
                         "overridden": overridden})

    # 配音(失败不阻塞: 剧本无台词或 TTS 不可用时原声直出)
    with stopwatch(proj, "dub"):
        _stage(job, "dub", "7/8 配音配乐")
        try:
            dubbing.run(proj)
        except Exception as e:
            job.log_write(f"[配音] 跳过: {e}\n")

    with stopwatch(proj, "deliver"):
        _stage(job, "deliver", "8/8 制片交付")
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


# ---------------------------------------------------------------- 签约新演员
def op_audition_generate(job, cards=None, **_):
    """人设卡[] → 候选建档 + 每人一张试镜照."""
    from sd import audition as A
    made = []
    for i, card in enumerate(cards or [], 1):
        _stage(job, "audition", f"试镜照 {i}/{len(cards)} · {card.get('name', '?')}")
        d, c2 = A.create_candidate(card)
        A.audition_photo(A.char_of(c2["name"]))
        made.append(c2["name"])
    return {"candidates": made}


def op_audition_reroll(job, name=None, **_):
    from sd import audition as A
    _stage(job, "audition", f"重掷试镜照 · {name}")
    A.audition_photo(A.char_of(name))
    return {"name": name}


def op_audition_sign(job, name=None, name_override=None, **_):
    """全链(三视图+三件套)→ 搬入 素材/角色X_名字."""
    from sd import audition as A
    _stage(job, "audition", f"签约全链 · {name}")
    final = A.sign(name, name_override=name_override)
    return {"actor": final}


def op_audition_batch(job, requirement="", count=5, direct_sign=True, **_):
    """群演批量: 一次产 count 张差异化卡;direct_sign=直接全套入库(挂机档)."""
    from sd import audition as A
    cards = A.make_cards(requirement, count)
    job.log_write(f"[签约] 批量人设卡: {', '.join(c['name'] for c in cards)}\n")
    made = []
    for i, card in enumerate(cards, 1):
        _stage(job, "audition", f"批量 {i}/{len(cards)} · {card['name']}")
        d, c2 = A.create_candidate(card)
        if direct_sign:
            A.sign(c2["name"])
        else:
            A.audition_photo(A.char_of(c2["name"]))
        made.append(c2["name"] + ("" if direct_sign else "(候选)"))
    return {"made": made, "direct_sign": direct_sign}


def op_audition_sign_cards(job, cards=None, **_):
    """按既定名单批量签约(卡直接全链入库;单人失败不断链,末尾汇总).挂机档."""
    from sd import audition as A
    made, failed = [], []
    for i, card in enumerate(cards or [], 1):
        name = card.get("name", "?")
        _stage(job, "audition", f"批量签约 {i}/{len(cards)} · {name}")
        try:
            d, c2 = A.create_candidate(card)
            final = A.sign(c2["name"], name_override=card.get("final_name"))
            made.append(final)
            job.log_write(f"[签约] {name} → {final}\n")
        except Exception as e:
            failed.append({"name": name, "error": str(e)[:200]})
            job.log_write(f"[签约] {name} 失败(继续下一个): {e}\n")
    job.log_write(f"[签约] 批量完成: 成功 {len(made)} / 失败 {len(failed)}\n")
    return {"made": made, "failed": failed}


def op_audition_refit(job, plan=None, **_):
    """按官方立绘批量重置(精修 DNA + 看图重出全套参考图;单人失败不断链)."""
    from sd import audition as A
    done, failed = [], []
    for i, item in enumerate(plan or [], 1):
        name = item.get("name", "?")
        _stage(job, "audition", f"立绘重置 {i}/{len(plan)} · {name}")
        try:
            final = A.refit({k: v for k, v in item.items()
                             if k in ("name", "positioning_cn", "face_dna",
                                      "outfit_dna", "seed")},
                            item.get("portrait"))
            done.append(final)
            job.log_write(f"[重置] {name} → {final}\n")
        except Exception as e:
            failed.append({"name": name, "error": str(e)[:200]})
            job.log_write(f"[重置] {name} 失败(继续下一个): {e}\n")
    job.log_write(f"[重置] 批量完成: 成功 {len(done)} / 失败 {len(failed)}\n")
    return {"done": done, "failed": failed}


# ---------------------------------------------------------------- op 注册表
# (提交参数校验后的) op 名 -> (callable, gpu, tail_gen)
OPS = {
    "cast":         (op_simple("cast"), False, False),
    "cast_manual":  (op_cast_manual, True, False),
    "materials":    (op_simple("materials"), False, False),
    "outline":      (op_outline, False, False),
    "script":       (op_simple("script"), False, False),
    "storyboard":   (op_simple("storyboard"), False, False),
    "generate":     (op_simple("generate"), True, True),
    "review":       (op_simple("review"), False, False),
    "dub":          (op_simple("dub"), False, False),
    "deliver":      (op_deliver, False, False),
    "master":       (op_master, True, False),
    "retake":       (op_retake, True, True),
    "retake_failed": (op_retake_failed, True, True),
    "regen":        (op_regen, True, False),
    "produce":      (op_produce, True, True),
    "pipeline":     (op_pipeline, False, True),
    "buildrefs":    (op_buildrefs, True, False),
    "turntable":    (op_turntable, True, True),
    "doctor":       (op_doctor, False, False),
    "audition.generate": (op_audition_generate, True, False),
    "audition.reroll":   (op_audition_reroll, True, False),
    "audition.sign":     (op_audition_sign, True, False),
    "audition.batch":    (op_audition_batch, True, False),
    "audition.sign_cards": (op_audition_sign_cards, True, False),
    "audition.refit":     (op_audition_refit, True, False),
}

OP_TITLES = {"cast": "招聘选角", "cast_manual": "手动选角", "materials": "服化道",
             "outline": "叙事大纲", "script": "编剧", "storyboard": "分镜", "generate": "导演开拍",
             "review": "审片", "dub": "配音配乐",
             "deliver": "制片交付", "master": "母版超分", "retake": "单镜重拍", "retake_failed": "一键重拍未过镜",
             "regen": "14步重生成", "produce": "全自动流水线",
             "pipeline": "分步流水线", "buildrefs": "补角色参考图",
             "turntable": "转台参考集", "doctor": "环境预检",
             "audition.generate": "生成试镜照", "audition.reroll": "重掷试镜照",
             "audition.sign": "签约入库", "audition.batch": "批量签约群演",
             "audition.sign_cards": "按名单批量签约",
             "audition.refit": "按立绘批量重置"}


def build_op(op, ctx):
    """把 ctx 闭包进统一签名的任务体."""
    fn, gpu, tail = OPS[op]

    def wrapped(job):
        return fn(job, **ctx)
    return wrapped, gpu, tail
