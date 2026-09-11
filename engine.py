"""实时预测流程编排：沿用上期 / SARIMAX（含春节外生变量）/ DeepSeek 读研报，扩展窗口回测与决策。"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np

import config, datasource, llm, reports, store
from calendar_cn import spring_series
from indicators import BY_ID, INDICATORS, LLM_MODES
from tsmodels import adf_test, expanding_backtest, lag1_corr, ljung_box

AR_DIR = config.DATA_DIR / "ar_cache"
AR_DIR.mkdir(parents=True, exist_ok=True)
AR_VERSION = "v4"

_state = {"series": {}, "ar": {}, "ar_progress": {}, "ready": False, "loading": False, "error": None,
          "loaded_at": None, "version": None, "last_check": None}
_lock = threading.RLock()
JOBS: dict[str, dict] = {}


# ------------------------------------------------------------------ 工具
def next_month(ind, m: str) -> str:
    y, mm = int(m[:4]), int(m[5:7])
    y2, m2 = (y + 1, 1) if mm == 12 else (y, mm + 1)
    if ind["jan_merge"] and m2 == 1:
        m2 = 2
    return f"{y2}-{m2:02d}"


def month_end(m: str) -> str:
    import calendar
    y, mm = int(m[:4]), int(m[5:7])
    return f"{m}-{calendar.monthrange(y, mm)[1]:02d}"


def _clean(x):
    if x is None:
        return None
    if isinstance(x, (float, np.floating)) and not math.isfinite(float(x)):
        return None
    return float(x) if isinstance(x, (np.floating, np.integer)) else x


def metrics(actual: dict, pred: dict, months=None):
    ms = [m for m in (months or pred.keys()) if m in actual and m in pred and pred[m] is not None
          and actual[m] is not None and math.isfinite(pred[m])]
    if len(ms) < 3:
        return {"n": len(ms), "corr": None, "rmse": None, "mae": None}
    a = np.array([actual[m] for m in ms])
    p = np.array([pred[m] for m in ms])
    corr = float(np.corrcoef(a, p)[0, 1]) if a.std() > 1e-9 and p.std() > 1e-9 else None
    err = p - a
    return {"n": len(ms), "corr": _clean(corr), "rmse": float(np.sqrt((err ** 2).mean())), "mae": float(np.abs(err).mean()),
            "start": ms[0], "end": ms[-1]}


# ------------------------------------------------------------------ 加载与自回归
def load_all(force_live=False, background=True):
    def job():
        try:
            with _lock:
                _state["loading"] = True
            raw = datasource.load(force_live=force_live)
            series = {i["id"]: datasource.build_series(i["id"], raw) for i in INDICATORS}
            version = hashlib.md5(json.dumps(series, sort_keys=True).encode()).hexdigest()[:12]
            with _lock:
                changed = version != _state["version"]
                _state["series"] = series
                _state["last_check"] = time.strftime("%Y-%m-%d %H:%M")
                if changed:
                    _state["version"] = version
                    _state["loaded_at"] = _state["last_check"]
            for ind in INDICATORS:
                compute_ar(ind["id"])
            with _lock:
                _state["ready"] = True
                _state["error"] = None
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


def compute_ar(ind_id: str):
    ind = BY_ID[ind_id]
    s = _state["series"][ind_id]
    months, values = s["months"], s["values"]
    if len(values) < 40:
        _state["ar"][ind_id] = {"error": "样本不足"}
        return
    nxt = next_month(ind, months[-1])
    exog = None
    if ind["spring"]:
        exog = np.array(spring_series(months + [nxt]))[:, None]
    key = hashlib.md5(json.dumps([AR_VERSION, months, values, ind["spring"], ind["seasonal"], ind.get("force_d"), config.BACKTEST_START]).encode()).hexdigest()
    cache_file = AR_DIR / f"{ind_id}.json"
    if cache_file.exists():
        try:
            c = json.loads(cache_file.read_text())
            if c.get("key") == key:
                _state["ar"][ind_id] = c
                _state["ar_progress"][ind_id] = 1.0
                return
        except Exception:
            pass
    start_idx = next((i for i, m in enumerate(months) if m >= config.BACKTEST_START), len(months))

    def prog(done, total):
        _state["ar_progress"][ind_id] = done / total

    preds, orders, spec, fit = expanding_backtest(values, months, start_idx, exog=exog, seasonal=ind["seasonal"],
                                                  progress=prog, force_d=ind.get("force_d"))
    adf_stat, adf_p, _ = adf_test(values)
    lb_q, lb_p = ljung_box(fit.resid, 12)
    lb_raw_q, lb_raw_p = ljung_box(values, 12)
    nowcast = preds.pop("__next__", None)
    orders.pop("__next__", None)
    res = {
        "key": key, "preds": {m: _clean(v) for m, v in preds.items()}, "orders": orders, "nowcast": _clean(nowcast),
        "nowcast_month": nxt, "final_order": spec.label(), "d": spec.d,
        "adf_stat": _clean(adf_stat), "adf_p": _clean(adf_p), "lb_resid_p": _clean(lb_p), "lb_raw_p": _clean(lb_raw_p),
        "spring": ind["spring"], "seasonal": ind["seasonal"], "computed_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    cache_file.write_text(json.dumps(res))
    _state["ar"][ind_id] = res
    _state["ar_progress"][ind_id] = 1.0


def status():
    return {"ready": _state["ready"], "loading": _state["loading"], "error": _state["error"],
            "ar_progress": _state["ar_progress"], "data": datasource.status(), "loaded_at": _state["loaded_at"],
            "version": _state["version"], "last_check": _state["last_check"], "refresh_hours": config.REFRESH_HOURS,
            "model": config.DEEPSEEK_MODEL, "models": config.DEEPSEEK_MODELS, "has_key": bool(config.DEEPSEEK_API_KEY),
            "auth_required": bool(config.ACCESS_PASSWORD), "backtest_start": config.BACKTEST_START,
            "llm_earliest": config.LLM_EARLIEST, "leak_split": config.LEAK_SPLIT, "offline": config.OFFLINE}


# ------------------------------------------------------------------ 汇总
def _actual(ind_id):
    s = _state["series"].get(ind_id) or {"months": [], "values": []}
    return dict(zip(s["months"], s["values"]))


def persist_preds(ind_id):
    s = _state["series"][ind_id]
    return {s["months"][i]: s["values"][i - 1] for i in range(1, len(s["months"]))}


def recommend(ind, persist_corr, ar_corr, adf_p, llm=None):
    """原文落地顺序：①与上期相关≥0.8 → 沿用上期；②自回归显著优于沿用 → SARIMAX（春节外生）；
    ③中相关（0.7–0.8）且自回归无优势 → 沿用上期；④其余 → LLM 读当月研报标题。
    若已有 ≥12 个月的 LLM 标题回测，则在“同一窗口”上比较三者相关性择优。"""
    if persist_corr is not None and persist_corr >= 0.8:
        return "persist", "与上期相关性 ≥0.8，直接沿用上期"
    if llm and llm.get("n", 0) >= 12 and llm.get("corr") is not None:
        cand = [("persist", (llm.get("persist_same") or {}).get("corr")), ("ar", (llm.get("ar_same") or {}).get("corr")),
                ("llm", llm["corr"])]
        cand = [(k, v) for k, v in cand if v is not None]
        best = max(cand, key=lambda x: x[1])
        names = {"persist": "沿用上期", "ar": "SARIMAX", "llm": "LLM 研报标题"}
        detail = "，".join(f"{names[k]} {v:.2f}" for k, v in cand)
        return best[0], f"同窗口（{llm['n']} 个月）相关性：{detail}"
    pc = persist_corr if persist_corr is not None else -1
    if ar_corr is not None and ar_corr >= 0.5 and ar_corr - pc >= 0.05:
        st = f"原序列 ADF p={adf_p:.2f}" if adf_p is not None else ""
        return "ar", f"自回归相关性 {ar_corr:.2f} 优于沿用上期 {pc:.2f}；{st}" + ("；含春节外生变量" if ind["spring"] else "")
    if pc >= 0.7:
        return "persist", f"与上期中高相关（{pc:.2f}），自回归无显著提升，沿用上期"
    return "llm", "历史弱相关、外生冲击多：按原文用 LLM 读当月研报标题"


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
            out["llm"][mode] = {**metrics(actual, lp, lm), "persist_same": metrics(actual, pp, lm),
                                "ar_same": metrics(actual, arp, lm) if arp else None}
    rec, why = recommend(ind, out["persist"]["corr"], (out["ar"] or {}).get("corr"), ar.get("adf_p"),
                         out["llm"].get("title"))
    out.update({"recommend": rec, "why": why})
    return out


def pending_month(ind_id):
    s = _state["series"][ind_id]
    return next_month(BY_ID[ind_id], s["months"][-1])


def overview():
    rows = []
    for ind in INDICATORS:
        s = _state["series"].get(ind["id"])
        if not s or not s["months"]:
            continue
        ar = _state["ar"].get(ind["id"]) or {}
        pm = pending_month(ind["id"])
        sm = summary(ind["id"]) or {}
        live = [r for r in store.list_runs(indicator=ind["id"], limit=50) if r["target_month"] == pm and r["value"] is not None]
        rows.append({
            "id": ind["id"], "name": ind["name"], "short": ind["short"], "unit": ind["unit"], "group": ind["group"],
            "role": ind["role"], "release": ind["release"], "spring": ind["spring"], "seasonal": ind["seasonal"],
            "last_month": s["months"][-1], "last_value": s["values"][-1],
            "prev_value": s["values"][-2] if len(s["values"]) > 1 else None,
            "pending_month": pm, "persist_pred": s["values"][-1], "ar_pred": ar.get("nowcast") if ar.get("nowcast_month") == pm else None,
            "ar_order": ar.get("final_order"), "adf_p": ar.get("adf_p"), "lag1_corr_full": _clean(lag1_corr(s["values"])),
            "persist_corr": (sm.get("persist") or {}).get("corr"), "ar_corr": (sm.get("ar") or {}).get("corr"),
            "llm_corr": {k: v.get("corr") for k, v in (sm.get("llm") or {}).items()},
            "recommend": sm.get("recommend"), "why": sm.get("why"), "paper": ind.get("paper"),
            "llm_latest": live[:4], "notes": s.get("notes", []),
        })
    return rows


def series_payload(ind_id, model=None):
    s = _state["series"][ind_id]
    ar = _state["ar"].get(ind_id) or {}
    out = {"months": s["months"], "values": s["values"], "persist": persist_preds(ind_id), "ar": ar.get("preds") or {},
           "ar_orders": ar.get("orders") or {}, "llm": {}, "pending_month": pending_month(ind_id),
           "ar_nowcast": ar.get("nowcast"), "diag": {k: ar.get(k) for k in ("adf_stat", "adf_p", "lb_resid_p", "lb_raw_p", "final_order", "d")}}
    for mode in LLM_MODES:
        lp = store.latest_preds(ind_id, mode, "backtest", model)
        if lp:
            out["llm"][mode] = lp
    return out


def backtest_table(start=None, end=None, model=None):
    rows = []
    for ind in INDICATORS:
        sm = summary(ind["id"], start, end, model)
        ar = _state["ar"].get(ind["id"]) or {}
        if sm is None:
            continue
        rows.append({"id": ind["id"], "name": ind["name"], "role": ind["role"], "spring": ind["spring"],
                     "persist": sm["persist"], "ar": sm["ar"], "llm": sm["llm"], "recommend": sm["recommend"], "why": sm["why"],
                     "order": ar.get("final_order"), "adf_p": ar.get("adf_p"), "lb_raw_p": ar.get("lb_raw_p"),
                     "lb_resid_p": ar.get("lb_resid_p"), "paper": ind.get("paper")})
    return rows


def leak_check(ind_id, mode="title", model=None, split=None):
    split = split or config.LEAK_SPLIT
    actual = _actual(ind_id)
    lp = store.latest_preds(ind_id, mode, "backtest", model)
    before = sorted(m for m in lp if m < split)
    after = sorted(m for m in lp if m >= split)
    pp = persist_preds(ind_id)
    return {"split": split, "before": metrics(actual, lp, before), "after": metrics(actual, lp, after),
            "persist_before": metrics(actual, pp, before), "persist_after": metrics(actual, pp, after)}


# ------------------------------------------------------------------ LLM
def prepare_text(ind_id, month, mode, cutoff=None):
    items = reports.fetch_month(month, cutoff)
    sel, supplemented = reports.select_titles(items, ind_id)
    info = {"n_all": len(items), "n_titles": len(sel), "supplemented": supplemented, "chunks": [], "dropped": 0}
    if mode.startswith("chunk"):
        chunks, dropped = reports.select_chunks(sel, ind_id)
        info.update(chunks=chunks, dropped=dropped)
        combined = "\n".join(chunks)
    else:
        combined = reports.format_titles(sel)
    return combined, sel, info


def run_llm(ind_id, month, mode="title", model=None, source="backtest", job_id=None):
    ind = BY_ID[ind_id]
    model = model or config.DEEPSEEK_MODEL
    today = date.today().isoformat()
    cutoff = min(month_end(month), today)
    ar = _state["ar"].get(ind_id) or {}
    ar_ref = None
    if mode.endswith("_ar"):
        ar_ref = (ar.get("preds") or {}).get(month)
        if ar_ref is None and ar.get("nowcast_month") == month:
            ar_ref = ar.get("nowcast")
    rec = {"source": source, "job_id": job_id, "indicator": ind_id, "target_month": month, "mode": mode, "model": model,
           "cutoff": cutoff, "ar_ref": ar_ref}
    try:
        if cutoff < f"{month}-01":
            raise RuntimeError(f"{month} 尚未开始，暂无当月研报")
        combined, sel, info = prepare_text(ind_id, month, mode, cutoff if cutoff < month_end(month) else None)
        rec.update(n_titles=info["n_titles"], n_chunks=len(info["chunks"]))
        if not combined.strip():
            raise RuntimeError("当月未召回到研报文本（数据源不可达或当月无相关研报）")
        prompt = llm.build_prompt(ind, month, mode, combined, ar_ref)
        rec["prompt"] = prompt
        res = llm.call_deepseek(prompt, model)
        value, ans, reason, thinking = llm.parse_answer(res["content"], ind["unit"])
        rec.update(value=value, answer_raw=ans or res["content"][-500:], reason=reason,
                   thinking=thinking or (res["reasoning"] or "")[:4000], latency=res["latency"], tokens=res["tokens"],
                   model=res["model"])
        if value is None:
            rec["error"] = "未能从 <回答> 中解析出数值"
    except Exception as e:  # noqa
        rec["error"] = str(e)
    rec["id"] = store.add_run(rec)
    return rec


def start_job(items, model=None, force=False, label=""):
    """items: [(indicator, month, mode, source)]"""
    model = model or config.DEEPSEEK_MODEL
    jid = uuid.uuid4().hex[:10]
    todo = []
    skipped = 0
    for ind_id, month, mode, source in items:
        if source == "backtest" and not force and store.has_backtest_run(ind_id, mode, month, model):
            skipped += 1
            continue
        todo.append((ind_id, month, mode, source))
    job = {"id": jid, "label": label, "model": model, "total": len(todo), "done": 0, "ok": 0, "failed": 0,
           "skipped": skipped, "status": "running" if todo else "done", "started": time.strftime("%Y-%m-%d %H:%M:%S"),
           "finished": None, "errors": [], "results": []}
    JOBS[jid] = job

    def one(it):
        r = run_llm(it[0], it[1], it[2], model, it[3], jid)
        with _lock:
            job["done"] += 1
            if r.get("value") is not None:
                job["ok"] += 1
            else:
                job["failed"] += 1
                job["errors"].append(f"{it[0]} {it[1]} {it[2]}：{r.get('error')}")
            job["results"].append({k: r.get(k) for k in ("id", "indicator", "target_month", "mode", "value", "reason", "error", "n_titles")})

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
    ind = BY_ID[ind_id]
    s = _state["series"][ind_id]
    start = max(start, config.LLM_EARLIEST)
    return [m for m in s["months"] if start <= m <= end]


def auto_refresh_loop():
    while True:
        time.sleep(config.REFRESH_HOURS * 3600)
        try:
            load_all(force_live=True, background=False)
        except Exception:
            traceback.print_exc()
