"""SARIMAX（带外生变量的季节性 ARIMA）与平稳性/自相关检验。

实现说明：采用“回归 + SARIMA 误差”形式（与 statsmodels SARIMAX 默认设定一致）
    y_t = c + β'x_t + u_t,   φ(L)Φ(L^s) Δ^d u_t = θ(L)Θ(L^s) ε_t
参数用条件平方和（CSS）极大似然估计（scipy least_squares），AR/MA 系数经偏自相关变换
强制平稳、可逆。只依赖 numpy/scipy，便于在任意云主机部署。
"""
from __future__ import annotations

import itertools
import math
import warnings

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import lfilter
from scipy.stats import chi2, norm

warnings.filterwarnings("ignore", category=RuntimeWarning)


# ----------------------------------------------------------------- 检验
def _mackinnon_p(stat: float) -> float:
    """ADF（含常数项、N=1）MacKinnon(1994) 近似 p 值。"""
    if stat > 2.74:
        return 1.0
    if stat < -18.83:
        return 0.0
    if stat <= -1.61:
        coef = [2.1659, 1.4412, 0.038269]
    else:
        coef = [1.7339, 0.93202, -0.12745, -0.010368]
    z = sum(c * stat ** i for i, c in enumerate(coef))
    return float(norm.cdf(z))


