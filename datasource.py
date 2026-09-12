"""数据层：中国（东方财富数据中心，国家统计局/海关/央行口径）+ 美国（FRED，美联储圣路易斯分行）。
实时抓取 → 本地缓存 → 内置快照 三级回退；支持 iFinD EDB 覆盖与上传 CSV 覆盖。"""
from __future__ import annotations

import csv
import io
import json
import os
import threading
import time
from datetime import datetime

import httpx

import config
import ifind
from indicators import BY_ID, EM_FIELDS, INDICATORS

DC_URL = os.environ.get("EM_DC_URL", "https://datacenter-web.eastmoney.com/api/data/v1/get")
FRED_CSV = os.environ.get("FRED_CSV_URL", "https://fred.stlouisfed.org/graph/fredgraph.csv")
FRED_API = os.environ.get("FRED_API_URL", "https://api.stlouisfed.org/fred/series/observations")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://data.eastmoney.com/"}
SNAPSHOT_CN = config.ROOT / "snapshot_cn.json"
SNAPSHOT_US = config.ROOT / "snapshot_us.json"
CACHE = config.DATA_DIR / "series_cache_v2.json"
IFIND_CACHE = config.DATA_DIR / "ifind_cache.json"
OVERRIDE_DIR = config.DATA_DIR / "overrides"
OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_state = {"raw": None, "source": {}, "fetched_at": None, "errors": [], "ifind": {}}


# ------------------------------------------------------------------ 东方财富
def _em_table(rn: str, client: httpx.Client):
    params = {"columns": "ALL", "pageNumber": 1, "pageSize": 500, "sortColumns": "REPORT_DATE", "sortTypes": 1,
              "source": "WEB", "client": "WEB", "reportName": rn}
    r = client.get(DC_URL, params=params)
    r.raise_for_status()
    j = r.json()
    if not j.get("success"):
        raise RuntimeError(f"{rn}: {j.get('message')}")
    fields = EM_FIELDS[rn]
    rows = []
    for d in j["result"]["data"]:
        row = [d["REPORT_DATE"][:7]]
        for f in fields:
            if f == "TRADE_BAL_100M_USD":
                ex, im = d.get("EXIT_BASE"), d.get("IMPORT_BASE")
                row.append(round((ex - im) / 1e5, 2) if ex is not None and im is not None else None)
            else:
                row.append(d.get(f))
        rows.append(row)
    return {"fields": fields, "rows": rows}


def _em_house(client: httpx.Client):
    """70 城新建商品住宅价格指数（同比）按月取均值 → 同比%（指数 100 为基）。"""
    out = {}
    for page in range(1, 8):
        params = {"columns": "REPORT_DATE,CITY,FIRST_COMHOUSE_SAME", "pageNumber": page, "pageSize": 2000,
                  "sortColumns": "REPORT_DATE", "sortTypes": -1, "source": "WEB", "client": "WEB",
                  "reportName": "RPT_ECONOMY_HOUSE_PRICE"}
        r = client.get(DC_URL, params=params)
        r.raise_for_status()
        j = r.json()
        data = (j.get("result") or {}).get("data") or []
        if not data:
            break
        for d in data:
            v = d.get("FIRST_COMHOUSE_SAME")
            if v is None:
                continue
            out.setdefault(d["REPORT_DATE"][:7], []).append(float(v) - 100.0)
        if len(data) < 2000:
            break
    rows = [[m, round(sum(v) / len(v), 2)] for m, v in sorted(out.items()) if len(v) >= 30]
    return {"fields": ["FIRST_COMHOUSE_SAME"], "rows": rows}


def fetch_cn():
    out, errors = {}, []
    with httpx.Client(timeout=config.HTTP_TIMEOUT, headers=UA, follow_redirects=True) as c:
        for rn in EM_FIELDS:
            try:
                out[rn] = _em_table(rn, c)
            except Exception as e:  # noqa
                errors.append(f"{rn}: {e}")
        try:
            out["EM_HOUSE70"] = _em_house(c)
        except Exception as e:  # noqa
            errors.append(f"HOUSE70: {e}")
    return out, errors


