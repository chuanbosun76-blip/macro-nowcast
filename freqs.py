"""频率体系：月度序列 ↔ 季度/年度聚合、当期（季/年）实时追踪（已公布月份 + 模型外推月份）、GDP 桥方程月度追踪。

聚合规则（由指标 kind / agg 决定）：
  yoy / index / rate / level → 期内均值      flow → 期内求和      stock → 期末值      mom → 期内环比累计（Σ，近似复合）
当期外推（尚未公布的月份）：
  yoy/index：预测值 + 季节漂移  drift(m) = mean_k [ y(m−12k) − y(pm−12k) ]，k=1..3（“季节性均值外推法”）
  mom：近 5 年同月均值（季节均值法）        rate/level/stock：平推（随机游走）
  flow：y(m−12) × [ pred(pm) / y(pm−12) ]（同比比例法）
"""
from __future__ import annotations

import math

import numpy as np

KIND_AGG = {"yoy": "mean", "mom": "sum", "index": "mean", "rate": "mean", "level": "mean", "flow": "sum", "stock": "last"}
FREQ_NAME = {"M": "月度", "Q": "季度", "A": "年度"}


def agg_of(ind):
    return ind.get("agg") or KIND_AGG.get(ind.get("kind", "yoy"), "mean")


def shift(m, k):
    t = int(m[:4]) * 12 + int(m[5:7]) - 1 + k
    return f"{t // 12}-{t % 12 + 1:02d}"


def period_key(m, freq):
    """所属期的键：M→原月；Q→季末月；A→12 月。"""
    y, mm = int(m[:4]), int(m[5:7])
    if freq == "Q":
        return f"{y}-{((mm - 1) // 3 + 1) * 3:02d}"
    if freq == "A":
        return f"{y}-12"
    return m


def period_months(key, freq):
    y, mm = int(key[:4]), int(key[5:7])
    if freq == "Q":
        return [f"{y}-{mm - 2:02d}", f"{y}-{mm - 1:02d}", f"{y}-{mm:02d}"]
    if freq == "A":
        return [f"{y}-{i:02d}" for i in range(1, 13)]
    return [key]


def period_label(key, freq):
    if not key:
        return "—"
    if freq == "Q":
        return f"{key[:4]}年Q{(int(key[5:7]) + 2) // 3}"
    if freq == "A":
        return f"{key[:4]}年"
    return f"{key[:4]}年{int(key[5:7])}月"


def next_period(key, freq):
    return shift(key, {"M": 1, "Q": 3, "A": 12}[freq])


def _agg(vals, how):
    vals = [v for v in vals if v is not None and math.isfinite(v)]
    if not vals:
        return None
    if how == "sum":
        return float(sum(vals))
    if how == "last":
        return float(vals[-1])
    return float(sum(vals) / len(vals))


def expected_n(key, freq, ind):
    n = {"M": 1, "Q": 3, "A": 12}[freq]
    if ind.get("jan_merge") and freq in ("Q", "A") and (freq == "A" or key[5:7] == "03"):
        n -= 1  # 1–2 月合并发布：1 月缺失属正常
    return n


def aggregate(ind, months, values, freq, allow_partial=False):
    """{期键: (值, 已含月数, 应含月数)}；默认只返回完整期。"""
    if freq == "M" or ind["freq"] != "M":
        return {}
    how = agg_of(ind)
    buckets: dict[str, list] = {}
    for m, v in zip(months, values):
        if v is None:
            continue
        buckets.setdefault(period_key(m, freq), []).append((m, v))
    out = {}
    for key, items in sorted(buckets.items()):
        need = expected_n(key, freq, ind)
        items.sort()
        if len(items) >= need or allow_partial:
            out[key] = (_agg([v for _, v in items], how), len(items), need)
    return out


def extrapolate(ind, ym: dict, months_needed: list, pm: str, pred_pm):
    """为尚未公布的月份给出外推值：{月: (值, 方法说明)}。ym：历史 {月: 值}；pm：待公布月；pred_pm：pm 的预测值。"""
    kind = ind.get("kind", "yoy")
    out = {}
    for m in months_needed:
        if m == pm and pred_pm is not None:
            out[m] = (float(pred_pm), "模型预测")
            continue
        base = pred_pm if pred_pm is not None else ym.get(shift(pm, -1))
        if kind == "mom":
            same = [ym.get(shift(m, -12 * k)) for k in range(1, 6)]
            same = [v for v in same if v is not None]
            out[m] = (float(np.mean(same)), "近5年同月均值") if same else (base, "平推")
        elif kind == "flow":
            ref, ref_pm = ym.get(shift(m, -12)), ym.get(shift(pm, -12))
            if ref is not None and ref_pm and pred_pm is not None and ref_pm != 0:
                out[m] = (float(ref * pred_pm / ref_pm), "同比比例法")
            elif ref is not None:
                out[m] = (float(ref), "上年同月")
            else:
                out[m] = (base, "平推")
        elif kind in ("yoy", "index"):
            drifts = []
            for k in range(1, 4):
                a, b = ym.get(shift(m, -12 * k)), ym.get(shift(pm, -12 * k))
                if a is not None and b is not None:
                    drifts.append(a - b)
            if base is None:
                continue
            out[m] = (float(base + np.mean(drifts)), "季节漂移外推") if drifts else (float(base), "平推")
        else:
            if base is not None:
                out[m] = (float(base), "平推")
    return out