def adf_test(y, maxlag: int | None = None):
    """Augmented Dickey-Fuller（含常数），滞后阶数按 AIC 选择。返回 (统计量, p值, 滞后阶)。"""
    y = np.asarray(y, dtype=float)
    y = y[~np.isnan(y)]
    n = len(y)
    if n < 20:
        return float("nan"), float("nan"), 0
    if maxlag is None:
        maxlag = int(math.ceil(12 * (n / 100.0) ** 0.25))
    maxlag = min(maxlag, n // 3)
    dy = np.diff(y)
    best = None
    for k in range(0, maxlag + 1):
        # 统一样本：从 maxlag 开始
        start = maxlag
        Y = dy[start:]
        cols = [np.ones_like(Y), y[start:-1]]
        for i in range(1, k + 1):
            cols.append(dy[start - i:-i])
        X = np.column_stack(cols)
        beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
        resid = Y - X @ beta
        nobs = len(Y)
        sse = float(resid @ resid)
        aic = nobs * math.log(sse / nobs) + 2 * X.shape[1]
        if best is None or aic < best[0]:
            best = (aic, k)
    k = best[1]
    Y = dy[k:]
    cols = [np.ones_like(Y), y[k:-1]]
    for i in range(1, k + 1):
        cols.append(dy[k - i:-i])
    X = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    s2 = float(resid @ resid) / (len(Y) - X.shape[1])
    cov = s2 * np.linalg.inv(X.T @ X)
    stat = float(beta[1] / math.sqrt(cov[1, 1]))
    return stat, _mackinnon_p(stat), k


def ljung_box(x, lags: int = 12):
    """Ljung-Box Q 检验，返回 (Q, p值)。p<0.05 说明存在显著自相关。"""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n <= lags + 2:
        return float("nan"), float("nan")
    x = x - x.mean()
    denom = float(x @ x)
    q = 0.0
    for k in range(1, lags + 1):
        r = float(x[k:] @ x[:-k]) / denom
        q += r * r / (n - k)
    q *= n * (n + 2)
    return q, float(chi2.sf(q, lags))


def lag1_corr(y) -> float:
    y = np.asarray(y, dtype=float)
    a, b = y[1:], y[:-1]
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 3:
        return float("nan")
    return float(np.corrcoef(a[m], b[m])[0, 1])


# ----------------------------------------------------------------- 模型
def _pacf_to_coef(x):
    """无约束参数 → 偏自相关(-1,1) → 平稳 AR 系数（Durbin-Levinson）。"""
    r = np.tanh(np.asarray(x, dtype=float)) * 0.995
    p = len(r)
    if p == 0:
        return np.zeros(0)
    phi = np.zeros((p, p))
    for k in range(p):
        phi[k, k] = r[k]
        for j in range(k):
            phi[k, j] = phi[k - 1, j] - r[k] * phi[k - 1, k - 1 - j]
    return phi[p - 1].copy()


class SarimaxSpec:
    def __init__(self, p=1, d=0, q=0, P=0, Q=0, s=12, trend=True):
        self.p, self.d, self.q, self.P, self.Q, self.s = p, d, q, P, Q, s
        self.trend = trend and d == 0

    def label(self):
        base = f"({self.p},{self.d},{self.q})"
        if self.P or self.Q:
            base += f"({self.P},0,{self.Q},{self.s})"
        return base

    def max_lag(self):
        return self.p + self.P * self.s


class SarimaxFit:
    def __init__(self, spec: SarimaxSpec, params, y, X, resid, sse, nobs, level_last=None):
        self.spec, self.params, self.y, self.X = spec, params, y, X
        self.resid, self.sse, self.nobs = resid, sse, nobs
        self.level_last = level_last
        k = len(params)
        self.sigma2 = sse / max(nobs, 1)
        self.aic = nobs * math.log(max(self.sigma2, 1e-12)) + 2 * (k + 1)


def _unpack(spec: SarimaxSpec, params, kx):
    i = 0
    c = 0.0
    if spec.trend:
        c = params[0]
        i = 1
    beta = params[i:i + kx]; i += kx
    phi = _pacf_to_coef(params[i:i + spec.p]); i += spec.p
    theta = -_pacf_to_coef(params[i:i + spec.q]); i += spec.q
    Phi = _pacf_to_coef(params[i:i + spec.P]); i += spec.P
    Theta = -_pacf_to_coef(params[i:i + spec.Q]); i += spec.Q
    return c, beta, phi, theta, Phi, Theta


def _polys(spec, phi, theta, Phi, Theta):
    ar = np.r_[1.0, -phi]
    ma = np.r_[1.0, theta]
    if spec.P:
        sar = np.zeros(spec.P * spec.s + 1); sar[0] = 1.0
        for j, v in enumerate(Phi):
            sar[(j + 1) * spec.s] = -v
        ar = np.convolve(ar, sar)
    if spec.Q:
        sma = np.zeros(spec.Q * spec.s + 1); sma[0] = 1.0
        for j, v in enumerate(Theta):
            sma[(j + 1) * spec.s] = v
        ma = np.convolve(ma, sma)
    return ar, ma


def _residuals(params, spec, y, X):
    kx = 0 if X is None else X.shape[1]
    c, beta, phi, theta, Phi, Theta = _unpack(spec, params, kx)
    u = y - c
    if kx:
        u = u - X @ beta
    ar, ma = _polys(spec, phi, theta, Phi, Theta)
    m = len(ar) - 1
    w = lfilter(ar, [1.0], u)[m:]
    e = lfilter([1.0], ma, w)
    return e, u, ar, ma


def fit_sarimax(y, spec: SarimaxSpec, exog=None, start_params=None):
    """y: 原始水平序列；exog: (n, k) 外生变量。d=1 时对 y 与 exog 同时差分。"""
    y = np.asarray(y, dtype=float)
    X = None if exog is None else np.asarray(exog, dtype=float).reshape(len(y), -1)
    level_last = None
    x_level_last = None if X is None else X[-1].copy()
    if spec.d == 1:
        level_last = y[-1]
        y = np.diff(y)
        if X is not None:
            X = np.diff(X, axis=0)
    kx = 0 if X is None else X.shape[1]
    # 初值：OLS
    cols = []
    if spec.trend:
        cols.append(np.ones_like(y))
    if kx:
        cols.extend(list(X.T))
    x0 = []
    if cols:
        A = np.column_stack(cols)
        b, *_ = np.linalg.lstsq(A, y, rcond=None)
        x0.extend(b.tolist())
    x0.extend([0.1] * spec.p + [0.0] * spec.q + [0.1] * spec.P + [0.0] * spec.Q)
    x0 = np.asarray(x0, dtype=float)
    if start_params is not None and len(start_params) == len(x0):
        x0 = np.asarray(start_params, dtype=float)
    nparam = len(x0)
    if nparam == 0:
        e = y - 0.0
        f = SarimaxFit(spec, x0, y, X, e, float(e @ e), len(e), level_last)
        f.X_level_last = x_level_last
        return f

    def fun(p):
        e = _residuals(p, spec, y, X)[0]
        return e

    n_res = len(fun(x0))
    method = "lm" if n_res > nparam else "trf"
    try:
        res = least_squares(fun, x0, method=method, max_nfev=200 * (nparam + 1))
        params = res.x
    except Exception:
        params = x0
    e = fun(params)
    f = SarimaxFit(spec, params, y, X, e, float(e @ e), len(e), level_last)
    f.X_level_last = x_level_last
    return f


def forecast_one(fit: SarimaxFit, exog_next=None) -> float:
    spec = fit.spec
    y, X = fit.y, fit.X
    kx = 0 if X is None else X.shape[1]
    c, beta, phi, theta, Phi, Theta = _unpack(spec, fit.params, kx)
    e, u, ar, ma = _residuals(fit.params, spec, y, X)
    # u_{T+1} = Σ_{k≥1} ma_k ε_{T+1-k} − Σ_{j≥1} ar_j u_{T+1-j}
    uhat = 0.0
    for j in range(1, len(ar)):
        if len(u) - j >= 0:
            uhat -= ar[j] * u[len(u) - j]
    for k in range(1, len(ma)):
        if len(e) - k >= 0:
            uhat += ma[k] * e[len(e) - k]
    xn = 0.0
    if kx:
        xe = np.asarray(exog_next, dtype=float).reshape(-1)
        if spec.d == 1:
            xe = xe - np.asarray(fit.X_level_last, dtype=float).reshape(-1)
        xn = float(xe @ beta)
    yhat = c + xn + uhat
    if spec.d == 1:
        yhat += fit.level_last
    return float(yhat)


def select_order(y, exog=None, d=0, seasonal=False, p_max=3, q_max=2):
    """按 AIC 在 (p,q) 网格上选阶；季节性指标固定 P=1。统一有效样本以保证 AIC 可比。"""
    best = None
    P = 1 if seasonal else 0
    for p, q in itertools.product(range(p_max + 1), range(q_max + 1)):
        spec = SarimaxSpec(p, d, q, P, 0)
        f = _fit_with_level(y, spec, exog)
        # 可比 AIC：统一丢弃最大滞后长度的样本
        burn = (p_max + P * 12) - spec.max_lag()
        e = f.resid[burn:] if burn > 0 else f.resid
        n = len(e)
        if n < 10:
            continue
        aic = n * math.log(max(float(e @ e) / n, 1e-12)) + 2 * (len(f.params) + 1)
        if best is None or aic < best[0]:
            best = (aic, spec, f)
    return best[1], best[2]


def _fit_with_level(y, spec, exog, start_params=None):
    return fit_sarimax(y, spec, exog, start_params)


def choose_d(y) -> tuple[int, float]:
    """原序列 ADF p<0.05 视为不作差分即平稳（d=0），否则 d=1。"""
    _, p, _ = adf_test(y)
    if not np.isfinite(p):
        return 0, p
    return (0 if p < 0.05 else 1), p


def expanding_backtest(y, months, start_idx, exog=None, seasonal=False, reselect_month="01", min_obs=36,
                       progress=None, force_d=None):
    """扩展窗口：对每个 t≥start_idx，仅用 y[:t] 估计并预测 y[t]；t=len(y) 为实时预测（下一期）。
    exog 需比 y 多 1 行（下一期外生变量已知：春节日期）。每年 1 月重选阶数，其余月份沿用阶数、重估参数。
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    E = None if exog is None else np.asarray(exog, dtype=float).reshape(n + 1, -1)
    preds, orders = {}, {}
    spec, fit, d = None, None, 0
    start_idx = max(start_idx, min_obs)
    for t in range(start_idx, n + 1):
        yt = y[:t]
        et = None if E is None else E[:t]
        mon = months[t] if t < n else "__next__"
        if spec is None or (t < n and months[t][5:7] == reselect_month):
            d = force_d if force_d is not None else choose_d(yt)[0]
            spec, fit = select_order(yt, et, d=d, seasonal=seasonal)
        else:
            fit = _fit_with_level(yt, spec, et, start_params=fit.params)
        xn = None if E is None else E[t]
        try:
            preds[mon] = forecast_one(fit, xn)
        except Exception:
            preds[mon] = float("nan")
        orders[mon] = spec.label()
        if progress:
            progress(t - start_idx + 1, n + 1 - start_idx)
    return preds, orders, spec, fit