# ------------------------------------------------------------------ FRED
def _fred_series(sid: str, client: httpx.Client) -> dict[str, float]:
    """返回 {日期: 值}（原频率）。优先 API（若配置 key），否则 fredgraph.csv。"""
    if config.FRED_API_KEY:
        r = client.get(FRED_API, params={"series_id": sid, "api_key": config.FRED_API_KEY, "file_type": "json",
                                         "observation_start": "2005-01-01"})
        r.raise_for_status()
        obs = r.json().get("observations") or []
        return {o["date"]: float(o["value"]) for o in obs if o.get("value") not in (None, ".", "")}
    r = client.get(FRED_CSV, params={"id": sid})
    r.raise_for_status()
    out = {}
    for row in csv.reader(io.StringIO(r.text)):
        if len(row) < 2 or not row[0][:4].isdigit():
            continue
        try:
            out[row[0]] = float(row[1])
        except ValueError:
            pass
    return out


def fetch_us():
    out, errors = {}, []
    sids = sorted({i["source"]["fred"] for i in INDICATORS if "fred" in i["source"]})
    with httpx.Client(timeout=config.HTTP_TIMEOUT, headers={"User-Agent": UA["User-Agent"]}, follow_redirects=True) as c:
        for sid in sids:
            try:
                out[sid] = _fred_series(sid, c)
            except Exception as e:  # noqa
                errors.append(f"FRED {sid}: {e}")
    return out, errors


