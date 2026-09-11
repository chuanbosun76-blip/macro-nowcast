"""宏观数据：东方财富数据中心（国家统计局/海关/央行口径）实时抓取 → 失败回退到内置快照。
支持上传 CSV 覆盖（如 Wind 口径）。"""
from __future__ import annotations

import csv
import io
import json
import threading
import time
from datetime import datetime

import httpx

import config
from indicators import BY_ID, INDICATORS, SOURCE_FIELDS

import os

DC_URL = os.environ.get("EM_DC_URL", "https://datacenter-web.eastmoney.com/api/data/v1/get")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://data.eastmoney.com/"}
SNAPSHOT = config.ROOT / "snapshot.json"
CACHE = config.DATA_DIR / "series_cache.json"
OVERRIDE_DIR = config.DATA_DIR / "overrides"
OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_state = {"raw": None, "source": None, "fetched_at": None, "errors": []}


def _fetch_report(rn: str, client: httpx.Client):
    params = {"columns": "ALL", "pageNumber": 1, "pageSize": 500, "sortColumns": "REPORT_DATE", "sortTypes": 1,
              "source": "WEB", "client": "WEB", "reportName": rn}
    r = client.get(DC_URL, params=params)
    r.raise_for_status()
    j = r.json()
    if not j.get("success"):
        raise RuntimeError(f"{rn}: {j.get('message')}")
    rows = []
    fields = SOURCE_FIELDS[rn]
    for d in j["result"]["data"]:
        m = d["REPORT_DATE"][:7]
        row = [m]
        for f in fields:
            if f == "TRADE_BAL_100M_USD":
                ex, im = d.get("EXIT_BASE"), d.get("IMPORT_BASE")
                row.append(round((ex - im) / 1e5, 2) if ex is not None and im is not None else None)  # 千美元→亿美元
            else:
                row.append(d.get(f))
        rows.append(row)
    return {"fields": fields, "rows": rows}


def fetch_live():
    out, errors = {}, []
    with httpx.Client(timeout=config.HTTP_TIMEOUT, headers=UA, follow_redirects=True) as c:
        for rn in SOURCE_FIELDS:
            try:
                out[rn] = _fetch_report(rn, c)
            except Exception as e:  # noqa
                errors.append(f"{rn}: {e}")
    return out, errors


def load(force_live: bool = False):
    """返回原始表字典。优先顺序：实时抓取（force 或缓存过期）→ 本地缓存 → 内置快照。"""
    with _lock:
        now = time.time()
        cache_ok = CACHE.exists() and now - CACHE.stat().st_mtime < config.REFRESH_HOURS * 3600
        raw, source, errors = None, None, []
        if not config.OFFLINE and (force_live or not cache_ok):
            live, errors = fetch_live()
            if live:
                base = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
                if CACHE.exists():
                    try:
                        base.update(json.loads(CACHE.read_text(encoding="utf-8")))
                    except Exception:
                        pass
                base.update(live)
                raw = base
                source = "东方财富数据中心（实时）" + ("" if not errors else "，部分表回退缓存")
                CACHE.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        if raw is None and CACHE.exists():
            raw = json.loads(CACHE.read_text(encoding="utf-8"))
            source = "本地缓存（东方财富）"
        if raw is None:
            raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
            source = "内置快照（东方财富，2026-09-11 抓取）"
        _state.update(raw=raw, source=source, errors=errors,
                      fetched_at=datetime.fromtimestamp(CACHE.stat().st_mtime if CACHE.exists() else SNAPSHOT.stat().st_mtime).strftime("%Y-%m-%d %H:%M"))
        return raw


def _next_month(m: str) -> str:
    y, mm = int(m[:4]), int(m[5:7])
    return f"{y + (mm == 12)}-{1 if mm == 12 else mm + 1:02d}"


def month_range(a: str, b: str):
    out = []
    while a <= b:
        out.append(a)
        a = _next_month(a)
    return out


def build_series(ind_id: str, raw=None):
    """清洗为连续月度序列：{"months": [...], "values": [...], "notes": [...]}。
    1–2 月合并发布的指标剔除 1 月（2 月值即 1–2 月合并值）；个别缺失月线性插值。"""
    raw = raw or _state["raw"] or load()
    ind = BY_ID[ind_id]
    tbl = raw[ind["source"]]
    fi = tbl["fields"].index(ind["field"])
    fb = tbl["fields"].index(ind["fallback"]) if ind.get("fallback") in tbl["fields"] else None
    data = {}
    for row in tbl["rows"]:
        v = row[1 + fi]
        if v is None and fb is not None:
            v = row[1 + fb]
        if v is not None:
            data[row[0]] = float(v)
    # CSV 覆盖
    ov = OVERRIDE_DIR / f"{ind_id}.csv"
    notes = []
    if ov.exists():
        for m, v in read_override(ov).items():
            data[m] = v
        notes.append("已使用上传 CSV 覆盖部分数据")
    if not data:
        return {"months": [], "values": [], "notes": ["无数据"]}
    months_all = month_range(min(data), max(data))
    months, values = [], []
    for m in months_all:
        if ind["jan_merge"] and m.endswith("-01"):
            continue
        months.append(m)
        values.append(data.get(m))
    # 插值
    filled = 0
    for i, v in enumerate(values):
        if v is None:
            prev = next((values[j] for j in range(i - 1, -1, -1) if values[j] is not None), None)
            nxt = next((values[j] for j in range(i + 1, len(values)) if values[j] is not None), None)
            values[i] = prev if nxt is None else (nxt if prev is None else (prev + nxt) / 2)
            filled += 1
    if filled:
        notes.append(f"{filled} 个缺失月已线性插值")
    if ind["jan_merge"]:
        notes.append("1–2 月合并发布：剔除 1 月，2 月值即 1–2 月合并值")
    return {"months": months, "values": values, "notes": notes}


def read_override(path) -> dict:
    out = {}
    text = path.read_text(encoding="utf-8-sig") if hasattr(path, "read_text") else path
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        m, v = row[0].strip(), row[1].strip().replace(",", "")
        if len(m) >= 7 and m[:4].isdigit():
            m = m[:7].replace("/", "-")
            if len(m) == 6:  # 2024-1
                m = m[:5] + "0" + m[5]
            try:
                out[m] = float(v)
            except ValueError:
                pass
    return out


def save_override(ind_id: str, text: str) -> int:
    parsed = read_override(text)
    if not parsed:
        raise ValueError("CSV 中未解析到有效行（格式：月份,数值，例如 2025-05,4.8）")
    (OVERRIDE_DIR / f"{ind_id}.csv").write_text(text, encoding="utf-8")
    return len(parsed)


def clear_override(ind_id: str):
    p = OVERRIDE_DIR / f"{ind_id}.csv"
    if p.exists():
        p.unlink()


def status():
    return {"source": _state["source"], "fetched_at": _state["fetched_at"], "errors": _state["errors"]}
