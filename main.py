"""Web 服务入口（Flask）。本地：python main.py；生产：gunicorn -w 1 --threads 16 main:app"""
from __future__ import annotations

import csv
import hmac
import io
import threading
from datetime import date
from functools import wraps

from flask import Flask, Response, jsonify, request, send_from_directory

import config
import datasource
import engine
import live
import llm
import markets
import reports
import store
import theory
from indicators import BY_ID, GROUPS_ORDER, INDICATORS, LLM_MODES

STATIC = config.ROOT
app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False
_started = threading.Event()


def boot():
    if _started.is_set():
        return
    _started.set()
    engine.boot()
    threading.Thread(target=engine.auto_refresh_loop, daemon=True).start()


def need_auth(fn):
    @wraps(fn)
    def w(*a, **k):
        if config.ACCESS_PASSWORD and not hmac.compare_digest(request.headers.get("X-Access-Password", ""), config.ACCESS_PASSWORD):
            return jsonify({"error": "需要访问口令"}), 401
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
    return jsonify({"indicators": engine.active_indicators(), "modes": LLM_MODES, "groups": GROUPS_ORDER, **engine.status()})


@app.get("/api/overview")
def api_overview():
    nr = not_ready()
    if nr:
        return nr
    return jsonify({"rows": engine.overview(request.args.get("country") or None), "status": engine.status()})


@app.get("/api/series/<ind_id>")
def api_series(ind_id):
    nr = not_ready()
    if nr:
        return nr
    if ind_id not in BY_ID:
        return jsonify({"error": "未知指标"}), 404
    return jsonify(engine.series_payload(ind_id, request.args.get("model") or None))


@app.get("/api/table")
def api_table():
    nr = not_ready()
    if nr:
        return nr
    return jsonify(engine.data_table(request.args.get("country") or None, int(request.args.get("months", 24)), request.args.get("freq", "M")))