# ------------------------------------------------------------------ 加载
def _read(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def load(force_live: bool = False):
    with _lock:
        now = time.time()
        cache = _read(CACHE)
        cache_ok = bool(cache) and now - CACHE.stat().st_mtime < config.REFRESH_HOURS * 3600
        raw = {"cn": _read(SNAPSHOT_CN), "us": _read(SNAPSHOT_US)}
        raw["cn"].update(cache.get("cn") or {})
        raw["us"].update(cache.get("us") or {})
        source = {"cn": "内置快照" if not cache.get("cn") else "本地缓存", "us": "内置快照" if not cache.get("us") else "本地缓存"}
        errors = []
        if not config.OFFLINE and (force_live or not cache_ok):
            cn, e1 = fetch_cn()
            us, e2 = fetch_us()
            errors = e1 + e2
            if cn:
                raw["cn"].update(cn)
                source["cn"] = "东方财富数据中心（实时）" + ("，部分表回退" if e1 else "")
            if us:
                raw["us"].update(us)
                source["us"] = "FRED（实时）" + ("，部分序列回退" if e2 else "")
            if cn or us:
                CACHE.write_text(json.dumps({"cn": raw["cn"], "us": raw["us"]}, ensure_ascii=False), encoding="utf-8")
        # iFinD EDB 覆盖
        if ifind.enabled() and not config.OFFLINE:
            try:
                ser = ifind.load_all()
                if ser:
                    _state["ifind"] = ser
                    IFIND_CACHE.write_text(json.dumps(ser, ensure_ascii=False), encoding="utf-8")
                    source["cn"] = f"iFinD EDB（{len(ser)} 项）+ " + source["cn"]
            except Exception as e:  # noqa
                errors.append(f"iFinD: {e}")
                if not _state["ifind"]:
                    _state["ifind"] = _read(IFIND_CACHE)
        ts = CACHE.stat().st_mtime if CACHE.exists() else time.time()
        _state.update(raw=raw, source=source, errors=errors, fetched_at=datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"))
        return raw


# ------------------------------------------------------------------ 序列构建
def _next_month(m):
    y, mm = int(m[:4]), int(m[5:7])
    return f"{y + (mm == 12)}-{1 if mm == 12 else mm + 1:02d}"


def month_range(a, b):
    out = []
    while a <= b:
        out.append(a)
        a = _next_month(a)
    return out


def _monthly_from_fred(ser: dict[str, float], agg="last") -> dict[str, float]:
    """任意频率 → 月度（周/日频取均值或期末）。季度序列的日期为季度首日，映射到季末月。"""
    buckets = {}
    for d, v in ser.items():
        buckets.setdefault(d[:7], []).append(v)
    out = {}
    for m, vs in buckets.items():
        out[m] = sum(vs) / len(vs) if agg == "mean" else vs[-1]
    return out


def _transform(ser: dict[str, float], how: str, freq="M", scale=1.0):
    months = sorted(ser)
    out = {}
    if how == "level":
        out = {m: ser[m] * scale for m in months}
    elif how == "yoy":
        for m in months:
            prev = f"{int(m[:4]) - 1}{m[4:]}"
            if prev in ser and ser[prev]:
                out[m] = round((ser[m] / ser[prev] - 1) * 100, 2)
    elif how == "mom":
        for i in range(1, len(months)):
            a, b = ser[months[i - 1]], ser[months[i]]
            if a:
                out[months[i]] = round((b / a - 1) * 100, 2)
    elif how == "diff":
        for i in range(1, len(months)):
            out[months[i]] = round((ser[months[i]] - ser[months[i - 1]]) * scale, 2)
    return out


def build_series(ind_id: str, raw=None):
    raw = raw or _state["raw"] or load()
    ind = BY_ID[ind_id]
    src = ind["source"]
    data, notes = {}, []
    if _state.get("ifind", {}).get(ind_id):
        data = {m: float(v) for m, v in _state["ifind"][ind_id].items() if v is not None}
        notes.append("来源：iFinD EDB")
    elif "em" in src:
        rn, field = src["em"]
        tbl = (raw.get("cn") or {}).get(rn)
        if not tbl or field not in tbl["fields"]:
            return {"months": [], "values": [], "notes": ["数据源暂无此表"]}
        fi = tbl["fields"].index(field)
        fb = tbl["fields"].index(src["fallback"]) if src.get("fallback") in tbl["fields"] else None
        for row in tbl["rows"]:
            v = row[1 + fi]
            if v is None and fb is not None:
                v = row[1 + fb]
            if v is not None:
                data[row[0]] = float(v)
        if ind["freq"] == "Q":  # 季度：东方财富以季末月标记（03/06/09/12）
            data = {m: v for m, v in data.items() if m[5:7] in ("03", "06", "09", "12")}
    elif "em_house" in src:
        tbl = (raw.get("cn") or {}).get("EM_HOUSE70")
        if not tbl:
            return {"months": [], "values": [], "notes": ["数据源暂无此表"]}
        data = {row[0]: float(row[1]) for row in tbl["rows"] if row[1] is not None}
    elif "fred" in src:
        ser = (raw.get("us") or {}).get(src["fred"])
        if not ser:
            return {"months": [], "values": [], "notes": ["FRED 序列尚未获取（服务器需能访问 fred.stlouisfed.org）"]}
        monthly = _monthly_from_fred(ser, src.get("agg", "last"))
        if ind["freq"] == "Q":
            # FRED 季度数据以季度首月标记，转为季末月
            monthly = {f"{m[:4]}-{int(m[5:7]) + 2:02d}": v for m, v in monthly.items()}
        data = _transform(monthly, src.get("transform", "level"), ind["freq"], src.get("scale", 1.0))
        notes.append("来源：FRED（" + src["fred"] + "）")
    ov = OVERRIDE_DIR / f"{ind_id}.csv"
    if ov.exists():
        data.update(read_override(ov))
        notes.append("已使用上传 CSV 覆盖部分数据")
    data = {m: v for m, v in data.items() if m >= "2008-01"}
    if not data:
        return {"months": [], "values": [], "notes": ["无数据"]}
    if ind["freq"] == "Q":
        months = sorted(data)
        return {"months": months, "values": [data[m] for m in months], "notes": notes}
    months_all = month_range(min(data), max(data))
    months, values = [], []
    for m in months_all:
        if ind["jan_merge"] and m.endswith("-01"):
            continue
        months.append(m)
        values.append(data.get(m))
    filled = 0
    for i, v in enumerate(values):
        if v is None:
            prev = next((values[j] for j in range(i - 1, -1, -1) if values[j] is not None), None)
            nxt = next((values[j] for j in range(i + 1, len(values)) if values[j] is not None), None)
            values[i] = prev if nxt is None else (nxt if prev is None else (prev + nxt) / 2)
            filled += 1
    if filled:
        notes.append(f"{filled} 个缺失月已插值")
    if ind["jan_merge"]:
        notes.append("1–2 月合并发布：剔除 1 月")
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
            if len(m) == 6:
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
    return {"source": _state["source"], "fetched_at": _state["fetched_at"], "errors": _state["errors"], "ifind": ifind.status()}


def export_csv(series: dict, country=None) -> str:
    ids = [i["id"] for i in INDICATORS if i["id"] in series and (country in (None, "", i["country"]))]
    months = sorted({m for i in ids for m in series[i]["months"]})
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["月份"] + [f"{BY_ID[i]['name']}（{BY_ID[i]['unit']}）" for i in ids])
    lk = {i: dict(zip(series[i]["months"], series[i]["values"])) for i in ids}
    for m in months:
        w.writerow([m] + [lk[i].get(m, "") for i in ids])
    return "﻿" + out.getvalue()
