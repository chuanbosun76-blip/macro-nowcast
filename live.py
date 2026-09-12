"""实时行情（东方财富 push2 行情接口）：指数 / 汇率 / 利率 / 商品，秒级刷新 + 日内走势。"""
from __future__ import annotations

import os
import threading
import time

import httpx

import config
import store

PUSH_URL = os.environ.get("EM_PUSH_URL", "https://push2.eastmoney.com/api/qt/ulist.np/get")
TX_URL = os.environ.get("TX_QUOTE_URL", "https://qt.gtimg.cn/q=")
DC_URL = os.environ.get("EM_DC_URL", "https://datacenter-web.eastmoney.com/api/data/v1/get")
# 备源映射：东财 secid → 腾讯代码 / 东财国债收益率表字段
TX_MAP = {"1.000001": "sh000001", "0.399001": "sz399001", "0.399006": "sz399006", "1.000300": "sh000300", "100.HSI": "hkHSI",
          "100.DJIA": "usDJI", "100.SPX": "usINX", "100.NDX": "usNDX", "100.IXIC": "usIXIC", "133.USDCNH": "whUSDCNY", "119.USDCNY": "whUSDCNY",
          "100.UDI": "whUSDX", "101.GC00Y": "hf_GC", "102.CL00Y": "hf_CL", "101.SI00Y": "hf_SI"}
YIELD_MAP = {"171.US10Y": "EMG00001310", "171.US2Y": "EMG00001306", "171.CN10Y": "EMM00166466", "171.CN2Y": "EMM00588704",
             "171.US30Y": "EMG00001312", "171.CN30Y": "EMM00166469"}
TREND_URL = os.environ.get("EM_TREND_URL", "https://push2his.eastmoney.com/api/qt/stock/trends2/get")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://quote.eastmoney.com/"}

# secid, 显示名, 分组
DEFAULT_SECIDS = [
    ("1.000001", "上证指数", "股指"), ("0.399001", "深证成指", "股指"), ("0.399006", "创业板指", "股指"), ("100.HSI", "恒生指数", "股指"),
    ("100.DJIA", "道琼斯", "股指"), ("100.SPX", "标普500", "股指"), ("100.NDX", "纳斯达克100", "股指"), ("100.N225", "日经225", "股指"),
    ("100.SX5E", "欧洲斯托克50", "股指"),
    ("133.USDCNH", "美元/人民币", "汇率"), ("100.UDI", "美元指数", "汇率"),
    ("171.US10Y", "美债10Y收益率", "利率"), ("171.US2Y", "美债2Y收益率", "利率"), ("171.CN10Y", "中债10Y收益率", "利率"),
    ("101.GC00Y", "COMEX黄金", "商品"), ("102.CL00Y", "NYMEX原油", "商品"),
]
_lock = threading.Lock()
_cache: dict = {"quotes": (0.0, None), "trend": {}, "em_fail_until": 0.0}


def secids():
    """设置页可覆盖：live_secids = [[secid, name, group], ...]；或环境变量 LIVE_SECIDS=secid:名称:组,..."""
    custom = store.get_setting("live_secids")
    if custom:
        return [tuple(x) for x in custom if len(x) == 3]
    env = os.environ.get("LIVE_SECIDS", "").strip()
    if env:
        out = []
        for tok in env.split(","):
            p = tok.split(":")
            if len(p) == 3:
                out.append((p[0].strip(), p[1].strip(), p[2].strip()))
        if out:
            return out
    return DEFAULT_SECIDS


def _q_eastmoney(ids, meta, c):
    r = c.get(PUSH_URL, params={"fltt": 2, "invt": 2, "fields": "f2,f3,f4,f12,f13,f14,f124", "secids": ",".join(s[0] for s in ids)})
    r.raise_for_status()
    out = []
    for d in ((r.json().get("data") or {}).get("diff") or []):
        sid = f"{d.get('f13')}.{d.get('f12')}"
        m = meta.get(sid)
        if not m or d.get("f2") in (None, "-"):
            continue
        out.append({"secid": sid, "name": m[1], "group": m[2], "em_name": d.get("f14"), "price": float(d.get("f2")), "pct": float(d.get("f3") or 0),
                    "chg": float(d.get("f4") or 0), "ts": d.get("f124"), "src": "eastmoney"})
    return out


def _q_tencent(ids, meta, c):
    codes = [(s[0], TX_MAP[s[0]]) for s in ids if s[0] in TX_MAP]
    if not codes:
        return []
    r = c.get(TX_URL + ",".join(t for _, t in codes), headers={"User-Agent": UA["User-Agent"]})
    r.raise_for_status()
    txt = r.content.decode("gbk", errors="ignore")
    vals = {}
    for line in txt.split(";"):
        line = line.strip()
        if not line.startswith("v_"):
            continue
        k, v = line[2:].split("=", 1)
        vals[k] = v.strip().strip('"')
    out = []
    for sid, t in codes:
        raw = vals.get(t)
        if not raw:
            continue
        m = meta[sid]
        try:
            if t.startswith("hf_"):
                f = raw.split(",")
                price, pct, prev = float(f[0]), float(f[1]), float(f[7])
                chg = price - prev
                name = f[13] if len(f) > 13 else t
            elif t.startswith("wh"):
                f = raw.split("~")
                price, prev, chg, pct, name = float(f[3]), float(f[6]), float(f[12]), float(f[13]), f[1]
            else:
                f = raw.split("~")
                price, chg, pct, name = float(f[3]), float(f[31]), float(f[32]), f[1]
        except (ValueError, IndexError):
            continue
        out.append({"secid": sid, "name": m[1], "group": m[2], "em_name": name, "price": price, "pct": pct, "chg": chg, "ts": int(time.time()), "src": "tencent"})
    return out