@app.get("/api/data.csv")
def api_data_csv():
    nr = not_ready()
    if nr:
        return nr
    return Response(datasource.export_csv(engine._state["series"], request.args.get("country") or None), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=macro_data.csv"})


@app.get("/api/backtest")
def api_backtest():
    nr = not_ready()
    if nr:
        return nr
    return jsonify({"rows": engine.backtest_table(request.args.get("start"), request.args.get("end"), request.args.get("model") or None,
                                                   request.args.get("country") or None), "status": engine.status()})


@app.get("/api/leak/<ind_id>")
def api_leak(ind_id):
    nr = not_ready()
    if nr:
        return nr
    return jsonify(engine.leak_check(ind_id, request.args.get("mode", "title"), request.args.get("model") or None, request.args.get("split") or None))


@app.get("/api/reports")
def api_reports():
    ind_id = request.args.get("indicator", "export_yoy")
    month = request.args.get("month")
    mode = request.args.get("mode", "title")
    if ind_id not in BY_ID or not month:
        return jsonify({"error": "参数错误"}), 400
    try:
        cutoff = min(engine.month_end(month), date.today().isoformat())
        items = reports.fetch_month(month, cutoff if cutoff < engine.month_end(month) else None)
        sel, supplemented = reports.select_titles(items, ind_id)
        info = {"n_all": len(items), "n_titles": len(sel), "supplemented": supplemented, "chunks": [], "dropped": 0}
        if mode == "chunk":
            chunks, dropped = reports.select_chunks(sel, ind_id)
            info.update(chunks=chunks, dropped=dropped)
    except Exception as e:  # noqa
        return jsonify({"error": f"研报抓取失败：{e}"}), 502
    return jsonify({"month": month, "indicator": ind_id, "titles": sel, "info": info, "rules": reports.rules()})



@app.get("/api/months/<ind_id>")
def api_months(ind_id):
    if ind_id not in BY_ID:
        return jsonify({"error": "未知指标"}), 404
    return jsonify(engine.predictable_months(ind_id))


@app.get("/api/calendar")
def api_calendar():
    nr = not_ready()
    if nr:
        return nr
    return jsonify({"items": engine.calendar_upcoming(int(request.args.get("days", 45))), "today": date.today().isoformat()})


@app.get("/api/live/quotes")
def api_live_quotes():
    return jsonify(live.quotes())


@app.get("/api/live/trend")
def api_live_trend():
    sid = request.args.get("secid", "")
    if not sid or sid not in {s[0] for s in live.secids()}:
        return jsonify({"error": "未知行情代码"}), 400
    return jsonify(live.trend(sid))


@app.get("/api/live/reports")
def api_live_reports():
    """最新研报流：当月宏观+策略研报，按日期倒序。"""
    month = date.today().strftime("%Y-%m")
    try:
        items = reports.fetch_month(month, None)
        prev = reports.fetch_month(_prev_month(month), None) if len(items) < 30 else []
    except Exception as e:  # noqa
        return jsonify({"items": [], "error": str(e)})
    allitems = sorted(items + prev, key=lambda x: (x.get("date") or "", x.get("title") or ""), reverse=True)
    return jsonify({"items": allitems[:int(request.args.get("limit", 40))], "n_month": len(items)})


def _prev_month(m):
    y, mm = int(m[:4]), int(m[5:7])
    return f"{y - (mm == 1)}-{12 if mm == 1 else mm - 1:02d}"


@app.get("/api/transmission/<ind_id>")
def api_transmission(ind_id):
    nr = not_ready()
    if nr:
        return nr
    if ind_id not in BY_ID:
        return jsonify({"error": "未知指标"}), 404
    return jsonify(engine.transmission(ind_id, request.args.get("start", "2010-01")))


@app.get("/api/markets/status")
def api_markets_status():
    return jsonify(markets.status())


@app.get("/api/markets/series/<key>")
def api_markets_series(key):
    if key not in markets.BY_KEY:
        return jsonify({"error": "未知市场"}), 404
    ser = markets.series(key)
    return jsonify({"key": key, "name": markets.BY_KEY[key][1], "type": markets.BY_KEY[key][3], "months": list(ser), "values": list(ser.values()), "responses": markets.responses(key)})


@app.get("/api/board")
def api_board():
    """实时看板：按国家 / 分组整理的宏观数据总表（最新值、变动、待发布、预测）。"""
    nr = not_ready()
    if nr:
        return nr
    out = {}
    for c in ("CN", "US"):
        rows = engine.overview(c)
        groups = {}
        for r in rows:
            if r.get("missing"):
                continue
            b = r.get("basis") or {}
            con = b.get("conclusion") or {}
            hist = r.get("history") or []
            groups.setdefault(r["group"], []).append({
                "id": r["id"], "name": r["name"], "short": r["short"], "unit": r["unit"], "freq": r["freq"], "role": r["role"],
                "last_month": r["last_month"], "last_value": r["last_value"], "prev_value": r.get("prev_value"),
                "spark": [h[1] for h in hist[-12:]], "pending_month": r.get("pending_month"), "release_est": r.get("release_est"),
                "pred": con.get("value"), "method": con.get("used"), "band": con.get("band"), "ai": bool(r.get("ai")),
                "persist_corr": r.get("persist_corr"), "ar_corr": r.get("ar_corr"), "mf_corr": r.get("mf_corr"),
                "sign": theory.for_indicator(BY_ID[r["id"]])["sign"],
            })
        out[c] = [{"group": g, "items": groups[g]} for g in GROUPS_ORDER if g in groups]
    return jsonify({"board": out, "status": engine.status(), "markets": markets.status()})

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
        if not pm:
            continue
        month = j.get("month") or pm
        items.append((i, month, mode, "live" if month >= pm else "backtest"))
    return jsonify(engine.start_job(items, j.get("model"), force=True, label="实时预测"))


@app.post("/api/backtest/llm")
@need_auth
def api_backtest_llm():
    nr = not_ready()
    if nr:
        return nr
    j = request.get_json(force=True) or {}
    ids = j.get("indicators") or [j.get("indicator")]
    modes = j.get("modes") or [j.get("mode", "title")]
    if any(i not in BY_ID for i in ids) or any(m not in LLM_MODES for m in modes):
        return jsonify({"error": "参数错误"}), 400
    items = []
    for i in ids:
        for mode in modes:
            for m in engine.backtest_months(i, j.get("start", "2024-01"), j.get("end", "9999-12")):
                items.append((i, m, mode, "backtest"))
    if len(items) > 600:
        return jsonify({"error": f"单次最多 600 次调用（当前 {len(items)}），请缩小区间或指标数"}), 400
    return jsonify(engine.start_job(items, j.get("model"), force=bool(j.get("force")), label="AI 回测"))


@app.post("/api/update_and_predict")
@need_auth
def api_update_and_predict():
    j = request.get_json(force=True) or {}
    return jsonify(engine.update_and_predict(j.get("mode", "title"), j.get("model"), j.get("country"), j.get("indicators")))


@app.get("/api/update_status")
def api_update_status():
    return jsonify({**engine.UPDATE, "status": engine.status()})


@app.get("/api/jobs")
def api_jobs():
    return jsonify(sorted(engine.JOBS.values(), key=lambda x: x["started"], reverse=True)[:30])


@app.get("/api/jobs/<jid>")
def api_job(jid):
    j = engine.JOBS.get(jid)
    return (jsonify(j), 200) if j else (jsonify({"error": "not found"}), 404)


@app.get("/api/runs")
def api_runs():
    a = request.args
    return jsonify(store.list_runs(a.get("indicator") or None, a.get("source") or None, a.get("mode") or None, a.get("country") or None,
                                   int(a.get("limit", 300)), ok_only=a.get("ok") == "1"))


@app.get("/api/runs/<int:rid>")
def api_run(rid):
    r = store.get_run(rid)
    return (jsonify(r), 200) if r else (jsonify({"error": "not found"}), 404)


@app.get("/api/runs.csv")
def api_runs_csv():
    rows = store.list_runs(request.args.get("indicator") or None, limit=100000)
    buf = io.StringIO()
    cols = ["id", "created_at", "source", "indicator", "target_month", "mode", "model", "value", "low", "high", "confidence", "ar_ref", "n_titles", "reason", "error"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c) for c in cols])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=predictions.csv"})


