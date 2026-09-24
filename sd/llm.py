"""智谱 GLM 客户端 —— 零依赖(urllib)实现 chat / vision / JSON 抽取."""
import base64
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from . import config


class LLMError(RuntimeError):
    pass


def _post(body, timeout=600):
    req = urllib.request.Request(
        config.LLM_BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {config.zhipu_key()}",
                 "Content-Type": "application/json"})
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:300]}"
        except Exception as e:
            last = str(e)
        time.sleep(3 * (i + 1))
    raise LLMError(f"LLM 请求失败: {last}")


def chat(model, system, user, max_tokens=16384, temperature=0.7):
    """文本对话。GLM-5.x 是推理模型,优先关思考;空回复自动升 max_tokens 重试一次."""
    body = {"model": model, "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user}],
        "max_tokens": max_tokens, "temperature": temperature}
    if model.startswith("glm-5"):
        body["thinking"] = {"type": "disabled"}
    try:
        d = _post(body)
    except LLMError:
        body.pop("thinking", None)   # 个别端点不认 thinking 参数
        d = _post(body)
    msg = d["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    if not content:
        if d["choices"][0].get("finish_reason") == "length":
            body["max_tokens"] = max_tokens * 2
            d = _post(body)
            content = (d["choices"][0]["message"].get("content") or "").strip()
        if not content:
            raise LLMError(f"空回复: reasoning={(msg.get('reasoning_content') or '')[:200]}")
    return content


def chat_json(model, system, user, max_tokens=16384, temperature=0.7, retries=2):
    """chat + extract_json,失败把错误反馈给模型重试(带上它的原输出)."""
    last_err = None
    prompt = user
    for _ in range(retries + 1):
        out = chat(model, system, prompt, max_tokens=max_tokens, temperature=temperature)
        try:
            return extract_json(out)
        except (LLMError, json.JSONDecodeError) as e:
            last_err = e
            prompt = (f"{user}\n\n【你上次的输出无法解析: {e}】\n"
                      f"上次输出开头: {out[:400]}\n请重新输出,**只输出合法 JSON**,不要任何其他文字。")
    raise LLMError(f"JSON 解析重试 {retries} 次仍失败: {last_err}")


def _shrink_b64(path, maxdim=768):
    """ffmpeg 缩图转 jpeg base64(系统 python 无 PIL)."""
    out = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False).name
    vf = (f"scale='if(gt(iw,ih),min({maxdim},iw),-2)':"
          f"'if(gt(iw,ih),-2,min({maxdim},ih))'")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                        "-vf", vf, "-q:v", "4", out], capture_output=True, text=True)
    if r.returncode != 0:
        raise LLMError(f"缩图失败 {path}: {r.stderr[:200]}")
    return base64.b64encode(open(out, "rb").read()).decode()


def vision(text, image_paths, max_tokens=4000):
    """视觉理解: 多图 + 文本 -> 回复."""
    content = [{"type": "text", "text": text}]
    for p in image_paths:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + _shrink_b64(p)}})
    body = {"model": config.LLM_VISION,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens}
    d = _post(body)
    content_out = (d["choices"][0]["message"].get("content") or "").strip()
    if not content_out:
        raise LLMError("vision 空回复")
    return content_out


def extract_json(text):
    """从模型回复中抽取第一个完整 JSON 对象/数组(容忍 ```围栏与前后废话)."""
    t = text.strip()
    if "```" in t:
        for seg in t.split("```"):
            seg = seg.strip().removeprefix("json").strip()
            if seg and seg[:1] in "[{":
                t = seg
                break
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        raise LLMError("回复中没有 JSON: " + text[:200])
    start = min(starts)
    depth, instr, esc = 0, False, False
    for i in range(start, len(t)):
        c = t[i]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
            continue
        if c == '"':
            instr = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return json.loads(t[start:i + 1])
    raise LLMError("JSON 未闭合: " + text[:200])
