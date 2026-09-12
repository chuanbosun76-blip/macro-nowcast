"""市场月度数据库：股指/汇率/商品月收盘（A股宽基、恒生、美股三大、日经、美元指数、USDCNH、黄金、原油）与国债收益率月均（中美 2Y/10Y/30Y）。
用途：宏观→市场传导分析（事件回归）。数据：内置快照（2005 年起，东方财富 K 线 / 国债收益率表）+ 实时增量更新。"""
from __future__ import annotations

import json
import math
import os
import threading
import time

import httpx

import config

KLINE_URL = os.environ.get("EM_KLINE_URL", "https://push2his.eastmoney.com/api/qt/stock/kline/get")
TX_KLINE_URL = os.environ.get("TX_KLINE_URL", "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get")
DC_URL = os.environ.get("EM_DC_URL", "https://datacenter-web.eastmoney.com/api/data/v1/get")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://quote.eastmoney.com/"}
SNAPSHOT = config.ROOT / "snapshot_markets.json"
CACHE = config.DATA_DIR / "markets_cache.json"

# key, 名称, 市场, 类型, 东财 secid, 腾讯代码
META = [
    ("hs300", "沪深300", "CN", "equity", "1.000300", "sh000300"),
    ("sh", "上证指数", "CN", "equity", "1.000001", "sh000001"),
    ("cyb", "创业板指", "CN", "equity", "0.399006", "sz399006"),
    ("zz500", "中证500", "CN", "equity", "1.000905", "sh000905"),
    ("zz1000", "中证1000", "CN", "equity", "1.000852", "sh000852"),
    ("kc50", "科创50", "CN", "equity", "1.000688", "sh000688"),
    ("hsi", "恒生指数", "HK", "equity", "100.HSI", "hkHSI"),
    ("spx", "标普500", "US", "equity", "100.SPX", "usINX"),
    ("ndx", "纳斯达克100", "US", "equity", "100.NDX", "usNDX"),
    ("djia", "道琼斯", "US", "equity", "100.DJIA", "usDJI"),
    ("n225", "日经225", "JP", "equity", "100.N225", None),
    ("udi", "美元指数", "FX", "equity", "100.UDI", None),
    ("usdcnh", "离岸人民币USDCNH", "FX", "equity", "133.USDCNH", None),
    ("gold", "COMEX黄金", "CMD", "equity", "101.GC00Y", None),
    ("oil", "WTI原油", "CMD", "equity", "102.CL00Y", None),
    ("cn10y", "中债10Y收益率", "CN", "yield", "EMM00166466", None),
    ("cn2y", "中债2Y收益率", "CN", "yield", "EMM00588704", None),
    ("cn30y", "中债30Y收益率", "CN", "yield", "EMM00166469", None),
    ("us10y", "美债10Y收益率", "US", "yield", "EMG00001310", None),
    ("us2y", "美债2Y收益率", "US", "yield", "EMG00001306", None),
    ("us30y", "美债30Y收益率", "US", "yield", "EMG00001312", None),
]
# 传导分析使用的核心资产（其余仅入库/看板）
CORE = ["hs300", "sh", "cyb", "hsi", "spx", "ndx", "djia", "udi", "usdcnh", "gold", "cn10y", "cn2y", "us10y", "us2y"]
ASSET_CLASS = {"equity": "股票", "yield": "利率"}
BY_KEY = {m[0]: m for m in META}
_lock = threading.Lock()
_state = {"data": None, "loaded_at": 0.0, "source": {}, "errors": []}


