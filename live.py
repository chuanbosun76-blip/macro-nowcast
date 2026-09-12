"""实时行情（东方财富 push2 行情接口）：指数 / 汇率 / 利率 / 商品，秒级刷新 + 日内走势。"""
from __future__ import annotations

import os
import threading
import time

import httpx

import config
import store

PUSH_URL = os.environ.get("EM_PUSH_URL", "https://push2.eastmoney.com/api/qt/ulist.np/get")
TREND_URL = os.environ.get("EM_TREND_URL", "https://push2his.eastmoney.com/api/qt/stock/trends2/get")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://quote.eastmoney.com/"}

# secid, 显示名, 分组
DEFAULT_SECIDS = [
    ("1.000001", "上证指数", "股指"), ("0.399001", "深证成指", "股指"), ("0.399006", "创业板指", "股指"), ("100.HSI", "恒生指数", "股指"),
    ("100.DJIA", "道琼斯", "股指"), ("100.SPX", "标普500", "股指"), ("100.NDX", "纳斯达克100", "股指"), ("100.N225", "日经225", "股指"),
    ("100.SX5E", "欧洲斯托克50", "股指"),
    ("133.USDCNH", "美元/离岸人民币", "汇率"), ("100.UDI", "美元指数", "汇率"),
    ("171.US10Y", "美债10Y收益率", "利率"), ("171.US2Y", "美债2Y收益率", "利率"), ("171.CN10Y", "中债10Y收益率", "利率"),
    ("101.GC00Y", "COMEX黄金", "商品"), ("102.CL00Y", "NYMEX原油", "商品"),
]
_lock = threading.Lock()
_cache: dict = {"quotes": (0.0, None), "trend": {}}


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


def quotes(max_age: float = 5.0):
    with _lock:
        ts, data = _cache["quotes"]
        if data is not None and time.time() - ts < max_age:
            return data
    ids = secids()
    meta = {s[0]: s for s in ids}
    out, err = [], None
    if not config.OFFLINE:
        try:
            with httpx.Client(timeout=8, headers=UA) as c:
                r = c.get(PUSH_URL, params={"fltt": 2, "invt": 2, "fields": "f2,f3,f4,f12,f13,f14,f124", "secids": ",".join(s[0] for s in ids)})
                r.raise_for_status()
                for d in ((r.json().get("data") or {}).get("diff") or []):
                    sid = f"{d.get('f13')}.{d.get('f12')}"
                    m = meta.get(sid)
                    if not m or d.get("f2") in (None, "-"):
                        continue
                    out.append({"secid": sid, "name": m[1], "group": m[2], "em_name": d.get("f14"), "price": d.get("f2"), "pct": d.get("f3"),
                                "chg": d.get("f4"), "ts": d.get("f124")})
        except Exception as e:  # noqa
            err = str(e)
    order = {s[0]: i for i, s in enumerate(ids)}
    out.sort(key=lambda x: order.get(x["secid"], 999))
    data = {"items": out, "error": err, "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"), "n": len(out)}
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
