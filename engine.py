"""流程编排：数据加载 → 增量 SARIMAX → 三法对照 → AI 结构化研判 → 自动预测 / 回测 / 问答上下文。"""
from __future__ import annotations

import calendar
import json
import re
import math
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np

import config
import datasource
import llm
import markets
import reports
import store
import theory
from calendar_cn import spring_series
from indicators import BY_ID, GROUPS_ORDER, INDICATORS, LLM_MODES
from tsmodels import adf_test, expanding_backtest, lag1_corr, ljung_box, spec_from_label

AR_DIR = config.DATA_DIR / "ar_cache"
AR_DIR.mkdir(parents=True, exist_ok=True)
AR_VERSION = "v6"
SEED_FILE = config.ROOT / "ar_seed.json"
_seed_cache = None

_state = {"series": {}, "ar": {}, "mf": {}, "ar_progress": {}, "ready": False, "loading": False, "error": None, "loaded_at": None,
          "last_check": None, "version": uuid.uuid4().hex[:12], "pending": {}}
_lock = threading.RLock()
JOBS: dict[str, dict] = {}
UPDATE = {"running": False, "stage": "", "started": None, "job_id": None, "error": None, "finished": None}


# ------------------------------------------------------------------ 工具
def is_modeled(ind) -> bool:
    return ind["freq"] == "M" and ind["role"] in ("nowcast", "persist")


def unreachable(ind) -> bool:
    """数据已加载但该指标为空（通常是 FRED 独有序列在服务器不可达）→ 前端隐藏。"""
    if not _state["ready"]:
        return False
    s = _state["series"].get(ind["id"])
    return not s or not s["months"]


def active_indicators():
    return [i for i in INDICATORS if not unreachable(i)]


def next_month(ind, m: str) -> str:
    y, mm = int(m[:4]), int(m[5:7])
    if ind["freq"] == "Q":
        mm2 = mm + 3
        return f"{y + (mm2 > 12)}-{(mm2 - 12 if mm2 > 12 else mm2):02d}"
    y2, m2 = (y + 1, 1) if mm == 12 else (y, mm + 1)
    if ind["jan_merge"] and m2 == 1:
        m2 = 2
    return f"{y2}-{m2:02d}"


def month_end(m: str) -> str:
    y, mm = int(m[:4]), int(m[5:7])
    return f"{m}-{calendar.monthrange(y, mm)[1]:02d}"


def _clean(x):
    if x is None:
        return None
    if isinstance(x, (float, np.floating)) and not math.isfinite(float(x)):
        return None
    return float(x) if isinstance(x, (np.floating, np.integer)) else x


def metrics(actual: dict, pred: dict, months=None):
    ms = [m for m in (months or pred.keys()) if m in actual and m in pred and pred[m] is not None and actual[m] is not None
          and math.isfinite(pred[m])]
    if len(ms) < 3:
        return {"n": len(ms), "corr": None, "rmse": None, "mae": None}
    a = np.array([actual[m] for m in ms])
    p = np.array([pred[m] for m in ms])
    corr = float(np.corrcoef(a, p)[0, 1]) if a.std() > 1e-9 and p.std() > 1e-9 else None
    err = p - a
    hit = float(np.mean(np.sign(np.diff(a)) == np.sign(np.array([pred[m] for m in ms[1:]]) - a[:-1]))) if len(ms) > 3 else None
    return {"n": len(ms), "corr": _clean(corr), "rmse": float(np.sqrt((err ** 2).mean())), "mae": float(np.abs(err).mean()),
            "hit": hit, "start": ms[0], "end": ms[-1]}


def pending_month(ind_id):
    s = _state["series"][ind_id]
    return next_month(BY_ID[ind_id], s["months"][-1]) if s["months"] else None


def _actual(ind_id):
    s = _state["series"].get(ind_id) or {"months": [], "values": []}
    return dict(zip(s["months"], s["values"]))


def persist_preds(ind_id):
    s = _state["series"][ind_id]
    return {s["months"][i]: s["values"][i - 1] for i in range(1, len(s["months"]))}


# ------------------------------------------------------------------ 加载
def load_all(force_live=False, background=True, network=True):
    def job():
        try:
            with _lock:
                _state["loading"] = True
            raw = datasource.load(force_live=force_live, network=network)
            series = {i["id"]: datasource.build_series(i["id"], raw) for i in INDICATORS}
            old_pending = dict(_state["pending"])
            with _lock:
                _state["series"] = series
                _state["loaded_at"] = time.strftime("%Y-%m-%d %H:%M")
                _state["last_check"] = _state["loaded_at"]
            for ind in INDICATORS:
                if is_modeled(ind) and series[ind["id"]]["months"]:
                    compute_ar(ind["id"])
                else:
                    _state["ar_progress"][ind["id"]] = 1.0
            for ind in INDICATORS:
                if is_modeled(ind) and series[ind["id"]]["months"]:
                    try:
                        compute_mf(ind["id"])
                    except Exception:  # noqa
                        traceback.print_exc()
            if network and not config.OFFLINE:
                try:
                    markets.load(force=True)
                except Exception:  # noqa
                    traceback.print_exc()
            new_pending = {i["id"]: pending_month(i["id"]) for i in INDICATORS if series[i["id"]]["months"]}
            with _lock:
                _state["pending"] = new_pending
                _state["ready"] = True
                _state["error"] = None
                _state["version"] = uuid.uuid4().hex[:12]
            changed = [i for i, m in new_pending.items() if old_pending and old_pending.get(i) and old_pending.get(i) != m
                       and BY_ID[i]["role"] == "nowcast"]
            auto = store.get_setting("auto_predict", config.AUTO_PREDICT)
            if changed and auto and not config.OFFLINE:
                start_job([(i, new_pending[i], "title", "live") for i in changed], None, force=True, label="新数据到达·自动预测")
        except Exception as e:  # noqa
            traceback.print_exc()
            with _lock:
                _state["error"] = str(e)
        finally:
            with _lock:
                _state["loading"] = False

    if background:
        threading.Thread(target=job, daemon=True).start()
    else:
        job()


def boot():
    """启动：先用快照/缓存秒级就绪（模型走种子缓存），再在后台拉实时数据并重算。"""
    def job():
        load_all(force_live=False, background=False, network=False)
        if not config.OFFLINE:
            load_all(force_live=False, background=False, network=True)

    threading.Thread(target=job, daemon=True).start()