def _read(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _fetch_kline_em(secid, client, beg="20230101"):
    r = client.get(KLINE_URL, params={"secid": secid, "klt": 103, "fqt": 1, "beg": beg, "end": "20500101", "lmt": 1000,
                                      "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f53"})
    r.raise_for_status()
    out = {}
    for row in (r.json().get("data") or {}).get("klines") or []:
        d, c = row.split(",")[:2]
        out[d[:7]] = float(c)
    return out


def _fetch_kline_tx(code, client):
    r = client.get(TX_KLINE_URL, params={"param": f"{code},month,,,48,qfq"})
    r.raise_for_status()
    d = (r.json().get("data") or {}).get(code) or {}
    rows = d.get("month") or d.get("qfqmonth") or []
    return {row[0][:7]: float(row[2]) for row in rows if len(row) >= 3}


def _fetch_yields(client, pages=2):
    """最近 ~1000 个交易日 → 月均。"""
    cols = "SOLAR_DATE," + ",".join(m[4] for m in META if m[3] == "yield")
    agg = {m[0]: {} for m in META if m[3] == "yield"}
    for page in range(1, pages + 1):
        r = client.get(DC_URL, params={"reportName": "RPTA_WEB_TREASURYYIELD", "columns": cols, "pageSize": 500, "pageNumber": page,
                                       "sortColumns": "SOLAR_DATE", "sortTypes": -1, "source": "WEB", "client": "WEB"})
        r.raise_for_status()
        data = ((r.json().get("result") or {}).get("data")) or []
        for d in data:
            mth = d["SOLAR_DATE"][:7]
            for m in META:
                if m[3] == "yield" and d.get(m[4]) is not None:
                    agg[m[0]].setdefault(mth, []).append(float(d[m[4]]))
        if len(data) < 500:
            break
    return {k: {mth: round(sum(v) / len(v), 4) for mth, v in a.items()} for k, a in agg.items()}


def load(force=False, max_age=6 * 3600):
    """快照 + 缓存 + 增量抓取（股指近 3 年月 K，收益率近 4 年）。"""
    with _lock:
        if _state["data"] and not force and time.time() - _state["loaded_at"] < max_age:
            return _state["data"]
        snap = _read(SNAPSHOT)
        data = {"equity": dict(snap.get("equity") or {}), "yield": dict(snap.get("yield") or {})}
        cache = _read(CACHE)
        for grp in ("equity", "yield"):
            for k, ser in (cache.get(grp) or {}).items():
                data[grp].setdefault(k, {}).update(ser)
        source, errors = {"equity": "内置快照", "yield": "内置快照"}, []
        if not config.OFFLINE:
            fresh = {"equity": {}, "yield": {}}
            with httpx.Client(timeout=12, headers=UA, follow_redirects=True) as c:
                em_ok = True
                for k, name, mkt, typ, secid, tx in META:
                    if typ != "equity":
                        continue
                    ser = None
                    if em_ok:
                        try:
                            ser = _fetch_kline_em(secid, c)
                        except Exception as e:  # noqa
                            em_ok = False
                            errors.append(f"东财K线 {k}: {str(e)[:80]}")
                    if not ser and tx:
                        try:
                            ser = _fetch_kline_tx(tx, c)
                            source["equity"] = "腾讯行情（实时）"
                        except Exception as e:  # noqa
                            errors.append(f"腾讯K线 {k}: {str(e)[:80]}")
                    if ser:
                        fresh["equity"][k] = ser
                        if em_ok:
                            source["equity"] = "东方财富K线（实时）"
                try:
                    fresh["yield"] = _fetch_yields(c)
                    source["yield"] = "东方财富国债收益率表（实时）"
                except Exception as e:  # noqa
                    errors.append(f"收益率: {str(e)[:80]}")
            for grp in ("equity", "yield"):
                for k, ser in fresh[grp].items():
                    data[grp].setdefault(k, {}).update(ser)
            if fresh["equity"] or fresh["yield"]:
                try:
                    CACHE.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
        _state.update(data=data, loaded_at=time.time(), source=source, errors=errors)
        return data


def patch_current_month(quotes_items):
    """用实时行情把当月收盘刷新为最新价（月内近似）。"""
    if not _state["data"]:
        return
    cur = time.strftime("%Y-%m")
    bysec = {q["secid"]: q for q in quotes_items}
    for k, name, mkt, typ, secid, tx in META:
        if typ == "equity" and secid in bysec and bysec[secid].get("price"):
            _state["data"]["equity"].setdefault(k, {})[cur] = float(bysec[secid]["price"])


def series(key):
    data = load()
    m = BY_KEY[key]
    ser = (data.get(m[3]) or {}).get(key) or {}
    return dict(sorted(ser.items()))


def responses(key):
    """市场“反应”序列：股指 → 月度对数收益率(%)；收益率 → 月度变动(bp)。键为当月。"""
    m = BY_KEY[key]
    ser = series(key)
    months = sorted(ser)
    out = {}
    for i in range(1, len(months)):
        a, b = ser[months[i - 1]], ser[months[i]]
        if a is None or b is None:
            continue
        if m[3] == "equity":
            if a > 0 and b > 0:
                out[months[i]] = round(100 * math.log(b / a), 3)
        else:
            out[months[i]] = round((b - a) * 100, 1)
    return out


def status():
    load()
    data = _state["data"] or {}
    last = {}
    for grp in ("equity", "yield"):
        for k, ser in (data.get(grp) or {}).items():
            if ser:
                lm = max(ser)
                last[k] = [lm, ser[lm]]
    return {"source": _state["source"], "errors": _state["errors"], "loaded_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(_state["loaded_at"])) if _state["loaded_at"] else None,
            "last": last, "meta": [{"key": m[0], "name": m[1], "market": m[2], "type": m[3]} for m in META]}
