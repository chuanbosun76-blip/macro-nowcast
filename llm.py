"""大模型层：DeepSeek（OpenAI 兼容）与 Anthropic Claude 双 provider；结构化宏观研判 prompt。"""
from __future__ import annotations

import json
import re
import threading
import time

import httpx

import config

_models_cache = {"ts": 0, "anthropic": []}
_lock = threading.Lock()


# ------------------------------------------------------------------ provider
def provider_of(model: str) -> str:
    return "anthropic" if model and model.startswith("claude") else "deepseek"


def anthropic_models() -> list[str]:
    """自动发现可用的 Claude 模型（Opus/Sonnet 优先，最新在前）。"""
    if not config.ANTHROPIC_API_KEY:
        return []
    if config.ANTHROPIC_MODELS:
        return config.ANTHROPIC_MODELS
    with _lock:
        if time.time() - _models_cache["ts"] < 6 * 3600 and _models_cache["anthropic"]:
            return _models_cache["anthropic"]
        try:
            r = httpx.get(f"{config.ANTHROPIC_BASE_URL}/v1/models", timeout=20,
                          headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"})
            ids = [m["id"] for m in r.json().get("data", []) if isinstance(m, dict) and m.get("id")]
            picked = [i for i in ids if "opus" in i] + [i for i in ids if "sonnet" in i]
            _models_cache.update(ts=time.time(), anthropic=picked[:6])
        except Exception:
            _models_cache.update(ts=time.time(), anthropic=[])
    return _models_cache["anthropic"]


def available_models() -> list[dict]:
    out = []
    if config.DEEPSEEK_API_KEY:
        for m in config.DEEPSEEK_MODELS:
            out.append({"id": m, "provider": "DeepSeek", "label": f"DeepSeek · {m}"})
    for m in anthropic_models():
        out.append({"id": m, "provider": "Anthropic", "label": f"Claude · {m}"})
    return out


def default_model() -> str:
    ms = [m["id"] for m in available_models()]
    if config.DEFAULT_MODEL in ms:
        return config.DEFAULT_MODEL
    return ms[0] if ms else config.DEFAULT_MODEL


def chat(messages, model=None, max_tokens=None, system=None):
    """统一对话接口。messages: [{role, content}]；返回 {content, reasoning, model, latency, tokens}"""
    model = model or default_model()
    max_tokens = max_tokens or config.LLM_MAX_TOKENS
    t0 = time.time()
    if provider_of(model) == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("未配置 ANTHROPIC_API_KEY")
        body = {"model": model, "max_tokens": min(max_tokens, 16000), "messages": [m for m in messages if m["role"] != "system"]}
        sys_txt = system or "\n".join(m["content"] for m in messages if m["role"] == "system")
        if sys_txt:
            body["system"] = sys_txt
        last = None
        for attempt in range(3):
            r = httpx.post(f"{config.ANTHROPIC_BASE_URL}/v1/messages", json=body, timeout=config.LLM_TIMEOUT,
                           headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            if r.status_code in (429, 500, 502, 503, 529):
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Claude HTTP {r.status_code}: {r.text[:300]}")
            j = r.json()
            content = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
            u = j.get("usage") or {}
            return {"content": content, "reasoning": "", "model": j.get("model", model), "latency": time.time() - t0,
                    "tokens": (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)}
        raise RuntimeError(f"Claude 调用失败：{last}")
    # DeepSeek / OpenAI 兼容
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": model, "messages": msgs, "max_tokens": max_tokens, "stream": False}
    headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    last = None
    for attempt in range(3):
        try:
            r = httpx.post(f"{config.DEEPSEEK_BASE_URL}/chat/completions", json=body, headers=headers, timeout=config.LLM_TIMEOUT)
        except httpx.HTTPError as e:
            last = str(e)
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"DeepSeek HTTP {r.status_code}: {r.text[:300]}")
        j = r.json()
        msg = j["choices"][0]["message"]
        return {"content": msg.get("content") or "", "reasoning": (msg.get("reasoning_content") or "")[:4000],
                "model": j.get("model", model), "latency": time.time() - t0, "tokens": (j.get("usage") or {}).get("total_tokens")}
    raise RuntimeError(f"DeepSeek 调用失败：{last}")


# ------------------------------------------------------------------ 研判 prompt
SYSTEM = """你是一名宏观经济研究员，负责对尚未公布的宏观指标做当期即时预测（nowcast）。
要求：以数据为准，先看序列的季节性与近期趋势，再看关联指标与高频线索，最后用研报观点校正方向与幅度；
明确区分"已公布事实"与"预期/观点"；给出可检验的数值、区间与置信度；理由必须可追溯到给定材料。
严格只输出一个 JSON 对象，不要输出任何其他文字。"""

PROMPT = """【任务】预测 {year}年{month}月 的「{name}」（单位：{unit}）。{release}
【指标特性】{theory}

【目标指标历史（最近 {n_hist} 期）】
{history}

【统计模型参考】
- 沿用上期：{persist}
- SARIMAX（{order}，扩展窗口回测相关性 {ar_corr}）：{ar}
{related}
{texts}
{custom}
【输出 JSON 格式】
{{
  "forecast": 数值（{fmt_hint}）,
  "low": 区间下限, "high": 区间上限,
  "direction": "上行" | "下行" | "持平"（相对上期）,
  "confidence": "高" | "中" | "低",
  "summary": "一句话结论（含数值与最关键原因）",
  "drivers": ["驱动因素1（引用具体数据/研报）", "驱动因素2", "驱动因素3"],
  "mechanism": "传导机制与理论依据（2–4 句，说明为什么这些因素会导致该方向和幅度）",
  "evidence": ["引用的研报标题或数据点 1", "..."],
  "risks": ["可能导致预测偏差的风险 1", "风险 2"],
  "vs_models": "与沿用上期/SARIMAX 的差异及原因（1–2 句）"
}}"""


def fmt_val(v, unit):
    if v is None:
        return "—"
    if unit in ("亿元", "亿美元", "千人", "千套"):
        return f"{v:,.1f}{unit}"
    return f"{v:.2f}{unit}" if unit else f"{v:.2f}"


def build_prompt(ind, month, ctx: dict, mode: str, custom: str = "") -> str:
    """ctx: history [(m,v)], persist, ar, order, ar_corr, related [(name, latest_month, value, unit)], titles str, chunks str"""
    y, m = int(month[:4]), int(month[5:7])
    hist = "\n".join(f"{mm}: {fmt_val(v, ind['unit'])}" for mm, v in ctx["history"])
    related = ""
    if ctx.get("related"):
        related = "【关联指标最新值】\n" + "\n".join(f"- {n}（{mm}）：{fmt_val(v, u)}" for n, mm, v, u in ctx["related"]) + "\n"
    texts = ""
    if mode in ("title", "title_ar") and ctx.get("titles"):
        texts = f"【{y}年{m}月内发布的研报标题（按日期）】\n{ctx['titles']}\n"
    elif mode == "chunk" and ctx.get("chunks"):
        texts = f"【{y}年{m}月内研报正文片段】\n{ctx['chunks']}\n"
    if mode == "data":
        texts = "【本次不提供研报文本，仅依据数据与统计模型研判】\n"
    cus = f"【用户附加要求】\n{custom.strip()}\n" if custom and custom.strip() else ""
    fmt_hint = "保留一位小数的百分数数值（不带百分号）" if ind["unit"] == "%" else f"数字本身（单位 {ind['unit']}）"
    ar_txt = fmt_val(ctx.get("ar"), ind["unit"]) if ctx.get("ar") is not None else "不适用"
    if mode == "title_ar" and ctx.get("ar") is not None:
        ar_txt += "（请将其作为重要参考）"
    return PROMPT.format(year=y, month=m, name=ind["name"], unit=ind["unit"] or "指数", release=f"发布规律：{ind['release']}。",
                         theory=ind.get("theory") or "", n_hist=len(ctx["history"]), history=hist,
                         persist=fmt_val(ctx.get("persist"), ind["unit"]), order=ctx.get("order") or "—",
                         ar_corr=("%.2f" % ctx["ar_corr"]) if ctx.get("ar_corr") is not None else "—", ar=ar_txt,
                         related=related, texts=texts, custom=cus, fmt_hint=fmt_hint)


def parse_json(text: str):
    """从模型输出中提取 JSON 对象。"""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", "").replace("%", "").replace("，", "")
    mm = re.search(r"[-−–]?\d+(?:\.\d+)?", s)
    return float(mm.group(0).replace("−", "-").replace("–", "-")) if mm else None


def predict(ind, month, ctx, mode="title", model=None, custom=""):
    prompt = build_prompt(ind, month, ctx, mode, custom)
    res = chat([{"role": "user", "content": prompt}], model=model, system=SYSTEM)
    j = parse_json(res["content"]) or {}
    value = _num(j.get("forecast"))
    analysis = {k: j.get(k) for k in ("direction", "summary", "drivers", "mechanism", "evidence", "risks", "vs_models") if j.get(k) is not None}
    return {"prompt": prompt, "value": value, "low": _num(j.get("low")), "high": _num(j.get("high")),
            "confidence": j.get("confidence"), "reason": j.get("summary") or (res["content"][:300] if value is None else ""),
            "analysis": analysis, "raw": res["content"], "reasoning": res.get("reasoning", ""), "latency": res["latency"],
            "tokens": res["tokens"], "model": res["model"], "error": None if value is not None else "模型未返回可解析的预测值"}
