"""DeepSeek 调用：沿用原文 Prompt（研报标题预测），扩展正文片段与自回归参考两种输入。"""
from __future__ import annotations

import re
import time

import httpx

import config

TITLE_PROMPT = """你的任务是根据{year}年{month}月内的宏观研究报告标题，预测{year}年{month}月的{target_var},并严格按照规定格式输出结果。以下是你需要遵循的步骤:
1、仔细阅读所有的研究报告标题(<标题>)，进行全量语义分析，注意分析标题内含的宏观观点对于目标预测指标的影响方向，以及观点的情感程度，不要有任何跳过。
2、在回答问题时，请先在<思考>标签内详细阐述你思考如何回答这个问题的过程，包括你考虑的要点、可能的推理方向等。然后在<回答>标签内给出针对问题的最终答案。
3、<回答>输出你预测的{year}年{month}月的{target_var},只要数值,格式是{fmt_hint}，结束以</回答>表示
4、<理由>输出你预测的{year}年{month}月的{target_var}的预测理由，只要文本，尽量精简，结束以</理由>表示{ar_step}
<标题>
{combined}
</标题>
请开始你的任务。
"""

CHUNK_PROMPT = """你的任务是根据{year}年{month}月内的宏观研究报告正文片段，预测{year}年{month}月的{target_var},并严格按照规定格式输出结果。以下是你需要遵循的步骤:
1、仔细阅读所有的研究报告正文片段(<正文片段>)，进行全量语义分析，注意分析片段内含的宏观观点与数据对于目标预测指标的影响方向，以及观点的情感程度，不要有任何跳过；注意片段可能存在重复引用或与目标指标无关的内容，需自行甄别。
2、在回答问题时，请先在<思考>标签内详细阐述你思考如何回答这个问题的过程，包括你考虑的要点、可能的推理方向等。然后在<回答>标签内给出针对问题的最终答案。
3、<回答>输出你预测的{year}年{month}月的{target_var},只要数值,格式是{fmt_hint}，结束以</回答>表示
4、<理由>输出你预测的{year}年{month}月的{target_var}的预测理由，只要文本，尽量精简，结束以</理由>表示{ar_step}
<正文片段>
{combined}
</正文片段>
请开始你的任务。
"""

AR_STEP = "\n5、附加参考：基于截至上月末历史数据的自回归（SARIMAX）模型，对{year}年{month}月{target_var}的预测值为{ar_value}。该值仅供参考，请结合文本信息独立判断。"


def target_var(ind) -> str:
    return f"{ind['name']}（单位：{ind['unit']}）"


def fmt_hint(ind) -> str:
    return "小数点一位的小数加百分号" if ind["unit"] == "%" else f"数字本身（单位：{ind['unit']}）"


def build_prompt(ind, month: str, mode: str, combined: str, ar_value: float | None = None) -> str:
    y, m = int(month[:4]), int(month[5:7])
    tv = target_var(ind)
    ar_step = ""
    if mode.endswith("_ar") and ar_value is not None:
        v = f"{ar_value:.1f}%" if ind["unit"] == "%" else f"{ar_value:,.1f}{ind['unit']}"
        ar_step = AR_STEP.format(year=y, month=m, target_var=tv, ar_value=v)
    tpl = CHUNK_PROMPT if mode.startswith("chunk") else TITLE_PROMPT
    return tpl.format(year=y, month=m, target_var=tv, fmt_hint=fmt_hint(ind), ar_step=ar_step, combined=combined)


def _tag(text, tag):
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, flags=re.S)
    if m:
        return m.group(1).strip()
    m = re.search(rf"<{tag}>\s*(.*)", text, flags=re.S)  # 缺少闭合标签
    return m.group(1).strip()[:2000] if m else None


def parse_answer(content: str, unit: str):
    ans = _tag(content, "回答")
    reason = _tag(content, "理由")
    thinking = _tag(content, "思考")
    value = None
    src = ans if ans is not None else content[-200:]
    if src:
        s = src.replace(",", "").replace("，", "")
        m = re.search(r"[-−–]?\d+(?:\.\d+)?", s)
        if m:
            value = float(m.group(0).replace("−", "-").replace("–", "-"))
            if unit == "亿元" and "万亿" in s:
                value *= 10000
            if unit == "亿美元" and "万亿" in s:
                value *= 10000
    if reason and "</" in reason:
        reason = reason.split("</")[0]
    return value, ans, reason, thinking


def call_deepseek(prompt: str, model: str | None = None):
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    model = model or config.DEEPSEEK_MODEL
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": config.DEEPSEEK_MAX_TOKENS,
            "stream": False}
    headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    last = None
    for attempt in range(3):
        t0 = time.time()
        try:
            r = httpx.post(f"{config.DEEPSEEK_BASE_URL}/chat/completions", json=body, headers=headers,
                           timeout=config.DEEPSEEK_TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"DeepSeek HTTP {r.status_code}: {r.text[:300]}")
            j = r.json()
            msg = j["choices"][0]["message"]
            return {"content": msg.get("content") or "", "reasoning": msg.get("reasoning_content") or "",
                    "latency": time.time() - t0, "tokens": (j.get("usage") or {}).get("total_tokens"),
                    "model": j.get("model", model), "finish": j["choices"][0].get("finish_reason")}
        except httpx.HTTPError as e:
            last = str(e)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"DeepSeek 调用失败：{last}")
