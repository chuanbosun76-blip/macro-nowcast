"""研报文本：东方财富研报中心（宏观研究 qType=3、策略报告 qType=2）。
替代原文朝阳永续向量库：按目标指标关键词召回当月研报标题；正文片段取研报摘要中含关键词的段落，
并按原文建议做去重与来源/表头过滤。"""
from __future__ import annotations

import calendar
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx

import config, store
from indicators import BY_ID

import os

LIST_URL = os.environ.get("EM_REPORT_API", "https://reportapi.eastmoney.com/report/jg")
_DETAIL_BASE = os.environ.get("EM_DETAIL_BASE", "https://data.eastmoney.com/report")
DETAIL_URL = {3: _DETAIL_BASE + "/zw_macresearch.jshtml?encodeUrl={}",
              2: _DETAIL_BASE + "/zw_strategy.jshtml?encodeUrl={}"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://data.eastmoney.com/report/"}
QTYPES = {3: "宏观研究", 2: "策略报告"}
MAX_PAGES = 12
NOISE = re.compile(r"资料来源|数据来源|来源[:：]|风险提示|免责声明|请务必阅读|证书编号|执业|SAC|分析师|联系人|图表\s*\d|图\s*\d|表\s*\d|单位[:：]|Wind|iFinD|UN Comtrade")


def month_bounds(month: str, cutoff: str | None = None):
    y, m = int(month[:4]), int(month[5:7])
    b = f"{month}-01"
    e = f"{month}-{calendar.monthrange(y, m)[1]:02d}"
    if cutoff and cutoff < e:
        e = cutoff
    return b, e


def _fetch_list(qtype: int, begin: str, end: str, client: httpx.Client):
    items = []
    for page in range(1, MAX_PAGES + 1):
        params = {"pageSize": 100, "beginTime": begin, "endTime": end, "pageNo": page, "fields": "",
                  "qType": qtype, "orgCode": "", "author": "", "p": page, "pageNum": page}
        r = client.get(LIST_URL, params=params)
        r.raise_for_status()
        j = r.json()
        data = j.get("data") or []
        for d in data:
            items.append({"title": (d.get("title") or "").strip(), "org": d.get("orgSName") or "",
                          "date": (d.get("publishDate") or "")[:10], "encodeUrl": d.get("encodeUrl"),
                          "qtype": qtype, "researcher": d.get("researcher") or ""})
        if page >= int(j.get("TotalPage") or 1) or not data:
            break
    return items


def fetch_month(month: str, cutoff: str | None = None):
    """当月全部宏观+策略研报（标题级）。已结束的月份永久缓存；当月缓存 2 小时。"""
    today = date.today().isoformat()
    begin, end = month_bounds(month, cutoff)
    finished = end < today and cutoff is None
    key = f"list:{month}:{end}"
    cached = store.cache_get(key, None if finished else 7200)
    if cached is not None:
        return cached
    if config.OFFLINE:
        return []
    items = []
    with httpx.Client(timeout=config.HTTP_TIMEOUT, headers=UA, follow_redirects=True) as c:
        for q in QTYPES:
            items.extend(_fetch_list(q, begin, end, c))
    store.cache_set(key, items)
    return items


def _norm(t: str) -> str:
    return re.sub(r"[\s\W_]+", "", t).lower()


def select_titles(items, ind_id: str, limit: int = 150):
    """关键词召回 + 标题去重。命中不足 10 条时补充当月宏观研究标题。"""
    kws = BY_ID[ind_id]["keywords"]
    seen, hit, other = set(), [], []
    for it in sorted(items, key=lambda x: x["date"]):
        n = _norm(it["title"])
        if not n or n in seen:
            continue
        seen.add(n)
        if any(k.lower() in it["title"].lower() for k in kws):
            hit.append(it)
        elif it["qtype"] == 3:
            other.append(it)
    supplemented = 0
    if len(hit) < 10:
        extra = other[-(40 - len(hit)):] if other else []
        supplemented = len(extra)
        hit = sorted(hit + extra, key=lambda x: x["date"])
    if len(hit) > limit:
        hit = hit[-limit:]  # 取临近月末的
    return hit, supplemented


def format_titles(sel):
    return "\n".join(f"{it['date']} {it['org']}：{it['title']}" for it in sel)


def _fetch_detail(it, client):
    key = f"zw:{it['encodeUrl']}"
    cached = store.cache_get(key, None)
    if cached is not None:
        return cached
    url = DETAIL_URL.get(it["qtype"], DETAIL_URL[3]).format(it["encodeUrl"])
    r = client.get(url)
    r.raise_for_status()
    text = parse_detail(r.text)
    store.cache_set(key, text)
    return text


def parse_detail(page: str):
    i = page.find('id="ctx-content"')
    if i < 0:
        return []
    j = page.find("</div>", i)
    seg = page[i:j if j > 0 else i + 20000]
    paras = re.findall(r"<p[^>]*>(.*?)</p>", seg, flags=re.S)
    out = []
    for p in paras:
        t = html.unescape(re.sub(r"<[^>]+>", "", p)).replace("　", "").strip()
        if t:
            out.append(t)
    return out


def select_chunks(sel, ind_id: str, max_reports: int = 14, max_chars: int = 6000):
    """正文片段：抓取召回研报摘要，保留含关键词的段落；过滤资料来源/表头/免责声明，按前缀去重。"""
    kws = BY_ID[ind_id]["keywords"]
    # 优先标题直接命中关键词的研报，近月末优先
    cand = [it for it in sel if any(k.lower() in it["title"].lower() for k in kws)][-max_reports:]
    if config.OFFLINE or not cand:
        return [], 0
    with httpx.Client(timeout=config.HTTP_TIMEOUT, headers=UA, follow_redirects=True) as c:
        with ThreadPoolExecutor(6) as ex:
            texts = list(ex.map(lambda it: _safe(lambda: _fetch_detail(it, c), []), cand))
    chunks, seen, total, dropped = [], set(), 0, 0
    for it, paras in zip(cand, texts):
        kept = 0
        for p in paras:
            if not any(k.lower() in p.lower() for k in kws):
                continue
            if NOISE.search(p) or len(p) < 20:
                dropped += 1
                continue
            key = _norm(p)[:40]
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            frag = p[:300]
            chunks.append(f"[{it['date']} {it['org']}] {frag}")
            total += len(frag)
            kept += 1
            if kept >= 3 or total >= max_chars:
                break
        if total >= max_chars:
            break
    return chunks, dropped


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default