@app.get("/api/settings")
def api_settings_get():
    s = store.all_settings()
    return jsonify({"predict_requirements": s.get("predict_requirements", ""), "recall_rules": reports.rules(),
                    "auto_predict": bool(s.get("auto_predict", config.AUTO_PREDICT)), "default_model": s.get("default_model") or llm.default_model()})


@app.post("/api/settings")
@need_auth
def api_settings_set():
    j = request.get_json(force=True) or {}
    for k in ("predict_requirements", "recall_rules", "auto_predict", "default_model"):
        if k in j:
            store.set_setting(k, j[k])
    return api_settings_get()


@app.post("/api/ask")
@need_auth
def api_ask():
    nr = not_ready()
    if nr:
        return nr
    j = request.get_json(force=True) or {}
    msgs = j.get("messages") or []
    if not msgs:
        return jsonify({"error": "缺少 messages"}), 400
    msgs = [{"role": m.get("role", "user"), "content": str(m.get("content", ""))[:8000]} for m in msgs[-12:]]
    custom = store.get_setting("predict_requirements", "") or ""
    system = ("你是“观数”宏观研究助手，服务于投资经理。基于下方最新宏观数据（中国、美国）与模型预测作答：引用具体数值与月份；"
              "对未来判断给出方向、幅度、依据与风险；区分事实与观点；数据未覆盖的内容明确说明。中文、结论先行、简洁。\n"
              + (f"用户附加要求：{custom}\n" if custom else "") + "\n" + engine.ask_context())
    try:
        res = llm.chat(msgs, j.get("model"), max_tokens=4000, system=system)
    except Exception as e:  # noqa
        return jsonify({"error": str(e)}), 502
    return jsonify(res)


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
    if request.args.get("clear"):
        datasource.clear_override(ind_id)
        n = 0
    else:
        try:
            n = datasource.save_override(ind_id, request.get_data(as_text=True) or "")
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
