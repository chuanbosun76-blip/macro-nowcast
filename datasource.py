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
from indicators import BY_ID, EM_FIELDS, EM_HOUSE_FIELDS, EM_STEP_TABLES, INDICATORS

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


def _em_house(client: httpx.Client, pages: int = 4):
    """70 城新建/二手住宅价格：按月对城市取均值（指数 100 为基 → 同比/环比 %）。"""
    agg = {}
    for page in range(1, pages + 1):
        params = {"columns": "REPORT_DATE,CITY," + ",".join(EM_HOUSE_FIELDS), "pageNumber": page, "pageSize": 500,
                  "sortColumns": "REPORT_DATE", "sortTypes": -1, "source": "WEB", "client": "WEB", "reportName": "RPT_ECONOMY_HOUSE_PRICE"}
        r = client.get(DC_URL, params=params)
        r.raise_for_status()
        data = ((r.json().get("result") or {}).get("data")) or []
        if not data:
            break
        for d in data:
            m = d["REPORT_DATE"][:7]
            for f in EM_HOUSE_FIELDS:
                v = d.get(f)
                if v is not None:
                    agg.setdefault(m, {}).setdefault(f, []).append(float(v) - 100.0)
        if len(data) < 500:
            break
    rows = []
    for m in sorted(agg):
        fd = agg[m]
        if len(fd.get("FIRST_COMHOUSE_SAME", [])) < 30:
            continue
        rows.append([m] + [round(sum(fd[f]) / len(fd[f]), 2) if fd.get(f) else None for f in EM_HOUSE_FIELDS])
    return {"fields": EM_HOUSE_FIELDS, "rows": rows}


def _em_step(rn: str, client: httpx.Client):
    field, datef = EM_STEP_TABLES[rn]
    r = client.get(DC_URL, params={"columns": "ALL", "pageNumber": 1, "pageSize": 500, "sortColumns": "REPORT_DATE", "sortTypes": 1,
                                   "source": "WEB", "client": "WEB", "reportName": rn})
    r.raise_for_status()
    j = r.json()
    if not j.get("success"):
        raise RuntimeError(f"{rn}: {j.get('message')}")
    rows = sorted([[d[datef][:10], d[field]] for d in j["result"]["data"] if d.get(field) is not None and d.get(datef)])
    return {"fields": [field], "rows": rows, "step": True}