def _load_ar_cache(ind_id):
    global _seed_cache
    f = AR_DIR / f"{ind_id}.json"
    if f.exists():
        try:
            c = json.loads(f.read_text())
            if c.get("version") == AR_VERSION:
                return c
        except Exception:
            pass
    if _seed_cache is None:
        try:
            _seed_cache = json.loads(SEED_FILE.read_text()) if SEED_FILE.exists() else {}
        except Exception:
            _seed_cache = {}
    c = _seed_cache.get(ind_id)
    return c if c and c.get("version") == AR_VERSION else None


def compute_ar(ind_id: str):
    """增量计算：预测 y[t] 只用 y[:t]，与缓存前缀一致的月份直接复用。"""
    ind = BY_ID[ind_id]
    s = _state["series"][ind_id]
    months, values = s["months"], s["values"]
    if len(values) < 40:
        _state["ar"][ind_id] = {"error": "样本不足"}
        _state["ar_progress"][ind_id] = 1.0
        return
    nxt = next_month(ind, months[-1])
    exog = np.array(spring_series(months + [nxt]))[:, None] if ind["spring"] else None
    cfg = [ind["spring"], ind["seasonal"], ind.get("force_d"), config.BACKTEST_START]
    start_idx = next((i for i, m in enumerate(months) if m >= config.BACKTEST_START), len(months))
    cached = _load_ar_cache(ind_id)
    preds, orders, initial_spec, resume = {}, {}, None, start_idx
    if cached and cached.get("cfg") == cfg:
        cm, cv = cached.get("months") or [], cached.get("values") or []
        L = 0
        while L < min(len(cm), len(months)) and cm[L] == months[L] and cv[L] is not None and values[L] is not None and abs(cv[L] - values[L]) < 1e-9:
            L += 1
        for i, m in enumerate(months):
            if i <= L and i >= start_idx and m in (cached.get("preds") or {}):
                preds[m] = cached["preds"][m]
                orders[m] = (cached.get("orders") or {}).get(m)
        if preds:
            last = max(preds, key=lambda m: months.index(m))
            resume = months.index(last) + 1
            if orders.get(last):
                initial_spec = spec_from_label(orders[last])
        if resume >= len(months) + 1 and cached.get("nowcast_month") == nxt and cm == months and cv == values:
            _state["ar"][ind_id] = cached
            _state["ar_progress"][ind_id] = 1.0
            return

    def prog(done, total):
        _state["ar_progress"][ind_id] = done / total

    try:
        new_preds, new_orders, spec, fit = expanding_backtest(values, months, max(resume, start_idx), exog=exog, seasonal=ind["seasonal"],
                                                              progress=prog, force_d=ind.get("force_d"), initial_spec=initial_spec)
    except Exception as e:  # noqa
        _state["ar"][ind_id] = {"error": f"自回归失败：{e}"}
        _state["ar_progress"][ind_id] = 1.0
        return
    preds.update({m: v for m, v in new_preds.items() if m != "__next__"})
    orders.update({m: v for m, v in new_orders.items() if m != "__next__"})
    adf_stat, adf_p, _ = adf_test(values)
    lb_q, lb_p = ljung_box(fit.resid, 12) if fit is not None else (None, None)
    res = {"version": AR_VERSION, "cfg": cfg, "months": months, "values": values,
           "preds": {m: _clean(v) for m, v in preds.items()}, "orders": orders, "nowcast": _clean(new_preds.get("__next__")),
           "nowcast_month": nxt, "final_order": spec.label(), "d": spec.d, "adf_stat": _clean(adf_stat), "adf_p": _clean(adf_p),
           "lb_resid_p": _clean(lb_p), "lb_raw_p": _clean(ljung_box(values, 12)[1]), "computed_at": time.strftime("%Y-%m-%d %H:%M")}
    try:
        (AR_DIR / f"{ind_id}.json").write_text(json.dumps(res))
    except Exception:
        pass
    _state["ar"][ind_id] = res
    _state["ar_progress"][ind_id] = 1.0


def status():
    prog = [v for k, v in _state["ar_progress"].items()]
    return {"ready": _state["ready"], "loading": _state["loading"], "error": _state["error"], "loaded_at": _state["loaded_at"],
            "last_check": _state["last_check"], "version": _state["version"], "ar_progress": (sum(prog) / len(prog)) if prog else 0,
            "data": datasource.status(), "models": llm.available_models(), "model": llm.default_model(),
            "has_key": bool(config.DEEPSEEK_API_KEY or config.ANTHROPIC_API_KEY), "auth_required": bool(config.ACCESS_PASSWORD),
            "backtest_start": config.BACKTEST_START, "llm_earliest": config.LLM_EARLIEST, "leak_split": config.LEAK_SPLIT,
            "refresh_hours": config.REFRESH_HOURS, "auto_predict": bool(store.get_setting("auto_predict", config.AUTO_PREDICT)),
            "runs": store.count_runs(), "n_indicators": {"CN": sum(1 for i in active_indicators() if i["country"] == "CN"),
                                                          "US": sum(1 for i in active_indicators() if i["country"] == "US")},
            "hidden_indicators": [i["id"] for i in INDICATORS if unreachable(i)]}


# ------------------------------------------------------------------ 多因子岭回归（第四种方法）
LEAD = {"pmi_mfg", "pmi_nonmfg", "us_ism_mfg", "us_ism_nonmfg", "us_umcsent", "us_conf_board", "us_fedfunds"}
MF_LAMBDA = 1.0
MF_MAX_FEATURES = 8


def _shift(m, k):
    t = int(m[:4]) * 12 + int(m[5:7]) - 1 + k
    return f"{t // 12}-{t % 12 + 1:02d}"


def _nearest_before(d, m, back=2):
    """取 m 当月值，缺失则向前找最多 back 个月（1–2 月合并等）。"""
    for k in range(0, back + 1):
        v = d.get(_shift(m, -k))
        if v is not None:
            return v
    return None


