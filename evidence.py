"""依据引擎：结论先行 + 不少于 5 条量化支撑 + 风险分布 + 市场含义。
每条支撑都必须带数字与方法出处（统计量、公式、样本），可直接用于研报写作与 AI 提示词。
引用方法论见 methodology.py（GDPNow / 纽约联储 DFM / 克利夫兰联储 / MIDAS 组合 / 信达高频 / 中金结构）。"""
from __future__ import annotations

import math

import numpy as np

import freqs
import methodology

METHOD_CN = {"persist": "沿用上期", "ar": "SARIMAX", "mf": "多因子回归", "bridge": "桥方程（月度追踪）", "ai": "AI 研判", "ref": "参考"}


def _f(v, nd=2):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:,.{nd}f}"


def _s(v, nd=2):
    return "—" if v is None or not math.isfinite(v) else f"{v:+.{nd}f}"


def _pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def _u(v, unit, signed=False):
    """带单位的数值；缺失时只返回破折号（不拼单位）。"""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return (_s(v) if signed else _f(v)) + (unit or "")


def _mo(m):
    return f"{int(m[5:7])}月" if m else "—"


# ---------------------------------------------------------------- 统计工具
def seasonal_index(months, values, kind):
    """季节性：同比/指数类用“当月值 − 前后 12 个月中心均值”的同月平均；环比/流量类用同月平均（相对全样本均值）。
    返回 {月份(1-12): (偏离, 样本数)} 与显著性（同月均值 / 全样本标准差）。"""
    ym = dict(zip(months, values))
    dev = {}
    if kind in ("mom",):
        base = float(np.mean([v for v in values[-60:] if v is not None])) if values else 0.0
        for m, v in zip(months[-60:], values[-60:]):
            if v is not None:
                dev.setdefault(int(m[5:7]), []).append(v - base)
    else:
        for i, (m, v) in enumerate(zip(months, values)):
            w = [values[j] for j in range(max(0, i - 6), min(len(values), i + 7)) if values[j] is not None]
            if v is None or len(w) < 8:
                continue
            dev.setdefault(int(m[5:7]), []).append(v - float(np.mean(w)))
    sd = float(np.std([v for v in values if v is not None])) or 1.0
    return {k: (float(np.mean(v)), len(v)) for k, v in dev.items()}, sd


def same_month_stats(ym, m, years=5):
    """近 N 年同月的历史值。"""
    vals = [(freqs.shift(m, -12 * k), ym.get(freqs.shift(m, -12 * k))) for k in range(1, years + 1)]
    vals = [(a, b) for a, b in vals if b is not None]
    if not vals:
        return None
    arr = np.array([b for _, b in vals], dtype=float)
    return {"items": vals, "mean": float(arr.mean()), "std": float(arr.std()), "min": float(arr.min()), "max": float(arr.max()), "n": len(vals)}


def carryover(mom_months, mom_values, target_month):
    """翘尾因素：同比 ≈ Π(去年 target 之后的环比) · Π(今年到 target 的环比) − 1。
    翘尾 = 去年 target 月之后各月环比的累积（对今年同比的“继承”部分）。"""
    ym = dict(zip(mom_months, mom_values))
    y, mo = int(target_month[:4]), int(target_month[5:7])
    tail = 1.0
    n = 0
    for k in range(mo + 1, 13):
        v = ym.get(f"{y - 1}-{k:02d}")
        if v is None:
            return None
        tail *= 1 + v / 100
        n += 1
    for k in range(1, mo + 1):
        v = ym.get(f"{y - 1}-{k:02d}")
        if v is None:
            return None
        tail *= 1  # 仅统计去年尾部
    return {"carry": (tail - 1) * 100, "n_months": n}


def base_effect(ym, target_month):
    """基数效应：去年同月值与去年环比动量（去年同月 − 去年上月），基数抬升会压低今年同比。"""
    a = ym.get(freqs.shift(target_month, -12))
    b = ym.get(freqs.shift(target_month, -13))
    c = ym.get(freqs.shift(target_month, -24))
    if a is None:
        return None
    return {"last_year": a, "last_year_prev": b, "two_years": c, "momentum": (a - b) if b is not None else None,
            "vs_2y": (a - c) if c is not None else None}


