"""研报文本：东方财富研报中心（宏观研究 qType=3、策略报告 qType=2），带直达链接；支持自定义召回规则。"""
from __future__ import annotations

import calendar
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx

import config
import store
from indicators import BY_ID

LIST_URL = os.environ.get("EM_REPORT_API", "https://reportapi.eastmoney.com/report/jg")
DETAIL_BASE = os.environ.get("EM_DETAIL_BASE", "https://data.eastmoney.com/report")
DETAIL_PAGE = {3: "zw_macresearch.jshtml", 2: "zw_strategy.jshtml", 1: "zw_industry.jshtml", 0: "zw_stock.jshtml"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://data.eastmoney.com/report/"}
QTYPES = {3: "宏观研究", 2: "策略报告"}
MAX_PAGES = 12
NOISE = re.compile(r"资料来源|数据来源|来源[:：]|风险提示|免责声明|请务必阅读|证书编号|执业|SAC|分析师|联系人|图表\s*\d|图\s*\d|表\s*\d|单位[:：]|Wind|iFinD|UN Comtrade")
US_HINT = re.compile(r"美国|美联储|非农|美债|海外|全球|联储|FOMC|美股|美元")


def report_url(it) -> str:
    return f"{DETAIL_BASE}/{DETAIL_PAGE.get(it.get('qtype', 3), DETAIL_PAGE[3])}?encodeUrl={it.get('encodeUrl', '')}"


def month_bounds(month: str, cutoff: str | None = None):
    y, m = int(month[:4]), int(month[5:7])
    b, e = f"{month}-01", f"{month}-{calendar.monthrange(y, m)[1]:02d}"
    if cutoff and cutoff < e:
        e = cutoff
    return b, e


def _fetch_list(qtype: int, begin: str, end: str, client: httpx.Client):
    items = []
    for page in range(1, MAX_PAGES + 1):
        params = {"pageSize": 100, "beginTime": begin, "endTime": end, "pageNo": page, "fields": "", "qType": qtype,
                  "orgCode": "", "author": "", "p": page, "pageNum": page}
        r = client.get(LIST_URL, params=params)
        r.raise_for_status()
        j = r.json()
        data = j.get("data") or []
        for d in data:
            items.append({"title": (d.get("title") or "").strip(), "org": d.get("orgSName") or "",
                          "date": (d.get("publishDate") or "")[:10], "encodeUrl": d.get("encodeUrl"), "qtype": qtype,
                          "researcher": d.get("researcher") or ""})
        if page >= int(j.get("TotalPage") or 1) or not data:
            break
    return items


def fetch_month(month: str, cutoff: str | None = None):
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
    for it in items:
        it["url"] = report_url(it)
    store.cache_set(key, items)
    return items


def _norm(t):
    return re.sub(r"[\s\W_]+", "", t).lower()


def rules():
    """用户自定义召回规则（设置页）：{"include": [...], "exclude": [...], "orgs": [...], "limit": 150}"""
    r = store.get_setting("recall_rules") or {}
    return {"include": [x for x in r.get("include", []) if x], "exclude": [x for x in r.get("exclude", []) if x],
            "orgs": [x for x in r.get("orgs", []) if x], "limit": int(r.get("limit") or 150)}


def select_titles(items, ind_id: str, limit: int | None = None):
    """关键词召回 + 去重 + 用户规则。美国指标额外要求标题含海外/美国类线索。"""
    ind = BY_ID[ind_id]
    ru = rules()
    kws = list(ind["keywords"]) + ru["include"]
    limit = limit or ru["limit"]
    seen, hit, other = set(), [], []
    for it in sorted(items, key=lambda x: x["date"]):
        n = _norm(it["title"])
        if not n or n in seen:
            continue
        seen.add(n)
        t = it["title"]
        if ru["exclude"] and any(x.lower() in t.lower() for x in ru["exclude"]):
            continue
        if ru["orgs"] and not any(o in (it.get("org") or "") for o in ru["orgs"]):
            continue
        if ind["country"] == "US" and not US_HINT.search(t):
            continue
        if any(k.lower() in t.lower() for k in kws):
            hit.append(it)
        elif it["qtype"] == 3:
            other.append(it)
    supplemented = 0
    if len(hit) < 10:
        extra = other[-(40 - len(hit)):] if other else []
        supplemented = len(extra)
        hit = sorted(hit + extra, key=lambda x: x["date"])
    if len(hit) > limit:
        hit = hit[-limit:]
    for it in hit:
        it.setdefault("url", report_url(it))
    return hit, supplemented


def format_titles(sel):
    return "\n".join(f"{it['date']} {it['org']}：{it['title']}" for it in sel)


def _fetch_detail(it, client):
    key = f"zw:{it['encodeUrl']}"
    cached = store.cache_get(key, None)
    if cached is not None:
        return cached
    r = client.get(report_url(it))
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
    out = []
    for p in re.findall(r"<p[^>]*>(.*?)</p>", seg, flags=re.S):
        t = html.unescape(re.sub(r"<[^>]+>", "", p)).replace("　", "").strip()
        if t:
            out.append(t)
    return out


def select_chunks(sel, ind_id: str, max_reports: int = 14, max_chars: int = 6000):
    kws = BY_ID[ind_id]["keywords"]
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