def compute_mf(ind_id: str):
    """多因子岭回归：y_t = α + Σβ_i·z_i,t（标准化特征：自身滞后 + 同国关联指标滞后一期/领先指标当期），扩展窗口逐月重估。"""
    ind = BY_ID[ind_id]
    s = _state["series"][ind_id]
    months, values = s["months"], s["values"]
    if len(values) < 48:
        _state["mf"][ind_id] = {"error": "样本不足"}
        return
    ym = dict(zip(months, values))
    pm = pending_month(ind_id)
    cands = []
    for o in INDICATORS:
        if o["country"] != ind["country"] or o["id"] == ind_id or o["freq"] != "M":
            continue
        so = _state["series"].get(o["id"])
        if not so or len(so["months"]) < 48:
            continue
        cands.append((o["id"], o["short"], dict(zip(so["months"], so["values"]))))

    def row_for(i, t):
        r = {"y_lag1": values[i - 1] if i >= 1 else None, "y_lag2": values[i - 2] if i >= 2 else None, "y_lag12": ym.get(_shift(t, -12))}
        for key, short, d in cands:
            r[key] = _nearest_before(d, t if key in LEAD else _shift(t, -1))
        return r

    rows = [row_for(i, t) for i, t in enumerate(months)]
    now_row = {"y_lag1": values[-1], "y_lag2": values[-2], "y_lag12": ym.get(_shift(pm, -12))}
    for key, short, d in cands:
        now_row[key] = _nearest_before(d, pm if key in LEAD else _shift(pm, -1), back=1)
    names = list(rows[-1].keys())
    labels = {"y_lag1": "自身滞后1期", "y_lag2": "自身滞后2期", "y_lag12": "自身滞后12期", **{k: sh + ("（当期）" if k in LEAD else "（滞后1期）") for k, sh, _ in cands}}
    start_idx = next((i for i, m in enumerate(months) if m >= config.BACKTEST_START), len(months))
    screen_n = max(36, min(start_idx, 72))
    # 特征筛选：只用回测起点之前的样本，按 |corr| 取前 N（避免用未来信息选特征）
    y0 = np.array(values[:screen_n], dtype=float)
    scores = []
    for nm in names:
        col = np.array([np.nan if rows[i].get(nm) is None else rows[i][nm] for i in range(screen_n)], dtype=float)
        ok = ~np.isnan(col) & ~np.isnan(y0)
        if ok.sum() < 24 or col[ok].std() < 1e-9:
            continue
        c = float(np.corrcoef(col[ok], y0[ok])[0, 1])
        if math.isfinite(c):
            scores.append((abs(c), nm))
    scores.sort(reverse=True)
    sel = [nm for _, nm in scores[:MF_MAX_FEATURES]]
    if "y_lag1" not in sel:
        sel = ["y_lag1"] + sel[:MF_MAX_FEATURES - 1]
    X = np.array([[np.nan if rows[i].get(nm) is None else rows[i][nm] for nm in sel] for i in range(len(months))], dtype=float)
    Y = np.array(values, dtype=float)

    def fit(upto):
        ok = ~np.isnan(X[:upto]).any(axis=1) & ~np.isnan(Y[:upto])
        Xa, Ya = X[:upto][ok], Y[:upto][ok]
        if len(Ya) < 30:
            return None
        mu, sd = Xa.mean(axis=0), Xa.std(axis=0)
        sd[sd < 1e-9] = 1.0
        Z = (Xa - mu) / sd
        ymu = Ya.mean()
        A = Z.T @ Z + MF_LAMBDA * np.eye(Z.shape[1])
        beta = np.linalg.solve(A, Z.T @ (Ya - ymu))
        return mu, sd, ymu, beta

    def predict(model, xrow):
        mu, sd, ymu, beta = model
        z = (np.array(xrow, dtype=float) - mu) / sd
        z = np.where(np.isnan(z), 0.0, z)
        return float(ymu + z @ beta)

    preds = {}
    model = None
    for i in range(start_idx, len(months)):
        if model is None or months[i].endswith("-01") or (i - start_idx) % 3 == 0:
            model = fit(i) or model
        if model is None:
            continue
        preds[months[i]] = _clean(predict(model, X[i]))
    final = fit(len(months))
    nowcast = None
    if final:
        nowcast = _clean(predict(final, [np.nan if now_row.get(nm) is None else now_row[nm] for nm in sel]))
    coef = {labels.get(nm, nm): _clean(float(b)) for nm, b in zip(sel, final[3])} if final else {}
    _state["mf"][ind_id] = {"preds": preds, "nowcast": nowcast, "nowcast_month": pm, "features": [labels.get(nm, nm) for nm in sel],
                            "coef": coef, "n_train": int((~np.isnan(X).any(axis=1)).sum()), "lambda": MF_LAMBDA,
                            "screen_window": f"{months[0]}–{months[min(screen_n, len(months)) - 1]}", "computed_at": time.strftime("%Y-%m-%d %H:%M")}


def mf_preds(ind_id):
    return (_state["mf"].get(ind_id) or {}).get("preds") or {}