def analogs(months, values, window=6, k=5, min_gap=6):
    """历史相似期：对最近 window 期做标准化形状匹配，找欧氏距离最小的 k 段，统计其后 1 期的变动。"""
    v = [x for x in values if x is not None]
    if len(v) < window + 24:
        return None
    arr = np.array(values, dtype=float)
    cur = arr[-window:]
    if np.isnan(cur).any() or cur.std() < 1e-9:
        return None
    curz = (cur - cur.mean()) / cur.std()
    cands = []
    for i in range(window, len(arr) - window - 1):
        seg = arr[i - window:i]
        if np.isnan(seg).any() or seg.std() < 1e-9 or np.isnan(arr[i]):
            continue
        z = (seg - seg.mean()) / seg.std()
        d = float(np.linalg.norm(z - curz))
        cands.append((d, i, float(arr[i] - arr[i - 1])))
    cands.sort()
    picked = []
    for d, i, dlt in cands:
        if all(abs(i - j) >= min_gap for _, j, _ in picked):
            picked.append((d, i, dlt))
        if len(picked) >= k:
            break
    if len(picked) < 3:
        return None
    deltas = [x[2] for x in picked]
    return {"n": len(picked), "matches": [{"end_month": months[i - 1], "next_month": months[i], "delta": dlt, "dist": round(d, 2)} for d, i, dlt in picked],
            "mean_delta": float(np.mean(deltas)), "up_share": float(np.mean([1 if d > 0 else 0 for d in deltas])), "std_delta": float(np.std(deltas))}


def lead_scan(target_months, target_values, cands: dict, max_lead=3):
    """领先性扫描：对每个候选序列，在 0..max_lead 期领先下计算与目标的相关系数，取 |corr| 最大者。"""
    ty = dict(zip(target_months, target_values))
    out = []
    for name, d in cands.items():
        best = None
        for lead in range(0, max_lead + 1):
            xs, ys = [], []
            for m in target_months[-96:]:
                x = d.get(freqs.shift(m, -lead))
                y = ty.get(m)
                if x is not None and y is not None:
                    xs.append(x)
                    ys.append(y)
            if len(xs) < 24 or np.std(xs) < 1e-9 or np.std(ys) < 1e-9:
                continue
            c = float(np.corrcoef(xs, ys)[0, 1])
            if best is None or abs(c) > abs(best[1]):
                best = (lead, c, len(xs))
        if best:
            last = sorted(d)[-1]
            prev = freqs.shift(last, -1)
            out.append({"name": name, "lead": best[0], "corr": best[1], "n": best[2], "last_month": last, "last": d[last],
                        "change": (d[last] - d[prev]) if d.get(prev) is not None else None})
    out.sort(key=lambda r: -abs(r["corr"]))
    return out


