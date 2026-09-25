"""shortdrama CLI —— 多角色 agent 短剧流水线.

用法:
  python3 -m sd new <名字> --brief "故事一句话" [--shots 4]
  python3 -m sd produce <名字> [--force-stage <cast|materials|script|storyboard|generate|review>]
  python3 -m sd <cast|materials|script|storyboard|generate|review|deliver> <名字> [--force]
  python3 -m sd retake <名字> <case_id> [--advice "建议"]
  python3 -m sd status [<名字>]
"""
import argparse
import json
import sys

from . import casting, config, director, materials, producer, reviewer
from . import pool, qwenimage, screenwriter, storyboard
from .project import Project


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sd", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new")
    p.add_argument("name")
    p.add_argument("--brief", required=True, help="故事梗概/一句话")
    p.add_argument("--shots", type=int, default=4)
    p.add_argument("--orientation", default="landscape",
                   choices=list(config.ORIENTATIONS), help="landscape横屏16:9(默认) | portrait竖屏9:16(裁切,清晰度降)")
    p.add_argument("--resolution", default="1080p",
                   choices=list(config.RESOLUTIONS), help="交付分辨率")

    p = sub.add_parser("produce")
    p.add_argument("name")
    p.add_argument("--force-stage", default=None)
    p.add_argument("--no-retake", action="store_true")

    p = sub.add_parser("retake")
    p.add_argument("name")
    p.add_argument("case")
    p.add_argument("--advice", default="")

    p = sub.add_parser("buildrefs")
    p.add_argument("char", help="角色目录名,如 角色C_阿比盖尔")

    p = sub.add_parser("turntable")
    p.add_argument("char", help="角色目录名;生成H3转台视频抽帧替换全身参考")

    p = sub.add_parser("metrics")
    p.add_argument("name")

    p = sub.add_parser("doctor")
    p.add_argument("--llm", action="store_true", help="附带一次 LLM 实调")

    p = sub.add_parser("master")
    p.add_argument("name")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("regen")
    p.add_argument("name")
    p.add_argument("case")
    p.add_argument("--steps", type=int, default=14)
    p.add_argument("--sampler", default="res_multistep")
    p.add_argument("--seed", type=int, default=None)

    p = sub.add_parser("status")
    p.add_argument("name", nargs="?")

    for st in ("cast", "materials", "script", "storyboard", "generate", "review", "dub", "deliver"):
        p = sub.add_parser(st)
        p.add_argument("name")
        p.add_argument("--force", action="store_true")

    a = ap.parse_args(argv)

    if a.cmd == "new":
        proj = Project(a.name)
        if proj.exists():
            sys.exit(f"项目已存在: {proj.path}")
        proj.create(a.brief, a.shots,
                    orientation=a.orientation, resolution=a.resolution)
        print(f"建项 {proj.path} ({a.orientation}/{a.resolution})\n下一步: python3 -m sd produce {a.name}")
        return
    if a.cmd == "status":
        names = [a.name] if a.name else Project.list_all()
        for n in names:
            proj = Project(n)
            if not proj.exists():
                print(f"{n}: 不存在"); continue
            st = proj.load_state()
            print(f"{n}: {len(st.get('stages', {}))} 阶段完成 "
                  f"{list(st.get('stages', {}))} shots={st.get('shots')}")
            if not a.name:
                continue
            sc = proj.load_stage("script")
            if sc:
                print(f"  剧名《{sc.get('title_cn')}》 {sc.get('logline', '')}")
            rv = proj.load_stage("review")
            if rv:
                for r in rv["results"]:
                    mark = {"pass": "✓", "retake": "✗", "fail": "✗", "error": "?"}.get(r.get("verdict"), " ")
                    print(f"  {mark} {r['case']} identity={r.get('identity','-')} "
                          f"action={r.get('action','-')} comp={r.get('composition','-')} "
                          f"{r.get('advice_cn') or r.get('advice', '')}")
        return
    if a.cmd == "doctor":
        from . import doctor
        sys.exit(0 if doctor.run(quick_llm=a.llm) else 1)
    if a.cmd == "metrics":
        proj = Project(a.name)
        if not proj.exists():
            sys.exit(f"项目不存在: {a.name}")
        from .metrics import Metrics
        print(Metrics(proj).summary())
        return
    if a.cmd == "turntable":
        chars = pool.scan_all()
        c = next((x for x in chars if a.char in x["name"]), None)
        if c is None:
            sys.exit(f"找不到角色 {a.char};可选: {[x['name'] for x in chars]}")
        from . import turntable
        print(json.dumps(turntable.turntable(c), ensure_ascii=False, indent=1))
        return
    if a.cmd == "buildrefs":
        chars = pool.scan_all()
        c = next((x for x in chars if a.char in x["name"]), None)
        if c is None:
            sys.exit(f"找不到角色 {a.char};可选: {[x['name'] for x in chars]}")
        refs = qwenimage.buildrefs(c)
        print(json.dumps(refs, ensure_ascii=False, indent=1))
        return
    if a.cmd == "regen":
        proj = Project(a.name)
        if not proj.exists():
            sys.exit(f"项目不存在: {a.name}")
        from . import regen as regen_mod
        out = regen_mod.run(proj, a.case, steps=a.steps,
                            sampler=a.sampler, seed=a.seed)
        print(out)
        return
    if a.cmd == "master":
        proj = Project(a.name)
        if not proj.exists():
            sys.exit(f"项目不存在: {a.name}")
        paths = producer.deliver_master(proj, force=a.force)
        print(json.dumps(paths, ensure_ascii=False, indent=1))
        return
    if a.cmd == "produce":
        producer.produce(a.name, auto_retake=not a.no_retake, force_stage=a.force_stage)
        return

    if a.cmd == "retake":
        proj = Project(a.name)
        if not proj.exists():
            sys.exit(f"项目不存在: {a.name}")
        mp4 = director.retake(proj, a.case, advice=a.advice)
        print("重拍完成:", mp4)
        return

    proj = Project(a.name)
    if not proj.exists():
        sys.exit(f"项目不存在: {a.name}")
    from . import dubbing
    fn = {"cast": casting.run, "materials": materials.run, "script": screenwriter.run,
          "storyboard": storyboard.run, "generate": director.shoot,
          "review": reviewer.review, "dub": dubbing.run,
          "deliver": producer.deliver}[a.cmd]
    out = fn(proj, force=getattr(a, "force", False))
    if a.cmd == "review" and isinstance(out, dict):
        print(json.dumps({k: out[k] for k in ("passed", "total")}, ensure_ascii=False))
    elif isinstance(out, (dict, list)):
        print(json.dumps(out, ensure_ascii=False, indent=1)[:2000])


if __name__ == "__main__":
    main()