# ------------------------------------------------------------------ 宏观 → 市场传导（事件回归）
def _ols(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = len(x)
    if n < 12 or x.std() < 1e-12 or y.std() < 1e-12:
        return None
    xb, yb = x.mean(), y.mean()
    sxx = ((x - xb) ** 2).sum()
    beta = ((x - xb) * (y - yb)).sum() / sxx
    alpha = yb - beta * xb
    resid = y - alpha - beta * x
    se = math.sqrt((resid ** 2).sum() / (n - 2) / sxx) if n > 2 else float("nan")
    corr = float(np.corrcoef(x, y)[0, 1])
    return {"n": n, "beta": float(beta), "alpha": float(alpha), "se": _clean(se), "t": _clean(beta / se) if se and se > 0 else None,
            "r2": _clean(corr ** 2), "corr": _clean(corr), "beta_std": _clean(beta * x.std()),
            "pos_mean": _clean(float(y[x > 0].mean())) if (x > 0).any() else None, "neg_mean": _clean(float(y[x < 0].mean())) if (x < 0).any() else None,
            "hit": _clean(float(np.mean(np.sign(x[x != 0]) == np.sign(y[x != 0])))) if (x != 0).any() else None}


def transmission(ind_id, start="2010-01"):
    ind = BY_ID[ind_id]
    s = _state["series"].get(ind_id)
    if not s or not s["months"]:
        return {"error": "无数据"}
    actual = _actual(ind_id)
    arp = (_state["ar"].get(ind_id) or {}).get("preds") or {}
    pp = persist_preds(ind_id)
    rel = 0 if "当月" in ind["release"] else (2 if "隔月" in ind["release"] else 1)
    sur, ref_used = {}, {}
    for m in s["months"]:
        if m < start:
            continue
        ref = arp.get(m)
        src = "ar"
        if ref is None:
            ref, src = pp.get(m), "persist"
        if ref is None or actual.get(m) is None or not math.isfinite(ref):
            continue
        sur[m] = actual[m] - ref
        ref_used[m] = src
    th = theory.for_indicator(ind)
    sd = float(np.std(list(sur.values()))) if len(sur) >= 12 else None
    out = {"indicator": ind_id, "name": ind["name"], "unit": ind["unit"], "release_lag": rel, "n_surprise": len(sur), "surprise_sd": _clean(sd),
           "sample": f"{min(sur)}–{max(sur)}" if sur else None, "ref_mix": {"ar": sum(1 for v in ref_used.values() if v == "ar"), "persist": sum(1 for v in ref_used.values() if v == "persist")},
           "theory": th, "markets": []}
    if not sur:
        return out
    b = basis(ind_id)
    con = (b or {}).get("conclusion") or {}
    pred = con.get("value")
    ar_now = ((b or {}).get("ar") or {}).get("value")
    ref_now = ar_now if ar_now is not None else (b or {}).get("last_value")
    implied = (pred - ref_now) if (pred is not None and ref_now is not None) else None
    z = implied / sd if (implied is not None and sd) else None
    # 各方法各自的隐含惊喜（便于对比：AI 与统计模型分歧越大，隐含冲击越大）
    by_method = {}
    for key, val in (("persist", ((b or {}).get("persist") or {}).get("value")), ("mf", ((b or {}).get("mf") or {}).get("value")),
                     ("ai", ((b or {}).get("ai") or {}).get("value"))):
        if val is not None and ref_now is not None and sd:
            by_method[key] = {"pred": _clean(val), "surprise": _clean(val - ref_now), "z": _clean((val - ref_now) / sd)}
    out["implied"] = {"pred": pred, "ref": ref_now, "ref_kind": "SARIMAX 事前预测" if ar_now is not None else "上期值", "surprise": _clean(implied), "z": _clean(z),
                      "method": con.get("used"), "by_method": by_method, "target_label": (b or {}).get("target_label")}
    for key, name, mkt, typ, secid, tx in markets.META:
        resp = markets.responses(key)
        pairs, pairs2, ms = [], [], []
        for m in sorted(sur):
            m0, m1 = _shift(m, rel), _shift(m, rel + 1)
            if m0 in resp:
                pairs.append((sur[m], resp[m0]))
                ms.append(m)
                pairs2.append((sur[m], resp[m0] + resp.get(m1, 0.0)))
        if len(pairs) < 24:
            continue
        r0 = _ols([p[0] for p in pairs], [p[1] for p in pairs])
        r2m = _ols([p[0] for p in pairs2], [p[1] for p in pairs2])
        rec = _ols([p[0] for p in pairs[-60:]], [p[1] for p in pairs[-60:]])
        if not r0:
            continue
        sign_theory = th["sign"].get(key, 0)
        out["markets"].append({"key": key, "name": name, "market": mkt, "type": typ, "unit": "%" if typ == "equity" else "bp",
                               "release_month": r0, "two_month": r2m, "recent5y": rec, "sign_theory": sign_theory,
                               "consistent": (None if sign_theory == 0 or r0.get("beta_std") is None else (sign_theory > 0) == (r0["beta_std"] > 0)),
                               "implied_move": _clean(r0["beta_std"] * z) if (z is not None and r0.get("beta_std") is not None) else None,
                               "implied_by_method": {k: _clean(r0["beta_std"] * v["z"]) for k, v in by_method.items() if v.get("z") is not None and r0.get("beta_std") is not None},
                               "months": ms[-3:]})
    return out


# ------------------------------------------------------------------ 发布日历 / 预测对象 / 预测依据
def month_label(m, freq="M"):
    if not m:
        return "—"
    if freq == "Q":
        return f"{m[:4]}年Q{(int(m[5:7]) + 2) // 3}"
    return f"{m[:4]}年{int(m[5:7])}月"


def _nth_weekday(y, mo, wd, n):
    d = date(y, mo, 1)
    return d + timedelta(days=(wd - d.weekday()) % 7 + 7 * (n - 1))


def _nth_workday(y, mo, n):
    d, c = date(y, mo, 1), 0
    while True:
        if d.weekday() < 5:
            c += 1
            if c == n:
                return d
        d += timedelta(days=1)


def _last_weekday(y, mo, wd):
    last = date(y, mo, calendar.monthrange(y, mo)[1])
    return last - timedelta(days=(last.weekday() - wd) % 7)


def _last_day(y, mo):
    return date(y, mo, calendar.monthrange(y, mo)[1])


def next_release(ind, month):
    """按 indicators.release 的发布规律估计 month 期数据的公布日（ISO）；无法解析返回 None。"""
    if not month:
        return None
    r = ind["release"]
    y, mo = int(month[:4]), int(month[5:7])

    def ym(k):
        t = y * 12 + mo - 1 + k
        return t // 12, t % 12 + 1

    try:
        if ind["freq"] == "Q":
            ny, nm = ym(1)
            if "月末" in r:
                return _last_day(ny, nm).isoformat()
            g = re.search(r"(\d+)\s*[–-]\s*(\d+)", r)
            return date(ny, nm, int(g.group(2)) if g else 20).isoformat()
        if r.startswith("每"):
            return None
        if "当月" in r:
            if "最后一个周二" in r:
                return _last_weekday(y, mo, 1).isoformat()
            if "中旬" in r:
                return date(y, mo, 15).isoformat()
            if "下旬" in r:
                return date(y, mo, 25).isoformat()
            if "月末" in r or "月底" in r:
                return _last_day(y, mo).isoformat()
        ny, nm = ym(2 if "隔月" in r else 1)
        if "第一个周五" in r:
            return _nth_weekday(ny, nm, 4, 1).isoformat()
        if "第一个工作日" in r:
            return _nth_workday(ny, nm, 1).isoformat()
        if "第三个工作日" in r:
            return _nth_workday(ny, nm, 3).isoformat()
        g = re.search(r"(\d+)\s*[–-]\s*(\d+)\s*日", r)
        if g:
            return date(ny, nm, int(g.group(2))).isoformat()
        g = re.search(r"(\d+)\s*日", r)
        if g:
            return date(ny, nm, int(g.group(1))).isoformat()
        if "月初" in r:
            return date(ny, nm, 5).isoformat()
        if "中旬" in r:
            return date(ny, nm, 15).isoformat()
        if "下旬" in r:
            return date(ny, nm, 25).isoformat()
        if "月底" in r or "月末" in r:
            return _last_day(ny, nm).isoformat()
    except Exception:
        return None
    return None


def _fmt(v, unit=""):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if unit in ("亿元", "千人", "千套"):
        return f"{v:,.0f}"
    return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.1f}"


def _fc(v, nd=2):
    return "—" if v is None else f"{v:.{nd}f}"