def current_period(ind, months, values, freq, pm, pred_pm, pred_method="模型"):
    """当期（含 pm 的季/年）追踪：已公布月份 + 外推月份 → 聚合值。"""
    if not pm:
        return None
    key = period_key(pm, freq)
    need = period_months(key, freq)
    ym = dict(zip(months, values))
    realized = [(m, ym[m]) for m in need if ym.get(m) is not None]
    if ind.get("jan_merge") and f"{key[:4]}-01" in need and ym.get(f"{key[:4]}-01") is None and ym.get(f"{key[:4]}-02") is not None:
        need = [m for m in need if m != f"{key[:4]}-01"]
    missing = [m for m in need if ym.get(m) is None]
    if ind.get("jan_merge") and pm.endswith("-02"):
        missing = [m for m in missing if m != f"{pm[:4]}-01"]
    ext = extrapolate(ind, ym, missing, pm, pred_pm)
    fc = [(m, ext[m][0], ext[m][1] if m != pm else pred_method) for m in missing if m in ext and ext[m][0] is not None]
    allv = [v for _, v in realized] + [v for _, v, _ in fc]
    how = agg_of(ind)
    return {"period": key, "label": period_label(key, freq), "realized": realized, "forecast": fc, "n_realized": len(realized),
            "n_total": len(realized) + len(fc), "value": _agg(allv, how), "agg": how, "realized_only": _agg([v for _, v in realized], how),
            "share_realized": (len(realized) / max(1, len(realized) + len(fc)))}


# ------------------------------------------------------------------ 季度指标的年度聚合 / 外推
def q_to_annual(ind, qmonths, qvalues, pending_q, pred_q):
    """季度序列 → 年度（均值/求和）；当年 = 已公布季度 + 待公布季度预测 + 后续季度季节漂移外推。"""
    how = agg_of(ind)
    yq = dict(zip(qmonths, qvalues))
    hist = {}
    for m, v in zip(qmonths, qvalues):
        hist.setdefault(m[:4], []).append(v)
    history = {f"{y}-12": (_agg(v, how), len(v), 4) for y, v in hist.items() if len(v) == 4}
    cur = None
    if pending_q:
        y = pending_q[:4]
        realized = [(m, yq[m]) for m in (f"{y}-03", f"{y}-06", f"{y}-09", f"{y}-12") if yq.get(m) is not None]
        fc = []
        for m in (f"{y}-03", f"{y}-06", f"{y}-09", f"{y}-12"):
            if yq.get(m) is not None:
                continue
            if m == pending_q and pred_q is not None:
                fc.append((m, float(pred_q), "模型预测"))
            else:
                base = pred_q if pred_q is not None else (yq.get(shift(pending_q, -3)))
                drifts = [yq[shift(m, -12 * k)] - yq[shift(pending_q, -12 * k)] for k in range(1, 4)
                          if yq.get(shift(m, -12 * k)) is not None and yq.get(shift(pending_q, -12 * k)) is not None]
                if base is not None:
                    fc.append((m, float(base + (np.mean(drifts) if drifts else 0)), "季节漂移外推" if drifts else "平推"))
        allv = [v for _, v in realized] + [v for _, v, _ in fc]
        cur = {"period": f"{y}-12", "label": f"{y}年", "realized": realized, "forecast": fc, "n_realized": len(realized), "n_total": len(allv),
               "value": _agg(allv, how), "agg": how, "realized_only": _agg([v for _, v in realized], how), "share_realized": len(realized) / max(1, len(allv))}
    return history, cur


