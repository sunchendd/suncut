"""资产库 —— 道具/场地 的跨项目复用库(桌面 短剧资产库/,零依赖 JSON 存储).

每个资产一个 .json 文件:
  场地: {"id","name_cn","dna_en","light_cn","tags",...}
  道具: {"id","name_cn","desc_en","tags",...}
服化道 agent 产出后自动归档入库(harvest),新项目可先从库里挑再补缺。
"""
import hashlib
import json
import re
import time
from pathlib import Path

from . import config

KINDS = {"scene": "场地", "prop": "道具"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
NAME_RE = re.compile(r"^[\w\u4e00-\u9fff·()()-]{1,24}$")


def _dir(kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError(f"未知资产类型: {kind}(可选 {list(KINDS)})")
    d = config.ASSET_LIB / KINDS[kind]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(name_cn: str) -> str:
    # 确定性 id:名字哈希前 10 位,重跑/重启不漂移
    h = hashlib.md5(name_cn.encode()).hexdigest()[:10]
    return f"a{h}"


def list_assets(kind: str):
    out = []
    for f in sorted(_dir(kind).glob("*.json")):
        try:
            d = json.loads(f.read_text())
            d.setdefault("id", f.stem)
            out.append(d)
        except Exception:
            continue
    out.sort(key=lambda a: a.get("updated") or a.get("created") or "", reverse=True)
    return out


def get(kind: str, asset_id: str):
    f = _dir(kind) / f"{asset_id}.json"
    return json.loads(f.read_text()) if f.exists() else None


def find_by_name(kind: str, name_cn: str):
    return next((a for a in list_assets(kind) if a.get("name_cn") == name_cn), None)


def save(kind: str, asset: dict):
    """新增/更新(按 id 或 name_cn 去重);返回规范化后的资产."""
    if kind not in KINDS:
        raise ValueError(f"未知资产类型: {kind}")
    a = dict(asset or {})
    name = (a.get("name_cn") or "").strip()
    if not NAME_RE.match(name or ""):
        raise ValueError("name_cn 必填(1-24 字,中英文/数字)")
    if kind == "scene" and not (a.get("dna_en") or "").strip():
        raise ValueError("场地必须给 dna_en(封闭英文场景DNA,含点光源)")
    if kind == "prop" and not (a.get("desc_en") or "").strip():
        raise ValueError("道具必须给 desc_en(英文一句描述)")
    a["name_cn"] = name
    a["id"] = a.get("id") or _slug(name)
    if not ID_RE.match(a["id"]):
        raise ValueError("id 只能是小写字母/数字/连字符(2-40)")
    a["tags"] = [t for t in (a.get("tags") or []) if str(t).strip()][:6]
    a["updated"] = time.strftime("%F %T")
    a.setdefault("created", a["updated"])
    _dir(kind).joinpath(f"{a['id']}.json").write_text(
        json.dumps(a, ensure_ascii=False, indent=1))
    return a


def remove(kind: str, asset_id: str):
    f = _dir(kind) / f"{asset_id}.json"
    if not ID_RE.match(asset_id or "") or not f.exists():
        raise KeyError(f"资产不存在: {kind}/{asset_id}")
    f.unlink()
    return True


def harvest(materials: dict, source: str = ""):
    """服化道产出自动归档: 新场景/新道具入库(按 name_cn 去重);返回入库清单."""
    made = {"scenes": [], "props": []}
    for s in materials.get("scenes", []):
        name = (s.get("name_cn") or "").strip()
        if not name or find_by_name("scene", name):
            continue
        try:
            made["scenes"].append(save("scene", {
                "name_cn": name, "dna_en": s.get("dna_en", ""),
                "light_cn": s.get("light_cn", ""), "tags": s.get("tags", []),
                "source": source}))
        except ValueError:
            continue
    for p in materials.get("props", []):
        name = (p.get("name_cn") or "").strip()
        if not name or find_by_name("prop", name):
            continue
        try:
            made["props"].append(save("prop", {
                "name_cn": name, "desc_en": p.get("desc_en", ""),
                "tags": p.get("tags", []), "source": source}))
        except ValueError:
            continue
    return made