def _pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def basis(ind_id, sm=None):
    """预测对象 + 三种方法各自的依据（数值、模型诊断、回测表现）+ 综合结论。"""
    ind = BY_ID[ind_id]
    s = _state["series"].get(ind_id)
    if not s or not s["months"]:
        return None
    unit = ind["unit"]
    pm = pending_month(ind_id)
    modeled = is_modeled(ind)
    if sm is None and modeled:
        sm = summary(ind_id)
    ar = _state["ar"].get(ind_id) or {}
    actual = _actual(ind_id)
    label = month_label(pm, ind["freq"])
    rel = next_release(ind, pm)
    last_m, last_v = s["months"][-1], s["values"][-1]
    out = {"target_month": pm, "target_label": label, "release_est": rel, "release_rule": ind["release"], "last_month": last_m,
           "last_value": last_v, "modeled": modeled, "theory": ind.get("theory")}
    pc = (sm or {}).get("persist") or {}
    out["persist"] = {"value": last_v, "ref_month": last_m, "corr": pc.get("corr"), "hit": pc.get("hit"), "n": pc.get("n"),
                      "text": (f"取最近一期（{month_label(last_m, ind['freq'])}）实际值 {_fmt(last_v, unit)}{unit} 作为 {label} 的预测。"
                               + (f"{config.BACKTEST_START} 以来该做法与实际值的相关系数 {_fc(pc.get('corr'))}（{pc.get('n')} 期回测）。" if pc else "")
                               + "逻辑：宏观指标存在惯性，上期值是无新增信息条件下的基准。")}
    out["ar"] = None
    if ar.get("preds"):
        am = (sm or {}).get("ar") or {}
        ms = [m for m in sorted(ar["preds"]) if m in actual][-36:]
        res = [ar["preds"][m] - actual[m] for m in ms if ar["preds"].get(m) is not None and actual.get(m) is not None]
        sigma = float(np.std(res)) if len(res) >= 6 else None
        v = ar.get("nowcast") if ar.get("nowcast_month") == pm else None
        band = [v - 1.28 * sigma, v + 1.28 * sigma] if (v is not None and sigma) else None
        recent = [[m, actual.get(m), ar["preds"].get(m)] for m in ms[-6:]]
        d = ar.get("d") or 0
        out["ar"] = {"value": v, "order": ar.get("final_order"), "d": d, "adf_p": ar.get("adf_p"), "lb_resid_p": ar.get("lb_resid_p"),
                     "spring": ind["spring"], "seasonal": ind["seasonal"], "n_obs": len(s["months"]), "sample": f"{s['months'][0]} 至 {last_m}",
                     "corr": am.get("corr"), "rmse": am.get("rmse"), "hit": am.get("hit"), "sigma": sigma, "band": band, "recent": recent,
                     "text": (f"SARIMAX{ar.get('final_order') or ''}：样本 {s['months'][0]}–{last_m} 共 {len(s['months'])} 期；"
                              f"ADF 单位根检验 p={_fc(ar.get('adf_p'), 3)}（{'平稳，直接建模' if d == 0 else '非平稳，一阶差分后建模'}）；"
                              + ("含 12 期季节项；" if ind["seasonal"] else "") + ("含春节假期比例外生变量；" if ind["spring"] else "")
                              + f"每年 1 月按 AIC 重选阶数，扩展窗口逐月只用截至上月的数据重估（无未来信息）。"
                              + (f"{config.BACKTEST_START} 以来回测相关系数 {_fc(am.get('corr'))}，RMSE {_fc(am.get('rmse'))}，方向命中率 {_pct(am.get('hit'))}；" if am else "")
                              + (f"近 {len(res)} 期残差 σ={_fc(sigma)}，80% 置信区间 [{_fmt(band[0], unit)}, {_fmt(band[1], unit)}]。" if band else ""))}
    out["mf"] = None
    mf = _state["mf"].get(ind_id) or {}
    if mf.get("preds"):
        mm = (sm or {}).get("mf") or {}
        v = mf.get("nowcast") if mf.get("nowcast_month") == pm else None
        top = sorted((mf.get("coef") or {}).items(), key=lambda kv: -abs(kv[1] or 0))[:5]
        out["mf"] = {"value": v, "features": mf.get("features"), "coef": mf.get("coef"), "corr": mm.get("corr"), "rmse": mm.get("rmse"), "hit": mm.get("hit"), "n_train": mf.get("n_train"),
                     "text": (f"多因子岭回归（λ={mf.get('lambda')}，特征标准化后估计）：特征 {len(mf.get('features') or [])} 个——" + "、".join(mf.get("features") or [])
                              + f"；特征按回测起点前样本（{mf.get('screen_window')}）的相关性筛选，避免用未来信息选变量；扩展窗口逐季重估。"
                              + f"最新系数（标准化，绝对值前 5）：" + "，".join(f"{k} {v:+.2f}" for k, v in top) + "。"
                              + (f"{config.BACKTEST_START} 以来回测相关系数 {_fc(mm.get('corr'))}，RMSE {_fc(mm.get('rmse'))}，方向命中率 {_pct(mm.get('hit'))}。" if mm else ""))}
    live = store.latest_live(ind_id, pm) if modeled else None
    out["ai"] = live
    rec = (sm or {}).get("recommend") if sm else "ref"
    why = (sm or {}).get("why") if sm else "参考指标：仅展示最新数据与走势，不做预测"
    cand = {"persist": out["persist"]["value"], "ar": (out["ar"] or {}).get("value"), "mf": (out["mf"] or {}).get("value"), "ai": (live or {}).get("value")}
    val, used, note = cand.get(rec), rec, ""
    if rec == "ai" and val is None:
        used = "ar" if cand["ar"] is not None else ("mf" if cand["mf"] is not None else "persist")
        val = cand[used]
        note = "AI 研判尚未运行，暂以 " + {"ar": "SARIMAX", "mf": "多因子回归", "persist": "沿用上期"}[used] + " 作为占位值；点击「AI 预测」后以 AI 结果为准。"
    if val is None and used in ("ar", "mf"):
        used, val = "persist", cand["persist"]
    names = {"persist": "沿用上期", "ar": "SARIMAX", "mf": "多因子回归", "ai": "AI 研判", "ref": "参考"}
    band = (out["ar"] or {}).get("band") if used == "ar" else ([live["low"], live["high"]] if used == "ai" and live and live.get("low") is not None else None)
    out["conclusion"] = {"method": rec, "used": used, "value": val, "band": band, "why": why, "note": note,
                         "text": ("" if not modeled else f"预测对象：{label} {ind['name']}（{'预计 ' + rel + ' 公布' if rel else ind['release']}）。"
                                  f"推荐方法：{names[rec]}（{why}）。预测值 {_fmt(val, unit)}{unit}"
                                  + (f"，区间 {_fmt(band[0], unit)}~{_fmt(band[1], unit)}" if band else "") + "。" + note)}
    return out