def _q_yields(ids, meta, c):
    want = [(s[0], YIELD_MAP[s[0]]) for s in ids if s[0] in YIELD_MAP]
    if not want:
        return []
    r = c.get(DC_URL, params={"reportName": "RPTA_WEB_TREASURYYIELD", "columns": "SOLAR_DATE," + ",".join(f for _, f in want), "pageSize": 6,
                              "pageNumber": 1, "sortColumns": "SOLAR_DATE", "sortTypes": -1, "source": "WEB", "client": "WEB"})
    r.raise_for_status()
    rows = ((r.json().get("result") or {}).get("data")) or []
    out = []
    for sid, f in want:
        vals = [(d["SOLAR_DATE"][:10], d.get(f)) for d in rows if d.get(f) is not None][:2]
        if not vals:
            continue
        cur = float(vals[0][1])
        prev = float(vals[1][1]) if len(vals) > 1 else cur
        m = meta[sid]
        out.append({"secid": sid, "name": m[1], "group": m[2], "em_name": f"日频 {vals[0][0]}", "price": cur, "pct": round((cur / prev - 1) * 100, 2) if prev else 0,
                    "chg": round(cur - prev, 4), "ts": vals[0][0], "src": "eastmoney-dc"})
    return out


def quotes(max_age: float = 5.0):
    with _lock:
        ts, data = _cache["quotes"]
        if data is not None and time.time() - ts < max_age:
            return data
    ids = secids()
    meta = {s[0]: s for s in ids}
    out, errs, provider = [], [], None
    if not config.OFFLINE:
        with httpx.Client(timeout=8, headers=UA) as c:
            if time.time() >= _cache["em_fail_until"]:
                try:
                    out = _q_eastmoney(ids, meta, c)
                    provider = "东方财富"
                except Exception as e:  # noqa
                    errs.append(f"东财行情: {str(e)[:60]}")
                    _cache["em_fail_until"] = time.time() + 600  # 失败后 10 分钟内直接走备源
            if not out:
                try:
                    out = _q_tencent(ids, meta, c)
                    provider = "腾讯行情"
                except Exception as e:  # noqa
                    errs.append(f"腾讯行情: {str(e)[:60]}")
            have = {q["secid"] for q in out}
            if any(s[0] in YIELD_MAP and s[0] not in have for s in ids):
                try:
                    out.extend(_q_yields(ids, meta, c))
                except Exception as e:  # noqa
                    errs.append(f"收益率: {str(e)[:60]}")
    order = {s[0]: i for i, s in enumerate(ids)}
    out.sort(key=lambda x: order.get(x["secid"], 999))
    err = "；".join(errs) if (errs and not out) else None
    data = {"items": out, "error": err, "warn": "；".join(errs) if errs else None, "provider": provider,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"), "n": len(out)}
    with _lock:
        if out or _cache["quotes"][1] is None:
            _cache["quotes"] = (time.time(), data)
        else:  # 抓取失败沿用上次
            old = _cache["quotes"][1]
            old["error"] = err
            data = old
    return data


def trend(secid: str, max_age: float = 60.0, max_points: int = 240):
    with _lock:
        ts, data = _cache["trend"].get(secid, (0.0, None))
        if data is not None and time.time() - ts < max_age:
            return data
    data = {"secid": secid, "pre_close": None, "points": [], "error": None}
    if not config.OFFLINE:
        try:
            with httpx.Client(timeout=8, headers=UA) as c:
                r = c.get(TREND_URL, params={"secid": secid, "fields1": "f1,f2,f3,f4,f5,f6,f7,f8", "fields2": "f51,f53", "ndays": 1, "iscr": 0, "iscca": 0})
                r.raise_for_status()
                j = r.json().get("data") or {}
                pts = []
                for row in j.get("trends") or []:
                    t, v = row.split(",")[:2]
                    try:
                        pts.append([t[-5:], float(v)])
                    except ValueError:
                        pass
                if len(pts) > max_points:
                    step = len(pts) / max_points
                    pts = [pts[int(i * step)] for i in range(max_points)] + [pts[-1]]
                data.update(pre_close=j.get("preClose"), points=pts, name=j.get("name"))
        except Exception as e:  # noqa
            data["error"] = str(e)
    with _lock:
        _cache["trend"][secid] = (time.time(), data)
    return data
