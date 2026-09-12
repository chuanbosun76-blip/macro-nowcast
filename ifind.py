"""同花顺 iFinD HTTP 接口适配器：宏观 EDB 月度序列。
配置（环境变量）：
  IFIND_REFRESH_TOKEN  iFinD 客户端生成的 refresh_token（有有效期，过期需重新生成）
  IFIND_EDB_MAP        JSON，指标 id → EDB 代码，例如 {"cpi_yoy":"M001620326","export_yoy":"M0000607"}
未配置或调用失败时自动回退东方财富数据。"""
from __future__ import annotations

import json
import os
import time

import httpx

BASE = os.environ.get("IFIND_BASE", "https://quantapi.51ifind.com/api/v1")
REFRESH_TOKEN = os.environ.get("IFIND_REFRESH_TOKEN", "").strip()
try:
    EDB_MAP = json.loads(os.environ.get("IFIND_EDB_MAP", "{}") or "{}")
except Exception:
    EDB_MAP = {}

_state = {"access_token": None, "token_at": 0, "last_ok": None, "last_error": None, "series": {}}


def enabled() -> bool:
    return bool(REFRESH_TOKEN and EDB_MAP)


def _access_token(client: httpx.Client) -> str:
    if _state["access_token"] and time.time() - _state["token_at"] < 6 * 3600:
        return _state["access_token"]
    r = client.post(f"{BASE}/get_access_token", headers={"Content-Type": "application/json", "refresh_token": REFRESH_TOKEN})
    j = r.json()
    if j.get("errorcode") not in (0, None) or not (j.get("data") or {}).get("access_token"):
        raise RuntimeError(f"iFinD 获取 access_token 失败：{j.get('errmsg') or j}")
    _state["access_token"] = j["data"]["access_token"]
    _state["token_at"] = time.time()
    return _state["access_token"]


def fetch_edb(codes: list[str], start="2008-01-01", timeout=30) -> dict[str, dict[str, float]]:
    """返回 {EDB代码: {"YYYY-MM": value}}"""
    if not REFRESH_TOKEN or not codes:
        return {}
    with httpx.Client(timeout=timeout) as c:
        tok = _access_token(c)
        r = c.post(f"{BASE}/edb_service", headers={"Content-Type": "application/json", "access_token": tok},
                   json={"indicators": ",".join(codes), "startdate": start, "enddate": time.strftime("%Y-%m-%d")})
        j = r.json()
    if j.get("errorcode") not in (0, None):
        raise RuntimeError(f"iFinD EDB 错误：{j.get('errmsg') or j}")
    out = {}
    for t in j.get("tables") or []:
        code = t.get("index") or t.get("indicator") or (t.get("thscode") or "")
        times, vals = t.get("time") or [], t.get("value") or []
        ser = {}
        for d, v in zip(times, vals):
            if v is None or d is None:
                continue
            m = str(d)[:7].replace("/", "-")
            try:
                ser[m] = float(v)
            except (TypeError, ValueError):
                pass
        if ser:
            out[str(code)] = ser
    return out


def load_all() -> dict[str, dict[str, float]]:
    """按 EDB_MAP 拉取全部已映射指标，返回 {指标id: {月份: 值}}。失败抛异常由调用方回退。"""
    if not enabled():
        return {}
    codes = sorted({c for c in EDB_MAP.values() if c})
    try:
        data = fetch_edb(codes)
        series = {ind: data[code] for ind, code in EDB_MAP.items() if code in data}
        _state.update(series=series, last_ok=time.strftime("%Y-%m-%d %H:%M"), last_error=None)
        return series
    except Exception as e:  # noqa
        _state["last_error"] = str(e)
        raise


def status():
    return {"enabled": enabled(), "mapped": len([c for c in EDB_MAP.values() if c]), "loaded": len(_state["series"]),
            "last_ok": _state["last_ok"], "last_error": _state["last_error"],
            "token_expires": _token_expiry()}


def _token_expiry():
    try:
        import base64
        payload = json.loads(base64.b64decode(REFRESH_TOKEN.split(".")[1] + "=="))
        return payload.get("user", {}).get("refreshTokenExpiredTime")
    except Exception:
        return None
