"""SQLite：预测记录（含结构化研判）、缓存、设置。"""
import json
import sqlite3
import threading
import time

import config

_DB = config.DATA_DIR / "nowcast.db"
_lock = threading.Lock()
_conn = sqlite3.connect(str(_DB), check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript(
    """
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, ts REAL);
    CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT, ts REAL);
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, source TEXT, job_id TEXT,
        indicator TEXT, target_month TEXT, mode TEXT, model TEXT, cutoff TEXT,
        value REAL, reason TEXT, thinking TEXT, answer_raw TEXT, ar_ref REAL,
        n_titles INTEGER, n_chunks INTEGER, prompt TEXT, latency REAL, tokens INTEGER, error TEXT,
        low REAL, high REAL, confidence TEXT, analysis TEXT);
    CREATE INDEX IF NOT EXISTS runs_idx ON runs(indicator, mode, target_month, source);
    """
)
for col, typ in (("low", "REAL"), ("high", "REAL"), ("confidence", "TEXT"), ("analysis", "TEXT")):
    try:
        _conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {typ}")
    except sqlite3.OperationalError:
        pass
_conn.commit()

COLS = ["created_at", "source", "job_id", "indicator", "target_month", "mode", "model", "cutoff", "value", "reason",
        "thinking", "answer_raw", "ar_ref", "n_titles", "n_chunks", "prompt", "latency", "tokens", "error",
        "low", "high", "confidence", "analysis"]


def cache_get(k, max_age=None):
    with _lock:
        r = _conn.execute("SELECT v, ts FROM cache WHERE k=?", (k,)).fetchone()
    if not r or (max_age is not None and time.time() - r["ts"] > max_age):
        return None
    return json.loads(r["v"])


def cache_set(k, v):
    with _lock:
        _conn.execute("INSERT OR REPLACE INTO cache(k, v, ts) VALUES (?,?,?)", (k, json.dumps(v, ensure_ascii=False), time.time()))
        _conn.commit()


def get_setting(k, default=None):
    with _lock:
        r = _conn.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default


def set_setting(k, v):
    with _lock:
        _conn.execute("INSERT OR REPLACE INTO settings(k, v, ts) VALUES (?,?,?)", (k, json.dumps(v, ensure_ascii=False), time.time()))
        _conn.commit()


def all_settings():
    with _lock:
        rows = _conn.execute("SELECT k, v FROM settings").fetchall()
    return {r["k"]: json.loads(r["v"]) for r in rows}


def add_run(rec: dict) -> int:
    rec = {**rec, "created_at": rec.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S")}
    if isinstance(rec.get("analysis"), (dict, list)):
        rec["analysis"] = json.dumps(rec["analysis"], ensure_ascii=False)
    with _lock:
        cur = _conn.execute(f"INSERT INTO runs({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})", [rec.get(c) for c in COLS])
        _conn.commit()
        return cur.lastrowid


def _row(r, full=False):
    d = dict(r)
    if not full:
        d.pop("prompt", None)
        d.pop("thinking", None)
    if d.get("analysis"):
        try:
            d["analysis"] = json.loads(d["analysis"])
        except Exception:
            pass
    return d


def list_runs(indicator=None, source=None, mode=None, country=None, limit=500, full=False, ok_only=False):
    q = "SELECT * FROM runs WHERE 1=1"
    args = []
    for col, v in (("indicator", indicator), ("source", source), ("mode", mode)):
        if v:
            q += f" AND {col}=?"
            args.append(v)
    if country == "US":
        q += " AND indicator LIKE 'us_%'"
    elif country == "CN":
        q += " AND indicator NOT LIKE 'us_%'"
    if ok_only:
        q += " AND value IS NOT NULL"
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _lock:
        rows = _conn.execute(q, args).fetchall()
    return [_row(r, full) for r in rows]


def get_run(run_id):
    with _lock:
        r = _conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return _row(r, True) if r else None


def latest_preds(indicator, mode, source="backtest", model=None):
    q = "SELECT target_month, value FROM runs WHERE indicator=? AND mode=? AND source=? AND value IS NOT NULL"
    args = [indicator, mode, source]
    if model:
        q += " AND model=?"
        args.append(model)
    q += " ORDER BY id"
    with _lock:
        rows = _conn.execute(q, args).fetchall()
    return {r["target_month"]: r["value"] for r in rows}


def latest_live(indicator, month):
    with _lock:
        r = _conn.execute("SELECT * FROM runs WHERE indicator=? AND target_month=? AND value IS NOT NULL ORDER BY id DESC LIMIT 1",
                          (indicator, month)).fetchone()
    return _row(r) if r else None


def has_backtest_run(indicator, mode, month, model):
    with _lock:
        r = _conn.execute("SELECT 1 FROM runs WHERE indicator=? AND mode=? AND target_month=? AND model=? AND source='backtest' AND value IS NOT NULL LIMIT 1",
                          (indicator, mode, month, model)).fetchone()
    return bool(r)


def count_runs():
    with _lock:
        r = _conn.execute("SELECT COUNT(*) n, SUM(value IS NOT NULL) ok FROM runs").fetchone()
    return {"n": r["n"], "ok": r["ok"] or 0}