def predictable_months(ind_id):
    """可预测的月份：当期（实时，尚未公布）+ 历史回测月（研报可得的 LLM_EARLIEST 起）。"""
    s = _state["series"].get(ind_id)
    if not s or not s["months"]:
        return {"live": None, "backtest": []}
    return {"live": pending_month(ind_id), "backtest": [m for m in s["months"] if m >= config.LLM_EARLIEST][::-1]}


def calendar_upcoming(days=45):
    """未来若干天内的发布日历（估计），附带当前推荐预测值。"""
    today = date.today()
    out = []
    for ind in active_indicators():
        s = _state["series"].get(ind["id"])
        if not s or not s["months"]:
            continue
        pm = pending_month(ind["id"])
        rel = next_release(ind, pm)
        if not rel:
            continue
        d = date.fromisoformat(rel)
        if d < today - timedelta(days=3) or d > today + timedelta(days=days):
            continue
        b = basis(ind["id"]) if is_modeled(ind) else None
        out.append({"id": ind["id"], "name": ind["name"], "short": ind["short"], "country": ind["country"], "unit": ind["unit"], "freq": ind["freq"],
                    "target_month": pm, "target_label": month_label(pm, ind["freq"]), "date": rel, "days": (d - today).days,
                    "last_value": s["values"][-1], "pred": (b or {}).get("conclusion", {}).get("value"), "method": (b or {}).get("conclusion", {}).get("used"),
                    "ai": bool((b or {}).get("ai")), "release": ind["release"]})
    out.sort(key=lambda x: (x["date"], x["country"]))
    return out


# ------------------------------------------------------------------ 汇总
def recommend(ind, persist_corr, ar_corr, llm_m=None, mf_corr=None):
    if not is_modeled(ind):
        return "ref", "参考指标：仅展示，不做实时预测"
    if persist_corr is not None and persist_corr >= 0.8:
        if mf_corr is not None and mf_corr - persist_corr >= 0.05:
            return "mf", f"多因子回归回测相关性 {mf_corr:.2f} 显著优于沿用上期 {persist_corr:.2f}"
        return "persist", f"与上期相关性 {persist_corr:.2f} ≥ 0.8，惯性极强，沿用上期即为最优"
    best_stat = max([(ar_corr or -1, "ar"), (mf_corr or -1, "mf")])
    if best_stat[1] == "mf" and mf_corr is not None and mf_corr >= 0.5 and mf_corr - (persist_corr if persist_corr is not None else -1) >= 0.05 and mf_corr - (ar_corr or -1) >= 0.03:
        return "mf", f"多因子回归回测相关性 {mf_corr:.2f} 优于 SARIMAX {ar_corr if ar_corr is not None else float('nan'):.2f} 与沿用上期 {persist_corr if persist_corr is not None else float('nan'):.2f}"
    if llm_m and llm_m.get("n", 0) >= 12 and llm_m.get("corr") is not None:
        cand = [("persist", (llm_m.get("persist_same") or {}).get("corr")), ("ar", (llm_m.get("ar_same") or {}).get("corr")), ("ai", llm_m["corr"])]
        cand = [(k, v) for k, v in cand if v is not None]
        best = max(cand, key=lambda x: x[1])
        names = {"persist": "沿用上期", "ar": "SARIMAX", "ai": "AI 研判"}
        return best[0], "同窗口回测相关性：" + "，".join(f"{names[k]} {v:.2f}" for k, v in cand)
    pc = persist_corr if persist_corr is not None else -1
    if ar_corr is not None and ar_corr >= 0.5 and ar_corr - pc >= 0.05:
        return "ar", f"SARIMAX 回测相关性 {ar_corr:.2f} 优于沿用上期 {pc:.2f}" + ("，含春节外生变量" if ind["spring"] else "")
    if pc >= 0.7:
        return "persist", f"与上期中高相关（{pc:.2f}），统计模型无显著提升"
    return "ai", "历史惯性弱、外生冲击多：以 AI 读研报 + 数据研判为主"


def summary(ind_id, start=None, end=None, model=None):
    ind = BY_ID[ind_id]
    s = _state["series"].get(ind_id)
    if not s or not s["months"]:
        return None
    actual = _actual(ind_id)
    start = start or config.BACKTEST_START
    end = end or s["months"][-1]
    win = [m for m in s["months"] if start <= m <= end]
    pp = persist_preds(ind_id)
    ar = _state["ar"].get(ind_id) or {}
    arp = ar.get("preds") or {}
    mfp = mf_preds(ind_id)
    out = {"persist": metrics(actual, pp, win), "ar": metrics(actual, arp, win) if arp else None, "mf": metrics(actual, mfp, win) if mfp else None, "llm": {}}
    for mode in LLM_MODES:
        lp = store.latest_preds(ind_id, mode, "backtest", model)
        lp = {m: v for m, v in lp.items() if start <= m <= end}
        if lp:
            lm = sorted(lp)
            out["llm"][mode] = {**metrics(actual, lp, lm), "persist_same": metrics(actual, pp, lm), "ar_same": metrics(actual, arp, lm) if arp else None}
    rec, why = recommend(ind, out["persist"]["corr"], (out["ar"] or {}).get("corr"), out["llm"].get("title"), (out["mf"] or {}).get("corr"))
    out.update(recommend=rec, why=why)
    return out


