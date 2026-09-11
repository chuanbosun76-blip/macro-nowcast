"""Web 服务入口（Flask）。启动：python run.py 或 gunicorn -w 1 --threads 16 app.main:app"""
from __future__ import annotations

import csv
import hmac
import io
import threading
from functools import wraps

from flask import Flask, Response, jsonify, request, send_from_directory

import config, datasource, engine, reports, store
from indicators import BY_ID, INDICATORS, LLM_MODES

STATIC = config.ROOT
app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False

_started = threading.Event()


def boot():
    if _started.is_set():
        return
    _started.set()
    engine.load_all(force_live=False, background=True)
    threading.Thread(target=engine.auto_refresh_loop, daemon=True).start()


def need_auth(fn):
    @wraps(fn)
    def w(*a, **k):
        if config.ACCESS_PASSWORD:
            given = request.headers.get("X-Access-Password", "")
            if not hmac.compare_digest(given, config.ACCESS_PASSWORD):
                return jsonify({"error": "需要访问口令（在“方法与设置”页输入）"}), 401
        return fn(*a, **k)
    return w


def not_ready():
    if not engine._state["series"]:
        return jsonify({"error": "数据加载中，请稍候", "status": engine.status()}), 503
    return None


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/static/<path:p>")
def static_files(p):
    return send_from_directory(STATIC, p)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, **engine.status()})


@app.get("/api/status")
def api_status():
    return jsonify(engine.status())


@app.get("/api/meta")
def meta():
    return jsonify({"indicators": [{k: v for k, v in i.items()} for i in INDICATORS], "modes": LLM_MODES,
                    **engine.status()})


@app.get("/api/overview")
def api_overview():
    nr = not_ready()
    if nr:
        return nr
    return jsonify({"rows": engine.overview(), "status": engine.status()})


@app.get("/api/series/<ind_id>")
def api_series(ind_id):
    nr = not_ready()
    if nr:
        return nr
    if ind_id not in BY_ID:
        return jsonify({"error": "未知指标"}), 404
    return jsonify(engine.series_payload(ind_id, request.args.get("model") or None))


@app.get("/api/backtest")
def api_backtest():
    nr = not_ready()
    if nr:
        return nr
    return jsonify({"rows": engine.backtest_table(request.args.get("start"), request.args.get("end"),
                                                   request.args.get("model") or None), "status": engine.status()})


@app.get("/api/leak/<ind_id>")
def api_leak(ind_id):
    nr = not_ready()
    if nr:
        return nr
    return jsonify(engine.leak_check(ind_id, request.args.get("mode", "title"), request.args.get("model") or None,
                                     request.args.get("split") or None))


@app.get("/api/reports")
def api_reports():
    ind_id = request.args.get("indicator", "export_yoy")
    month = request.args.get("month")
    mode = request.args.get("mode", "title")
    if ind_id not in BY_ID or not month:
        return jsonify({"error": "参数错误"}), 400
    try:
        cutoff = min(engine.month_end(month), __import__("datetime").date.today().isoformat())
        combined, sel, info = engine.prepare_text(ind_id, month, mode, cutoff if cutoff < engine.month_end(month) else None)
    except Exception as e:  # noqa
        return jsonify({"error": f"研报抓取失败：{e}"}), 502
    return jsonify({"month": month, "indicator": ind_id, "titles": sel, "info": info, "combined": combined})


@app.post("/api/nowcast")
@need_auth
def api_nowcast():
    nr = not_ready()
    if nr:
        return nr
    j = request.get_json(force=True) or {}
    inds = j.get("indicators") or [j.get("indicator")]
    mode = j.get("mode", "title")
    if mode not in LLM_MODES or any(i not in BY_ID for i in inds):
        return jsonify({"error": "参数错误"}), 400
    items = []
    for i in inds:
        pm = engine.pending_month(i)
        month = j.get("month") or pm
        source = "live" if month >= pm else "backtest"
        items.append((i, month, mode, source))
    job = engine.start_job(items, j.get("model"), force=True, label="实时预测")
    return jsonify(job)


@app.post("/api/backtest/llm")
@need_auth
def api_backtest_llm():
    nr = not_ready()
    if nr:
        return nr
    j = request.get_json(force=True) or {}
    ind_id = j.get("indicator")
    modes = j.get("modes") or [j.get("mode", "title")]
    if ind_id not in BY_ID or any(m not in LLM_MODES for m in modes):
        return jsonify({"error": "参数错误"}), 400
    months = engine.backtest_months(ind_id, j.get("start", "2024-01"), j.get("end", "9999-12"))
    if len(months) > 240:
        return jsonify({"error": "单次最多 240 个月"}), 400
    items = [(ind_id, m, mode, "backtest") for mode in modes for m in months]
    return jsonify(engine.start_job(items, j.get("model"), force=bool(j.get("force")), label="LLM 回测"))


@app.get("/api/jobs")
def api_jobs():
    return jsonify(sorted(engine.JOBS.values(), key=lambda x: x["started"], reverse=True)[:30])


@app.get("/api/jobs/<jid>")
def api_job(jid):
    j = engine.JOBS.get(jid)
    return (jsonify(j), 200) if j else (jsonify({"error": "not found"}), 404)


@app.get("/api/runs")
def api_runs():
    return jsonify(store.list_runs(request.args.get("indicator") or None, request.args.get("source") or None,
                                   request.args.get("mode") or None, int(request.args.get("limit", 300))))


@app.get("/api/runs/<int:rid>")
def api_run(rid):
    r = store.get_run(rid)
    return (jsonify(r), 200) if r else (jsonify({"error": "not found"}), 404)


@app.get("/api/runs.csv")
def api_runs_csv():
    rows = store.list_runs(request.args.get("indicator") or None, limit=100000)
    buf = io.StringIO()
    cols = ["id", "created_at", "source", "indicator", "target_month", "mode", "model", "value", "ar_ref", "n_titles",
            "n_chunks", "reason", "error"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c) for c in cols])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=nowcast_runs.csv"})


@app.post("/api/refresh")
@need_auth
def api_refresh():
    engine.load_all(force_live=True, background=True)
    return jsonify({"ok": True})


@app.post("/api/override/<ind_id>")
@need_auth
def api_override(ind_id):
    if ind_id not in BY_ID:
        return jsonify({"error": "未知指标"}), 404
    text = request.get_data(as_text=True) or ""
    if request.args.get("clear"):
        datasource.clear_override(ind_id)
        n = 0
    else:
        try:
            n = datasource.save_override(ind_id, text)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    engine.load_all(force_live=False, background=True)
    return jsonify({"ok": True, "rows": n})


@app.post("/api/auth/check")
@need_auth
def api_auth_check():
    return jsonify({"ok": True})


boot()


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), threaded=True)