# ---------------------------------------------------------------- 主构建
def build(ctx: dict) -> dict:
    """ctx 需含：ind, months, values, basis, summary, ar, mf, bridge, cand_series(同国其他指标 {名: {月: 值}}),
    mom_series(同指标的环比序列，用于翘尾), transmission(可选), views(可选)。"""
    ind = ctx["ind"]
    months, values = ctx["months"], ctx["values"]
    b = ctx["basis"] or {}
    sm = ctx.get("summary") or {}
    unit = ind["unit"]
    ym = dict(zip(months, values))
    pm = b.get("target_month")
    con = b.get("conclusion") or {}
    pred = con.get("value")
    last_v, last_m = b.get("last_value"), b.get("last_month")
    freq = ind["freq"]
    fname = freqs.FREQ_NAME[freq]
    pts = []

    def add(tag, title, text, nums=None, method=""):
        pts.append({"no": len(pts) + 1, "tag": tag, "title": title, "text": text, "numbers": nums or [], "method": method})

    # ① 基准与惯性
    recent = [(m, ym[m]) for m in months[-4:]]
    chg = (pred - last_v) if (pred is not None and last_v is not None) else None
    ar = ctx.get("ar") or {}
    pc = (sm.get("persist") or {})
    add("基准", "上期水平与惯性基准",
        f"最近 4 期：" + "、".join(f"{freqs.period_label(m, freq)} {_f(v)}{unit}" for m, v in recent) + "。"
        f"以上期值（{_f(last_v)}{unit}）作为无新增信息的基准，{ctx.get('backtest_start', '2014-01')} 以来该基准与实际值相关系数 {_f(pc.get('corr'))}、RMSE {_f(pc.get('rmse'))}"
        + (f"（{pc.get('n')} 期）" if pc.get("n") else "") + "。"
        + (f"本次结论 {_f(pred)}{unit}，相对上期变动 {_s(chg)}{unit}。" if chg is not None else ""),
        [("上期值", _u(last_v, unit)), ("基准相关系数", _f(pc.get("corr"))), ("基准RMSE", _f(pc.get("rmse"))), ("相对上期", _u(chg, unit, True))],
        "随机游走基准（persistence benchmark）：宏观序列自相关强，任何模型必须先跑赢它才有价值。")

    # ② 时序模型与季节性
    if ar.get("preds"):
        am = sm.get("ar") or {}
        d = ar.get("d") or 0
        si, sd_all = seasonal_index(months, values, ind["kind"])
        mo = int(pm[5:7]) if pm else None
        s_here = si.get(mo)
        seas_txt = ""
        if s_here and freq == "M":
            seas_txt = (f"季节性：{_mo(pm)}的历史季节偏离为 {_s(s_here[0])}{unit}（{s_here[1]} 个样本，全样本标准差 {_f(sd_all)}，"
                        f"季节强度 {_f(abs(s_here[0]) / sd_all * 100, 0)}%）。")
        add("模型", f"SARIMAX{ar.get('final_order') or ''} 时序模型",
            f"样本 {months[0]}–{last_m} 共 {len(months)} 期；ADF 单位根检验 p={_f(ar.get('adf_p'), 3)}"
            f"（{'平稳，d=0 直接建模' if d == 0 else '非平稳，d=1 一阶差分后建模'}）；"
            + ("含 12 期季节项（P=1，s=12）；" if ind["seasonal"] and freq == "M" else ("含 4 期季节项（s=4）；" if ind["seasonal"] else ""))
            + ("含春节假期比例外生变量；" if ind["spring"] else "")
            + f"残差 Ljung–Box p={_f(ar.get('lb_resid_p'), 3)}（{'未拒绝白噪声，设定合理' if (ar.get('lb_resid_p') or 0) > 0.05 else '仍有自相关，提示存在未建模的结构'}）。"
            + f"扩展窗口回测：相关系数 {_f(am.get('corr'))}、RMSE {_f(am.get('rmse'))}、方向命中率 {_pct(am.get('hit'))}（{am.get('n')} 期）。" + seas_txt
            + (f"模型给出 {_f((b.get('ar') or {}).get('value'))}{unit}。" if (b.get("ar") or {}).get("value") is not None else ""),
            [("阶数", ar.get("final_order")), ("ADF p", _f(ar.get("adf_p"), 3)), ("回测RMSE", _f(am.get("rmse"))), ("方向命中", _pct(am.get("hit"))),
             ("季节偏离", _u(s_here[0], unit, True) if s_here else "—")],
            "SARIMAX：φ(L)Φ(Lˢ)(1−L)^d y_t = c + βx_t + θ(L)Θ(Lˢ)ε_t；AIC 网格选阶，每年重选一次，扩展窗口无未来信息。")

    # ③ 多因子贡献分解
    mf = ctx.get("mf") or {}
    if mf.get("contrib"):
        mm = sm.get("mf") or {}
        top = sorted(mf["contrib"].items(), key=lambda kv: -abs(kv[1] or 0))[:5]
        pos = [k for k, v in top if (v or 0) > 0]
        neg = [k for k, v in top if (v or 0) < 0]
        add("因子", "多因子回归的贡献分解",
            f"以同国 {len(mf.get('features') or [])} 个因子（自身滞后 + 关联指标滞后 1 期 + 领先指标当期）标准化后岭回归（λ={mf.get('lambda')}），"
            f"截距（历史均值）{_f(mf.get('alpha'))}{unit}；本期各因子贡献 β_j·z_j："
            + "，".join(f"{k} {_s(v)}" for k, v in top) + "。"
            + (f"拉动项主要来自 {'、'.join(pos)}；" if pos else "") + (f"拖累项来自 {'、'.join(neg)}。" if neg else "")
            + f"合计得到 {_f(mf.get('nowcast'))}{unit}。回测：相关系数 {_f(mm.get('corr'))}、RMSE {_f(mm.get('rmse'))}、方向命中率 {_pct(mm.get('hit'))}。",
            [(k, _s(v)) for k, v in top] + [("回测RMSE", _f(mm.get("rmse")))],
            "岭回归 β̂=(ZᵀZ+λI)⁻¹Zᵀ(y−ȳ)；贡献分解 ŷ−ȳ=Σβ_j·z_j（纽约联储 DFM“新闻分解”的可解释替代）。")

    # ④ 领先信号
    cands = ctx.get("cand_series") or {}
    if cands:
        ls = lead_scan(months, values, cands)[:4]
        if ls:
            txt = []
            for r in ls:
                txt.append(f"{r['name']}（领先 {r['lead']} 期，相关系数 {_f(r['corr'])}，{r['n']} 期样本）最新 {r['last_month']} 为 {_f(r['last'])}"
                           + (f"，较上期 {_s(r['change'])}" if r.get("change") is not None else ""))
            nch = len([r for r in ls if r.get("change") not in (None, 0)])
            agree = sum(1 for r in ls if r.get("change") not in (None, 0) and np.sign(r["change"]) * np.sign(r["corr"]) > 0)
            add("领先", "领先/同步指标的最新方向",
                "；".join(txt) + (f"。按各自与本指标的相关方向折算，{nch} 个有变动的信号中 {agree} 个指向上行、{nch - agree} 个指向下行，"
                                 + ("合力偏多。" if agree * 2 > nch else ("合力偏空。" if agree * 2 < nch else "多空相当。")) if nch else "。"),
                [(r["name"], f"{_f(r['last'])}（{_s(r['change'])}）") for r in ls],
                "交叉相关扫描：在 0–3 期领先下取 |corr| 最大的滞后阶（信达高频跟踪框架的量化版）。")

    # ⑤ 基数效应 / 翘尾
    be = base_effect(ym, pm) if pm else None
    if be:
        mom = ctx.get("mom_series")
        co = carryover(mom[0], mom[1], pm) if mom else None
        t = (f"去年同期（{freqs.period_label(freqs.shift(pm, -12), freq)}）为 {_f(be['last_year'])}{unit}"
             + (f"，去年上一期 {_f(be['last_year_prev'])}{unit}（去年同期动量 {_s(be['momentum'])}{unit}）" if be.get("momentum") is not None else "")
             + (f"，前年同期 {_f(be['two_years'])}{unit}（两年变动 {_s(be['vs_2y'])}{unit}）" if be.get("vs_2y") is not None else "") + "。")
        if ind["kind"] == "yoy" and be.get("momentum") is not None:
            t += "去年同期基数" + ("抬升，对今年同比形成压制；" if be["momentum"] > 0 else "回落，对今年同比构成支撑；")
        if co:
            t += f"翘尾因素：去年 {_mo(pm)}之后 {co['n_months']} 个月环比累积为 {_s(co['carry'])}{unit}，即在今年新涨价为零的情形下同比已“继承” {_s(co['carry'])}{unit}。"
        sms = same_month_stats(ym, pm, 5)
        if sms:
            t += f"近 5 年同期均值 {_f(sms['mean'])}{unit}（区间 {_f(sms['min'])}~{_f(sms['max'])}，标准差 {_f(sms['std'])}）。"
        add("基数", "基数效应与同期比较", t,
            [("去年同期", _u(be["last_year"], unit)), ("去年同期动量", _u(be.get("momentum"), unit, True)), ("翘尾", _u(co["carry"], unit, True) if co else "—"),
             ("近5年同期均值", _u(sms["mean"], unit) if sms else "—")],
            "同比_t ≈ (1+环比_t)(1+同比_{t−1})/(1+环比_{t−12}) − 1；翘尾 = 去年剩余月份环比的累积（中金/统计局口径）。")

    # ⑥ 历史相似期
    an = analogs(months, values)
    if an:
        add("类比", "历史相似形态的后续走势",
            f"以最近 6 期的标准化形态匹配历史，找到 {an['n']} 个最相似时点（"
            + "、".join(f"{m['end_month']}（距离 {m['dist']}，其后变动 {_s(m['delta'])}）" for m in an["matches"][:3]) + " 等）。"
            f"这些相似期之后一期的平均变动为 {_s(an['mean_delta'])}{unit}，上行概率 {_pct(an['up_share'])}，变动标准差 {_f(an['std_delta'])}{unit}。"
            f"按此类比，本期参考值为 {_f((last_v or 0) + an['mean_delta'])}{unit}。",
            [("相似样本", an["n"]), ("平均后续变动", _u(an["mean_delta"], unit, True)), ("上行概率", _pct(an["up_share"])), ("类比参考值", _u((last_v or 0) + an["mean_delta"], unit))],
            "模式匹配：d = ‖z(近6期) − z(历史6期)‖₂，取最小的 5 段（互不重叠）统计其后一期变动。")

    # ⑦ 桥方程（季度指标）
    br = b.get("bridge")
    if br:
        add("桥方程", "月度数据对当季的实时追踪", br["text"],
            [("当季追踪值", _u(br["value"], unit)), ("已公布月数", f"{br['n_current']}/3"), ("R²", _f(br.get("r2"))), ("样本外RMSE", _f(br.get("rmse")))],
            "桥方程 y_q = α + Σβ_j·z̄_j,q（亚特兰大联储 GDPNow）；本平台用“季度至今均值”逐月更新。")

    # ⑧ 组合与不确定性
    cb = b.get("combo")
    band = con.get("band")
    if cb or band:
        t = ""
        if cb:
            names = {"persist": "沿用上期", "ar": "SARIMAX", "mf": "多因子", "bridge": "桥方程", "ai": "AI研判"}
            t = ("组合预测（Bates–Granger 逆均方误差加权 w_i ∝ 1/RMSE_i²）：" +
                 "，".join(f"{names.get(k, k)} 权重 {v * 100:.0f}%（RMSE {_f(cb['rmse'].get(k))}）" for k, v in sorted(cb["weights"].items(), key=lambda kv: -kv[1])) +
                 f"，组合值 {_f(cb['value'])}{unit}。")
        if band:
            t += f"80% 置信区间 {_f(band[0])}~{_f(band[1])}{unit}（±1.28σ，σ 由近 36 期回测残差估计）。"
        diff = None
        vals = [v for v in ((b.get("persist") or {}).get("value"), (b.get("ar") or {}).get("value"), (b.get("mf") or {}).get("value"),
                            (b.get("bridge") or {}).get("value"), (b.get("ai") or {}).get("value")) if v is not None]
        if len(vals) >= 2:
            diff = max(vals) - min(vals)
            t += f"各方法给出的区间为 {_f(min(vals))}~{_f(max(vals))}{unit}（极差 {_f(diff)}{unit}），" + (
                "分歧较小，结论稳健。" if (band and diff <= abs(band[1] - band[0]) * 0.75) else "分歧偏大，说明本期存在模型难以捕捉的外生因素，应提高对研报与高频信息的权重。")
        add("稳健性", "组合预测与不确定性", t,
            [("组合值", _u((cb or {}).get("value"), unit) if cb else "—"), ("80%区间", f"{_f(band[0])}~{_u(band[1], unit)}" if band else "—"), ("方法极差", _u(diff, unit) if diff else "—")],
            "Bates & Granger (1969)：组合权重与各法历史 RMSE 平方成反比；区间基于回测残差正态近似。")

    # ⑨ 跨频率含义
    vw = ctx.get("views") or {}
    for f in ("Q", "A"):
        cur = (vw.get(f) or {}).get("current")
        if cur and cur.get("value") is not None and f != freq:
            add("跨期", f"对{'当季' if f == 'Q' else '当年'}的含义",
                f"{cur['label']}：已公布 {cur['n_realized']}/{cur['n_total']} 期（已实现占比 {_pct(cur.get('share_realized'))}），"
                f"按{'期内均值' if cur['agg'] == 'mean' else ('期内合计' if cur['agg'] == 'sum' else '期末值')}口径，"
                f"已实现部分为 {_f(cur.get('realized_only'))}{unit}，纳入本期预测与剩余期外推后为 {_f(cur['value'])}{unit}。"
                + ("外推方法：" + "、".join(f"{m[5:7]}月 {meth}" for m, _, meth in (cur.get("forecast") or [])[:4]) + "。" if cur.get("forecast") else ""),
                [("口径", {"mean": "期内均值", "sum": "期内合计", "last": "期末值"}.get(cur["agg"], cur["agg"])), ("已实现", _u(cur.get("realized_only"), unit)),
                 (f"{cur['label']}合计/均值", _u(cur["value"], unit)), ("已实现占比", _pct(cur.get("share_realized")))],
                "IMF/OECD 年度预测口径：已实现期 + 剩余期外推（carry-over）；外推用季节漂移/同比比例/季节均值法。")

    # 风险分布
    sigma = (b.get("ar") or {}).get("sigma")
    risks = None
    if pred is not None and sigma:
        risks = {"base": pred, "sigma": sigma,
                 "up": pred + 1.28 * sigma, "down": pred - 1.28 * sigma,
                 "up_ext": pred + 1.96 * sigma, "down_ext": pred - 1.96 * sigma,
                 "text": (f"以稳健残差 σ={_f(sigma)}{unit}（1.4826×MAD，已弱化 2020 年异常）刻画不确定性：基准情形 {_f(pred)}{unit}；"
                          f"乐观情形（80% 上界）{_f(pred + 1.28 * sigma)}{unit}，悲观情形 {_f(pred - 1.28 * sigma)}{unit}；"
                          f"95% 区间 {_f(pred - 1.96 * sigma)}~{_f(pred + 1.96 * sigma)}{unit}。超出该区间的概率约 5%。")}

    # 市场含义
    tr = ctx.get("transmission") or {}
    market = None
    if tr.get("markets") and (tr.get("implied") or {}).get("z") is not None:
        imp = tr["implied"]
        rows = sorted([m for m in tr["markets"] if m.get("implied_move") is not None], key=lambda m: -abs(m["implied_move"]))[:6]
        market = {"z": imp["z"], "surprise": imp["surprise"], "ref_kind": imp["ref_kind"], "rows": rows,
                  "text": (f"预期差：结论 {_f(imp['pred'])}{unit} 相对{imp['ref_kind']} {_f(imp['ref'])}{unit}，预期差 {_s(imp['surprise'])}{unit}，"
                           f"折合 z={_f(imp['z'])}（历史预期差标准差 {_f(tr.get('surprise_sd'))}{unit}）。按事件回归 β_std 估算："
                           + "、".join(f"{m['name']} {_s(m['implied_move'], 2)}{m['unit']}（t={_f((m['release_month'] or {}).get('t'))}，R²={_pct((m['release_month'] or {}).get('r2'))}）" for m in rows) + "。")}

    meths = methodology.relevant(ind)
    return {"conclusion": {"value": pred, "unit": unit, "label": b.get("target_label"), "method": con.get("used"), "band": con.get("band"),
                           "direction": ("上行" if (chg or 0) > 0 else ("下行" if (chg or 0) < 0 else "持平")), "change": chg,
                           "text": (f"结论：预计 {b.get('target_label')} {ind['name']} 为 {_f(pred)}{unit}"
                                    + (f"（80% 区间 {_f(con['band'][0])}~{_f(con['band'][1])}{unit}）" if con.get("band") else "")
                                    + (f"，较上期 {_f(last_v)}{unit} {'上行' if (chg or 0) > 0 else ('下行' if (chg or 0) < 0 else '持平')} {_f(abs(chg or 0))}{unit}" if chg is not None else "")
                                    + f"；采用方法：{METHOD_CN.get(con.get('used'), con.get('used') or '')}（{con.get('why') or ''}）。")},
            "points": pts, "risks": risks, "market": market, "frequency": fname,
            "factors": methodology.factors_for(ind), "methods": [{k: m[k] for k in ("id", "org", "name", "core", "formula", "accuracy", "use", "ref")} for m in meths]}