def overview(country=None):
    rows = []
    for ind in active_indicators():
        if country and ind["country"] != country:
            continue
        s = _state["series"].get(ind["id"])
        if not s or not s["months"]:
            rows.append({"id": ind["id"], "name": ind["name"], "short": ind["short"], "unit": ind["unit"], "group": ind["group"],
                         "country": ind["country"], "role": ind["role"], "freq": ind["freq"], "release": ind["release"],
                         "missing": True, "notes": (s or {}).get("notes", [])})
            continue
        ar = _state["ar"].get(ind["id"]) or {}
        mf = _state["mf"].get(ind["id"]) or {}
        pm = pending_month(ind["id"])
        sm = summary(ind["id"]) if is_modeled(ind) else None
        live = store.latest_live(ind["id"], pm)
        rows.append({
            "id": ind["id"], "name": ind["name"], "short": ind["short"], "unit": ind["unit"], "group": ind["group"], "country": ind["country"],
            "role": ind["role"], "freq": ind["freq"], "release": ind["release"], "theory": ind.get("theory"), "spring": ind["spring"],
            "last_month": s["months"][-1], "last_value": s["values"][-1], "prev_value": s["values"][-2] if len(s["values"]) > 1 else None,
            "history": list(zip(s["months"][-24:], s["values"][-24:])), "pending_month": pm, "persist_pred": s["values"][-1],
            "ar_pred": ar.get("nowcast") if ar.get("nowcast_month") == pm else None, "ar_order": ar.get("final_order"), "adf_p": ar.get("adf_p"),
            "mf_pred": mf.get("nowcast") if mf.get("nowcast_month") == pm else None, "mf_corr": ((sm or {}).get("mf") or {}).get("corr") if sm else None,
            "mf_features": mf.get("features"),
            "persist_corr": (sm or {}).get("persist", {}).get("corr") if sm else None, "ar_corr": ((sm or {}).get("ar") or {}).get("corr") if sm else None,
            "llm_corr": {k: v.get("corr") for k, v in ((sm or {}).get("llm") or {}).items()} if sm else {},
            "recommend": (sm or {}).get("recommend") if sm else "ref", "why": (sm or {}).get("why") if sm else "参考指标",
            "ai": live, "notes": s.get("notes", []), "basis": basis(ind["id"], sm), "release_est": next_release(ind, pm),
        })
    return rows


def series_payload(ind_id, model=None):
    s = _state["series"][ind_id]
    ar = _state["ar"].get(ind_id) or {}
    mf = _state["mf"].get(ind_id) or {}
    out = {"months": s["months"], "values": s["values"], "persist": persist_preds(ind_id) if s["months"] else {}, "ar": ar.get("preds") or {},
           "mf": mf.get("preds") or {}, "mf_nowcast": mf.get("nowcast"), "mf_info": {k: mf.get(k) for k in ("features", "coef", "n_train", "lambda", "screen_window")},
           "ar_orders": ar.get("orders") or {}, "llm": {}, "pending_month": pending_month(ind_id), "ar_nowcast": ar.get("nowcast"),
           "diag": {k: ar.get(k) for k in ("adf_stat", "adf_p", "lb_resid_p", "lb_raw_p", "final_order", "d")}, "notes": s.get("notes", [])}
    for mode in LLM_MODES:
        lp = store.latest_preds(ind_id, mode, "backtest", model)
        if lp:
            out["llm"][mode] = lp
    live = [r for r in store.list_runs(indicator=ind_id, source="live", limit=20, ok_only=True)]
    out["live"] = live[:5]
    out["basis"] = basis(ind_id)
    out["months_predictable"] = predictable_months(ind_id)
    return out


def backtest_table(start=None, end=None, model=None, country=None):
    rows = []
    for ind in active_indicators():
        if not is_modeled(ind) or (country and ind["country"] != country):
            continue
        sm = summary(ind["id"], start, end, model)
        ar = _state["ar"].get(ind["id"]) or {}
        if sm is None:
            continue
        rows.append({"id": ind["id"], "name": ind["name"], "country": ind["country"], "group": ind["group"], "role": ind["role"], "spring": ind["spring"],
                     "persist": sm["persist"], "ar": sm["ar"], "mf": sm.get("mf"), "llm": sm["llm"], "recommend": sm["recommend"], "why": sm["why"],
                     "mf_features": (_state["mf"].get(ind["id"]) or {}).get("features"),
                     "order": ar.get("final_order"), "adf_p": ar.get("adf_p"), "paper": ind.get("paper")})
    return rows


def leak_check(ind_id, mode="title", model=None, split=None):
    split = split or config.LEAK_SPLIT
    actual = _actual(ind_id)
    lp = store.latest_preds(ind_id, mode, "backtest", model)
    before, after = sorted(m for m in lp if m < split), sorted(m for m in lp if m >= split)
    pp = persist_preds(ind_id)
    return {"split": split, "before": metrics(actual, lp, before), "after": metrics(actual, lp, after),
            "persist_before": metrics(actual, pp, before), "persist_after": metrics(actual, pp, after)}


def data_table(country=None, n_months: int = 24, freq="M"):
    series = _state["series"]
    ids = [i["id"] for i in INDICATORS if (not country or i["country"] == country) and i["freq"] == freq and series.get(i["id"], {}).get("months")]
    months = sorted({m for i in ids for m in series[i]["months"]})[-n_months:]
    cols = []
    for i in ids:
        ind = BY_ID[i]
        s = series[i]
        lk = dict(zip(s["months"], s["values"]))
        cols.append({"id": i, "name": ind["name"], "short": ind["short"], "unit": ind["unit"], "role": ind["role"], "group": ind["group"],
                     "country": ind["country"], "latest_month": s["months"][-1], "latest": s["values"][-1], "values": [lk.get(m) for m in months]})
    return {"months": months, "columns": cols}


# ------------------------------------------------------------------ AI 研判
def related_for(ind):
    """同国家的关联指标最新值（同组优先 + 景气/利率组）。"""
    out = []
    for o in INDICATORS:
        if o["country"] != ind["country"] or o["id"] == ind["id"]:
            continue
        if o["group"] not in (ind["group"], "景气", "货币利率", "就业") and ind["group"] not in ("增长",):
            continue
        s = _state["series"].get(o["id"])
        if s and s["months"]:
            out.append((o["name"], s["months"][-1], s["values"][-1], o["unit"]))
    return out[:12]


def build_ctx(ind_id, month, mode, cutoff=None):
    ind = BY_ID[ind_id]
    s = _state["series"][ind_id]
    idx = [i for i, m in enumerate(s["months"]) if m < month]
    hist = [(s["months"][i], s["values"][i]) for i in idx[-24:]]
    ar = _state["ar"].get(ind_id) or {}
    ar_val = (ar.get("preds") or {}).get(month)
    if ar_val is None and ar.get("nowcast_month") == month:
        ar_val = ar.get("nowcast")
    sm = summary(ind_id) if is_modeled(ind) else None
    mf = _state["mf"].get(ind_id) or {}
    mf_val = (mf.get("preds") or {}).get(month)
    if mf_val is None and mf.get("nowcast_month") == month:
        mf_val = mf.get("nowcast")
    ctx = {"history": hist, "persist": hist[-1][1] if hist else None, "ar": ar_val, "mf": mf_val, "mf_features": mf.get("features"), "order": (ar.get("orders") or {}).get(month) or ar.get("final_order"),
           "ar_corr": ((sm or {}).get("ar") or {}).get("corr") if sm else None, "related": related_for(ind) if month >= (s["months"][-1] if s["months"] else "") else []}
    info = {"n_titles": 0, "n_chunks": 0, "titles": []}
    if mode != "data":
        items = reports.fetch_month(month, cutoff)
        sel, supplemented = reports.select_titles(items, ind_id)
        info.update(n_titles=len(sel), titles=[{"title": t["title"], "org": t["org"], "date": t["date"], "url": t.get("url")} for t in sel], supplemented=supplemented)
        ctx["titles"] = reports.format_titles(sel)
        if mode == "chunk":
            chunks, dropped = reports.select_chunks(sel, ind_id)
            ctx["chunks"] = "\n".join(chunks)
            info.update(n_chunks=len(chunks), dropped=dropped)
    return ctx, info