# ------------------------------------------------------------------ 桥方程（季度目标 ← 月度指标）
def qtd_features(feats: dict, names: list, upto_month: str):
    """季度至今（quarter-to-date）特征均值：只用该季度内 ≤ upto_month 且已公布的月份，与 GDPNow 的“已公布月份取实际值”一致。"""
    q = period_key(upto_month, "Q")
    ms = [m for m in period_months(q, "Q") if m <= upto_month]
    row, n_ok = [], 0
    for nm in names:
        vals = [feats[nm].get(m) for m in ms]
        vals = [v for v in vals if v is not None]
        if not vals:  # 1–2 月合并等：向前借一期
            v = feats[nm].get(shift(ms[0], -1))
            vals = [v] if v is not None else []
        if vals:
            n_ok += 1
            row.append(float(np.mean(vals)))
        else:
            row.append(np.nan)
    return row, n_ok, len([m for m in ms if any(feats[nm].get(m) is not None for nm in names)])


def _ridge(X, Y, lam):
    ok = ~np.isnan(X).any(axis=1) & ~np.isnan(Y)
    Xa, Ya = X[ok], Y[ok]
    if len(Ya) < 16:
        return None
    mu, sd = Xa.mean(axis=0), Xa.std(axis=0)
    sd[sd < 1e-9] = 1.0
    Z = (Xa - mu) / sd
    ymu = float(Ya.mean())
    beta = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (Ya - ymu))
    resid = Ya - (ymu + Z @ beta)
    r2 = 1 - float((resid ** 2).sum() / max(((Ya - ymu) ** 2).sum(), 1e-12))
    return {"mu": mu, "sd": sd, "ymu": ymu, "beta": beta, "r2": r2, "rmse_in": float(np.sqrt((resid ** 2).mean())), "n": int(ok.sum())}


def bridge_build(target: dict, feats: dict, lam=1.0, start="2011-03", backtest_start="2014-03", min_cover=0.7):
    """扩展窗口桥方程：对每个季度 q，只用 q 之前的季度估计，再用 q 的季内特征均值预测（样本外）；
    同时给出逐月追踪值（每月用“季度至今均值”代入当时可得的模型）。"""
    names = [nm for nm in feats]
    qs = sorted(q for q in target if q >= start)
    if len(qs) < 24:
        return None
    Xall = np.array([[np.mean([v for v in (feats[nm].get(m) for m in period_months(q, "Q")) if v is not None]) if any(
        feats[nm].get(m) is not None for m in period_months(q, "Q")) else np.nan for nm in names] for q in qs], dtype=float)
    Yall = np.array([target[q] for q in qs], dtype=float)
    cover = (~np.isnan(Xall)).mean(axis=0)
    use = [i for i, c in enumerate(cover) if c >= min_cover]
    if not use:
        return None
    names = [names[i] for i in use]
    Xall = Xall[:, use]
    preds, model = {}, None
    for i, q in enumerate(qs):
        if q < backtest_start:
            continue
        m = _ridge(Xall[:i], Yall[:i], lam)
        if m is None:
            continue
        model = m
        z = (Xall[i] - m["mu"]) / m["sd"]
        z = np.where(np.isnan(z), 0.0, z)
        preds[q] = float(m["ymu"] + z @ m["beta"])
    final = _ridge(Xall, Yall, lam)
    if final is None:
        return None
    errs = [preds[q] - target[q] for q in preds if target.get(q) is not None]
    # 逐月追踪：每个月用“季度至今”特征 + 该季度之前估计的模型
    months = sorted({m for nm in names for m in feats[nm]})
    months = [m for m in months if m >= backtest_start]
    monthly, monthly_n = {}, {}
    for m in months:
        q = period_key(m, "Q")
        i = next((j for j, qq in enumerate(qs) if qq == q), None)
        mod = _ridge(Xall[:i], Yall[:i], lam) if i is not None else final
        mod = mod or final
        row, n_ok, n_m = qtd_features(feats, names, m)
        if n_ok < max(2, len(names) // 2):
            continue
        z = (np.array(row) - mod["mu"]) / mod["sd"]
        z = np.where(np.isnan(z), 0.0, z)
        monthly[m] = float(mod["ymu"] + z @ mod["beta"])
        monthly_n[m] = n_m
    return {"names": names, "coef": {nm: float(b) for nm, b in zip(names, final["beta"])}, "alpha": final["ymu"], "r2": final["r2"],
            "rmse_in": final["rmse_in"], "n": final["n"], "sample": f"{qs[0]}–{qs[-1]}", "preds": preds, "monthly": monthly, "monthly_n": monthly_n,
            "rmse_oos": float(np.sqrt(np.mean(np.square(errs)))) if len(errs) >= 8 else None, "n_oos": len(errs),
            "mu": final["mu"], "sd": final["sd"], "beta": final["beta"]}


