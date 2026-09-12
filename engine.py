"""流程编排：数据加载 → 增量 SARIMAX → 三法对照 → AI 结构化研判 → 自动预测 / 回测 / 问答上下文。"""
from __future__ import annotations

import calendar
import json
import math
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np

import config
import datasource
import llm
import reports
import store
from calendar_cn import spring_series
from indicators import BY_ID, GROUPS_ORDER, INDICATORS, LLM_MODES
from tsmodels import adf_test, expanding_backtest, lag1_corr, ljung_box, spec_from_label

AR_DIR = config.DATA_DIR / "ar_cache"
AR_DIR.mkdir(parents=True, exist_ok=True)
AR_VERSION = "v6"
SEED_FILE = config.ROOT / "ar_seed.json"
_seed_cache = None

_state = {"series": {}, "ar": {}, "ar_progress": {}, "ready": False, "loading": False, "error": None, "loaded_at": None,
          "last_check": None, "version": uuid.uuid4().hex[:12], "pending": {}}
_lock = threading.RLock()
JOBS: dict[str, dict] = {}
UPDATE = {"running": False, "stage": "", "started": None, "job_id": None, "error": None, "finished": None}


# ------------------------------------------------------------------ 工具
def is_modeled(ind) -> bool:
    return ind["freq"] == "M" and ind["role"] in ("nowcast", "persist")


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
            "runs": store.count_runs(), "n_indicators": {"CN": sum(1 for i in INDICATORS if i["country"] == "CN"),
                                                          "US": sum(1 for i in INDICATORS if i["country"] == "US")}}


# ------------------------------------------------------------------ 汇总
def recommend(ind, persist_corr, ar_corr, llm_m=None):
    if not is_modeled(ind):
        return "ref", "参考指标：仅展示，不做实时预测"
    if persist_corr is not None and persist_corr >= 0.8:
        return "persist", f"与上期相关性 {persist_corr:.2f} ≥ 0.8，惯性极强，沿用上期即为最优"
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
    out = {"persist": metrics(actual, pp, win), "ar": metrics(actual, arp, win) if arp else None, "llm": {}}
    for mode in LLM_MODES:
        lp = store.latest_preds(ind_id, mode, "backtest", model)
        lp = {m: v for m, v in lp.items() if start <= m <= end}
        if lp:
            lm = sorted(lp)
            out["llm"][mode] = {**metrics(actual, lp, lm), "persist_same": metrics(actual, pp, lm), "ar_same": metrics(actual, arp, lm) if arp else None}
    rec, why = recommend(ind, out["persist"]["corr"], (out["ar"] or {}).get("corr"), out["llm"].get("title"))
    out.update(recommend=rec, why=why)
    return out


def overview(country=None):
    rows = []
    for ind in INDICATORS:
        if country and ind["country"] != country:
            continue
        s = _state["series"].get(ind["id"])
        if not s or not s["months"]:
            rows.append({"id": ind["id"], "name": ind["name"], "short": ind["short"], "unit": ind["unit"], "group": ind["group"],
                         "country": ind["country"], "role": ind["role"], "freq": ind["freq"], "release": ind["release"],
                         "missing": True, "notes": (s or {}).get("notes", [])})
            continue
        ar = _state["ar"].get(ind["id"]) or {}
        pm = pending_month(ind["id"])
        sm = summary(ind["id"]) if is_modeled(ind) else None
        live = store.latest_live(ind["id"], pm)
        rows.append({
            "id": ind["id"], "name": ind["name"], "short": ind["short"], "unit": ind["unit"], "group": ind["group"], "country": ind["country"],
            "role": ind["role"], "freq": ind["freq"], "release": ind["release"], "theory": ind.get("theory"), "spring": ind["spring"],
            "last_month": s["months"][-1], "last_value": s["values"][-1], "prev_value": s["values"][-2] if len(s["values"]) > 1 else None,
            "history": list(zip(s["months"][-24:], s["values"][-24:])), "pending_month": pm, "persist_pred": s["values"][-1],
            "ar_pred": ar.get("nowcast") if ar.get("nowcast_month") == pm else None, "ar_order": ar.get("final_order"), "adf_p": ar.get("adf_p"),
            "persist_corr": (sm or {}).get("persist", {}).get("corr") if sm else None, "ar_corr": ((sm or {}).get("ar") or {}).get("corr") if sm else None,
            "llm_corr": {k: v.get("corr") for k, v in ((sm or {}).get("llm") or {}).items()} if sm else {},
            "recommend": (sm or {}).get("recommend") if sm else "ref", "why": (sm or {}).get("why") if sm else "参考指标",
            "ai": live, "notes": s.get("notes", []),
        })
    return rows


def series_payload(ind_id, model=None):
    s = _state["series"][ind_id]
    ar = _state["ar"].get(ind_id) or {}
    out = {"months": s["months"], "values": s["values"], "persist": persist_preds(ind_id) if s["months"] else {}, "ar": ar.get("preds") or {},
           "ar_orders": ar.get("orders") or {}, "llm": {}, "pending_month": pending_month(ind_id), "ar_nowcast": ar.get("nowcast"),
           "diag": {k: ar.get(k) for k in ("adf_stat", "adf_p", "lb_resid_p", "lb_raw_p", "final_order", "d")}, "notes": s.get("notes", [])}
    for mode in LLM_MODES:
        lp = store.latest_preds(ind_id, mode, "backtest", model)
        if lp:
            out["llm"][mode] = lp
    live = [r for r in store.list_runs(indicator=ind_id, source="live", limit=20, ok_only=True)]
    out["live"] = live[:5]
    return out


def backtest_table(start=None, end=None, model=None, country=None):
    rows = []
    for ind in INDICATORS:
        if not is_modeled(ind) or (country and ind["country"] != country):
            continue
        sm = summary(ind["id"], start, end, model)
        ar = _state["ar"].get(ind["id"]) or {}
        if sm is None:
            continue
        rows.append({"id": ind["id"], "name": ind["name"], "country": ind["country"], "group": ind["group"], "role": ind["role"], "spring": ind["spring"],
                     "persist": sm["persist"], "ar": sm["ar"], "llm": sm["llm"], "recommend": sm["recommend"], "why": sm["why"],
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
    ctx = {"history": hist, "persist": hist[-1][1] if hist else None, "ar": ar_val, "order": (ar.get("orders") or {}).get(month) or ar.get("final_order"),
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