def run_llm(ind_id, month, mode="title", model=None, source="backtest", job_id=None):
    ind = BY_ID[ind_id]
    model = model or llm.default_model()
    today = date.today().isoformat()
    cutoff = min(month_end(month), today)
    rec = {"source": source, "job_id": job_id, "indicator": ind_id, "target_month": month, "mode": mode, "model": model, "cutoff": cutoff}
    try:
        if cutoff < f"{month}-01":
            raise RuntimeError(f"{month} 尚未开始")
        ctx, info = build_ctx(ind_id, month, mode, cutoff if cutoff < month_end(month) else None)
        rec.update(n_titles=info["n_titles"], n_chunks=info["n_chunks"], ar_ref=ctx.get("ar"))
        if mode in ("title", "title_ar", "chunk") and not (ctx.get("titles") or ctx.get("chunks")):
            mode_used = "data"
        else:
            mode_used = mode
        custom = store.get_setting("predict_requirements", "") or ""
        r = llm.predict(ind, month, ctx, mode_used, model, custom)
        rec.update(value=r["value"], low=r["low"], high=r["high"], confidence=r["confidence"], reason=r["reason"],
                   analysis={**r["analysis"], "titles": info["titles"][:40], "mode_used": mode_used, "related": ctx.get("related")},
                   thinking=(r.get("reasoning") or "")[:4000], answer_raw=r["raw"][:6000], prompt=r["prompt"], latency=r["latency"],
                   tokens=r["tokens"], model=r["model"], error=r["error"])
    except Exception as e:  # noqa
        rec["error"] = str(e)
    rec["id"] = store.add_run(rec)
    return rec


def start_job(items, model=None, force=False, label=""):
    model = model or llm.default_model()
    jid = uuid.uuid4().hex[:10]
    todo, skipped = [], 0
    for ind_id, month, mode, source in items:
        if source == "backtest" and not force and store.has_backtest_run(ind_id, mode, month, model):
            skipped += 1
            continue
        todo.append((ind_id, month, mode, source))
    job = {"id": jid, "label": label, "model": model, "total": len(todo), "done": 0, "ok": 0, "failed": 0, "skipped": skipped,
           "status": "running" if todo else "done", "started": time.strftime("%Y-%m-%d %H:%M:%S"), "finished": None, "errors": [], "results": []}
    JOBS[jid] = job

    def one(it):
        r = run_llm(it[0], it[1], it[2], model, it[3], jid)
        with _lock:
            job["done"] += 1
            if r.get("value") is not None:
                job["ok"] += 1
            else:
                job["failed"] += 1
                job["errors"].append(f"{BY_ID[it[0]]['short']} {it[1]}：{r.get('error')}")
            job["results"].append({k: r.get(k) for k in ("id", "indicator", "target_month", "mode", "value", "low", "high", "confidence", "reason", "error", "n_titles")})

    def runner():
        with ThreadPoolExecutor(max(1, config.LLM_CONCURRENCY)) as ex:
            list(ex.map(one, todo))
        job["status"] = "done"
        job["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if todo:
        threading.Thread(target=runner, daemon=True).start()
    else:
        job["finished"] = job["started"]
    return job


def backtest_months(ind_id, start, end):
    s = _state["series"][ind_id]
    start = max(start, config.LLM_EARLIEST)
    return [m for m in s["months"] if start <= m <= end]


def update_and_predict(mode="title", model=None, country=None, indicators=None):
    if UPDATE["running"]:
        return UPDATE
    UPDATE.update(running=True, stage="正在从东方财富 / FRED 拉取最新数据…", started=time.strftime("%H:%M:%S"), job_id=None, error=None, finished=None)

    def run():
        try:
            load_all(force_live=True, background=False)
            UPDATE["stage"] = "数据已更新，正在 AI 研判…"
            ids = indicators or [i["id"] for i in INDICATORS if i["role"] == "nowcast" and (not country or i["country"] == country)]
            items = [(i, pending_month(i), mode, "live") for i in ids if _state["series"].get(i, {}).get("months")]
            job = start_job(items, model, force=True, label="更新数据并预测")
            UPDATE["job_id"] = job["id"]
        except Exception as e:  # noqa
            UPDATE["error"] = str(e)
        finally:
            UPDATE["running"] = False
            UPDATE["finished"] = time.strftime("%H:%M:%S")

    threading.Thread(target=run, daemon=True).start()
    return UPDATE


def ask_context(max_months: int = 12) -> str:
    lines = []
    for country, label in (("CN", "中国"), ("US", "美国")):
        lines.append(f"【{label}最新宏观数据】")
        for c in data_table(country, max_months)["columns"] + data_table(country, 8, "Q")["columns"]:
            s = _state["series"][c["id"]]
            seq = "，".join(f"{m[2:].replace('-', '/')}:{v:g}" for m, v in zip(s["months"][-max_months:], s["values"][-max_months:]))
            lines.append(f"- {c['name']}（{c['unit'] or '指数'}）最新 {c['latest_month']}={c['latest']:g}；序列：{seq}")
        lines.append("")
    lines.append("【当期实时预测】")
    for r in overview():
        if r.get("missing") or r["role"] == "ref":
            continue
        ai = r.get("ai")
        parts = [f"沿用上期={r['persist_pred']:g}"]
        if r.get("ar_pred") is not None:
            parts.append(f"SARIMAX{r.get('ar_order') or ''}={r['ar_pred']:.2f}")
        if ai:
            parts.append(f"AI研判={ai['value']:g}（区间 {ai.get('low')}~{ai.get('high')}，置信{ai.get('confidence')}；{ai.get('reason') or ''}）")
        lines.append(f"- {r['name']}：待发布 {r['pending_month']}；" + "；".join(parts) + f"；推荐：{r.get('recommend')}（{r.get('why')}）")
    return "\n".join(lines)


def auto_refresh_loop():
    while True:
        time.sleep(config.REFRESH_HOURS * 3600)
        try:
            load_all(force_live=True, background=False)
        except Exception:
            traceback.print_exc()