def _parallel(jobs: dict, fn, workers: int = 6, fail_fast_after: int | None = None):
    """并发抓取；jobs = {key: arg}。fail_fast_after：若前 N 个任务全部为网络错误则放弃其余（避免被墙时逐个超时）。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out, errors = {}, []
    keys = list(jobs)
    if fail_fast_after and keys:
        probe = keys[:fail_fast_after]
        with ThreadPoolExecutor(max_workers=len(probe)) as ex:
            futs = {ex.submit(fn, jobs[k]): k for k in probe}
            for f in as_completed(futs):
                k = futs[f]
                try:
                    out[k] = f.result()
                except Exception as e:  # noqa
                    errors.append(f"{k}: {e}")
        if not out:
            errors.append(f"前 {len(probe)} 个请求全部失败，跳过其余 {len(keys) - len(probe)} 个（网络不可达）")
            return out, errors
        keys = keys[len(probe):]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, jobs[k]): k for k in keys}
        for f in as_completed(futs):
            k = futs[f]
            try:
                out[k] = f.result()
            except Exception as e:  # noqa
                errors.append(f"{k}: {e}")
    return out, errors


def fetch_cn():
    with httpx.Client(timeout=config.HTTP_TIMEOUT, headers=UA, follow_redirects=True) as c:
        jobs = {rn: rn for rn in EM_FIELDS}
        jobs.update({rn: rn for rn in EM_STEP_TABLES})
        jobs["EM_HOUSE70"] = "EM_HOUSE70"

        def one(rn):
            if rn == "EM_HOUSE70":
                return _em_house(c)
            if rn in EM_STEP_TABLES:
                return _em_step(rn, c)
            return _em_table(rn, c)

        return _parallel(jobs, one, workers=6, fail_fast_after=3)


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
    with httpx.Client(timeout=min(config.HTTP_TIMEOUT, 20), headers={"User-Agent": UA["User-Agent"]},
                      follow_redirects=True) as c:
        out, errors = _parallel({s: s for s in sids}, lambda s: _fred_series(s, c), workers=6, fail_fast_after=2)
    return out, [f"FRED {e}" for e in errors]


# ------------------------------------------------------------------ 东方财富·美国宏观（FRED 不可达时的备源，2008 年起，含发布日期）
def _em_us_series(code: str, client: httpx.Client) -> dict[str, float]:
    params = {"columns": "ALL", "pageNumber": 1, "pageSize": 500, "sortColumns": "REPORT_DATE", "sortTypes": -1,
              "source": "WEB", "client": "WEB", "reportName": "RPT_ECONOMICVALUE_USANEW",
              "filter": f'(INDICATOR_ID="{code}")'}
    r = client.get(DC_URL, params=params)
    r.raise_for_status()
    j = r.json()
    if not j.get("success"):
        raise RuntimeError(f"{code}: {j.get('message')}")
    out = {}
    for d in j["result"]["data"]:
        if d.get("VALUE") is not None:
            out[d["REPORT_DATE"][:7]] = float(d["VALUE"])
    return out


def fetch_us_em():
    codes = sorted({i["source"]["em_us"] for i in INDICATORS if "em_us" in i["source"]})
    with httpx.Client(timeout=config.HTTP_TIMEOUT, headers=UA, follow_redirects=True) as c:
        out, errors = _parallel({f"EM:{k}": k for k in codes}, lambda k: _em_us_series(k, c), workers=6, fail_fast_after=2)
    return out, [f"东财美国 {e}" for e in errors]


# ------------------------------------------------------------------ 加载
def _read(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def load(force_live: bool = False, network: bool = True):
    """network=False：只读缓存/快照，秒级返回（启动首屏用）；之后再 network=True 拉实时。"""
    with _lock:
        now = time.time()
        cache = _read(CACHE)
        cache_ok = bool(cache) and now - CACHE.stat().st_mtime < config.REFRESH_HOURS * 3600
        raw = {"cn": _read(SNAPSHOT_CN), "us": _read(SNAPSHOT_US)}
        raw["cn"].update(cache.get("cn") or {})
        raw["us"].update(cache.get("us") or {})
        source = {"cn": "内置快照" if not cache.get("cn") else "本地缓存", "us": "内置快照" if not cache.get("us") else "本地缓存"}
        errors = list(_state.get("errors") or []) if not network else []
        if network and not config.OFFLINE and (force_live or not cache_ok):
            _state["stage"] = "抓取东方财富"
            cn, e1 = fetch_cn()
            _state["stage"] = "抓取 FRED"
            us, e2 = fetch_us()
            _state["stage"] = "抓取东方财富·美国宏观"
            us_em, e3 = fetch_us_em()
            _state["stage"] = None
            errors = e1 + e2 + e3
            if cn:
                for rn, tbl in cn.items():
                    old = raw["cn"].get(rn)
                    if old and old.get("fields") == tbl.get("fields") and rn == "EM_HOUSE70":
                        merged = {r[0]: r for r in old["rows"]}
                        merged.update({r[0]: r for r in tbl["rows"]})
                        tbl = {"fields": tbl["fields"], "rows": [merged[k] for k in sorted(merged)]}
                    raw["cn"][rn] = tbl
                source["cn"] = "东方财富数据中心（实时）" + ("，部分表回退" if e1 else "")
            if us or us_em:
                raw["us"].update(us)
                raw["us"].update(us_em)
                parts = []
                if us:
                    parts.append("FRED（实时）" + ("，部分序列回退" if e2 else ""))
                if us_em:
                    parts.append("东方财富·美国宏观（实时）")
                source["us"] = " + ".join(parts)
                us = us or us_em
            if cn or us:
                CACHE.write_text(json.dumps({"cn": raw["cn"], "us": raw["us"]}, ensure_ascii=False), encoding="utf-8")
        # iFinD EDB 覆盖
        if network and ifind.enabled() and not config.OFFLINE:
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


def _table_dict(raw, rn, field, fallback=None, scale=1.0):
    tbl = (raw.get("cn") or {}).get(rn)
    if not tbl or field not in tbl["fields"]:
        return None
    fi = tbl["fields"].index(field)
    fb = tbl["fields"].index(fallback) if fallback in tbl["fields"] else None
    out = {}
    for row in tbl["rows"]:
        v = row[1 + fi]
        if v is None and fb is not None:
            v = row[1 + fb]
        if v is not None:
            out[row[0]] = float(v) * scale
    return out


def _gdp_derived(raw, mode):
    """GDP 累计表 → 当季同比 / 名义当季同比（估算）。"""
    tbl = (raw.get("cn") or {}).get("RPT_ECONOMY_GDP")
    if not tbl:
        return {}
    f = tbl["fields"]
    if "SUM_SAME" not in f or "DOMESTICL_PRODUCT_BASE" not in f:
        return {}
    gi, li = f.index("SUM_SAME"), f.index("DOMESTICL_PRODUCT_BASE")
    rows = {r[0]: (r[1 + gi], r[1 + li]) for r in tbl["rows"] if r[1 + gi] is not None and r[1 + li] is not None}
    out = {}
    for m in sorted(rows):
        y, q = int(m[:4]), int(m[5:7])
        g_c, L = rows[m]
        if mode == "nominal_yoy":
            prev_q = f"{y}-{q - 3:02d}" if q > 3 else None
            Lq = L - rows[prev_q][1] if prev_q and prev_q in rows else (L if q == 3 else None)
            pm = f"{y - 1}-{q:02d}"
            ppq = f"{y - 1}-{q - 3:02d}" if q > 3 else None
            if Lq is None or pm not in rows:
                continue
            Lq_prev = rows[pm][1] - rows[ppq][1] if ppq and ppq in rows else (rows[pm][1] if q == 3 else None)
            if Lq_prev:
                out[m] = round((Lq / Lq_prev - 1) * 100, 2)
        else:  # q_yoy：单季实际同比 ≈ (g_c(Q)·W_Q − g_c(Q−1)·W_{Q−1}) / (W_Q − W_{Q−1})，W 为上年同期累计名义值
            if q == 3:
                out[m] = g_c
                continue
            prev_q = f"{y}-{q - 3:02d}"
            if prev_q not in rows:
                continue
            g_p, L_p = rows[prev_q]
            W_q, W_p = L / (1 + g_c / 100), L_p / (1 + g_p / 100)
            if W_q - W_p > 0:
                out[m] = round((g_c * W_q - g_p * W_p) / (W_q - W_p), 2)
    return out


def _step_to_monthly(rows, first="2008-01"):
    """事件日期序列 → 月度（月末生效值，前值填充）。"""
    if not rows:
        return {}
    ev = sorted(rows)
    out, cur, i = {}, None, 0
    last = time.strftime("%Y-%m")
    for m in month_range(first, last):
        me = f"{m}-31"
        while i < len(ev) and ev[i][0] <= me:
            cur = float(ev[i][1])
            i += 1
        if cur is None and i == 0:
            # 起点前最后一个事件
            before = [r for r in ev if r[0] <= me]
            cur = float(before[-1][1]) if before else None
        if cur is not None:
            out[m] = cur
    return out


def build_series(ind_id: str, raw=None, _depth=0):
    raw = raw or _state["raw"] or load()
    ind = BY_ID[ind_id]
    src = ind["source"]
    data, notes = {}, []
    if _state.get("ifind", {}).get(ind_id):
        data = {m: float(v) for m, v in _state["ifind"][ind_id].items() if v is not None}
        notes.append("来源：iFinD EDB")
    elif "em" in src:
        rn, field = src["em"]
        d = _table_dict(raw, rn, field, src.get("fallback"), src.get("scale", 1.0))
        if d is None:
            return {"months": [], "values": [], "notes": ["数据源暂无此表"]}
        data = d
        if src.get("offset"):
            data = {m: v + src["offset"] for m, v in data.items()}
        if ind["freq"] == "Q":
            data = {m: v for m, v in data.items() if m[5:7] in ("03", "06", "09", "12")}
        if ind["freq"] == "A":
            data = {m: v for m, v in data.items() if m[5:7] == "12"}
        notes.append(f"来源：东方财富数据中心 {rn}.{field}")
    elif "em_accum_yoy" in src:
        rn, field = src["em_accum_yoy"]
        d = _table_dict(raw, rn, field)
        if d is None:
            return {"months": [], "values": [], "notes": ["数据源暂无此表"]}
        for m, v in d.items():
            pm = f"{int(m[:4]) - 1}{m[4:]}"
            if d.get(pm):
                data[m] = round((v / d[pm] - 1) * 100, 2)
        notes.append(f"来源：由 {rn}.{field} 累计值计算累计同比（未剔除基数修订）")
    elif "em_step" in src:
        rn, field, datef = src["em_step"]
        tbl = (raw.get("cn") or {}).get(rn)
        if not tbl:
            return {"months": [], "values": [], "notes": ["数据源暂无此表"]}
        data = _step_to_monthly(tbl["rows"])
        notes.append(f"来源：{rn}（事件型，月末生效值）")
    elif "gdp" in src:
        data = _gdp_derived(raw, src["gdp"])
        notes.append("来源：由国家统计局 GDP 累计同比与累计名义值推算（估算口径）")
    elif "derived" in src:
        a, op, b = src["derived"]
        if _depth > 3:
            return {"months": [], "values": [], "notes": ["派生层级过深"]}
        sa, sb = build_series(a, raw, _depth + 1), build_series(b, raw, _depth + 1)
        da, db = dict(zip(sa["months"], sa["values"])), dict(zip(sb["months"], sb["values"]))
        for m in da:
            if m in db and da[m] is not None and db[m] is not None:
                data[m] = round(da[m] - db[m], 3) if op == "-" else round(da[m] + db[m], 3)
        notes.append(f"派生：{BY_ID[a]['short']} {op} {BY_ID[b]['short']}")
    elif "yield" in src:
        import markets
        data = dict(markets.series(src["yield"]))
        notes.append("来源：东方财富国债收益率表（日频取月均）")
    elif "em_house" in src:
        tbl = (raw.get("cn") or {}).get("EM_HOUSE70")
        if not tbl or src["em_house"] not in tbl["fields"]:
            return {"months": [], "values": [], "notes": ["数据源暂无此表"]}
        fi = tbl["fields"].index(src["em_house"])
        data = {row[0]: float(row[1 + fi]) for row in tbl["rows"] if len(row) > 1 + fi and row[1 + fi] is not None}
        notes.append("来源：国家统计局 70 城房价（东方财富数据中心，按城市取均值）")
    elif "fred" in src or "em_us" in src:
        ser = (raw.get("us") or {}).get(src["fred"]) if "fred" in src else None
        em = (raw.get("us") or {}).get("EM:" + src["em_us"]) if "em_us" in src else None
        if em:  # 优先官方发布口径（与研报/新闻中的 headline 数字一致），FRED 用于无东财映射的序列
            sc = src.get("em_scale", 1.0)
            data = {m: round(float(v) * sc, 4) for m, v in em.items()}
            notes.append("来源：东方财富·美国宏观（" + src["em_us"] + "，官方发布口径转载）")
        elif ser:
            monthly = _monthly_from_fred(ser, src.get("agg", "last"))
            if ind["freq"] == "Q":
                monthly = {f"{m[:4]}-{int(m[5:7]) + 2:02d}": v for m, v in monthly.items()}
            data = _transform(monthly, src.get("transform", "level"), ind["freq"], src.get("scale", 1.0))
            notes.append("来源：FRED（" + src["fred"] + "）")
        else:
            return {"months": [], "values": [], "notes": ["美国序列尚未获取（FRED / 东方财富均不可达）"]}
    ov = OVERRIDE_DIR / f"{ind_id}.csv"
    if ov.exists():
        data.update(read_override(ov))
        notes.append("已使用上传 CSV 覆盖部分数据")
    data = {m: v for m, v in data.items() if m >= ("2005-01" if ind["freq"] in ("Q", "A") else "2008-01")}
    if not data:
        return {"months": [], "values": [], "notes": ["无数据"]}
    if ind["freq"] in ("Q", "A"):
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
    return {"source": _state["source"], "fetched_at": _state["fetched_at"], "errors": _state["errors"],
            "stage": _state.get("stage"), "ifind": ifind.status()}


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
