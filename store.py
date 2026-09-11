"""SQLite 持久化：LLM 预测记录、研报缓存、任务记录。"""
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
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, source TEXT, job_id TEXT,
        indicator TEXT, target_month TEXT, mode TEXT, model TEXT, cutoff TEXT,
        value REAL, reason TEXT, thinking TEXT, answer_raw TEXT, ar_ref REAL,
        n_titles INTEGER, n_chunks INTEGER, prompt TEXT, latency REAL, tokens INTEGER, error TEXT);
    CREATE INDEX IF NOT EXISTS runs_idx ON runs(indicator, mode, target_month, source);
    """
)


def cache_get(k, max_age=None):
    with _lock:
        r = _conn.execute("SELECT v, ts FROM cache WHERE k=?", (k,)).fetchone()
    if not r:
        return None
    if max_age is not None and time.time() - r["ts"] > max_age:
        return None
    return json.loads(r["v"])


def cache_set(k, v):
    with _lock:
        _conn.execute("INSERT OR REPLACE INTO cache(k, v, ts) VALUES (?,?,?)", (k, json.dumps(v, ensure_ascii=False), time.time()))
        _conn.commit()


def add_run(rec: dict) -> int:
    cols = ["created_at", "source", "job_id", "indicator", "target_month", "mode", "model", "cutoff", "value", "reason",
            "thinking", "answer_raw", "ar_ref", "n_titles", "n_chunks", "prompt", "latency", "tokens", "error"]
    rec = {**rec, "created_at": rec.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S")}
    with _lock:
        cur = _conn.execute(f"INSERT INTO runs({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                            [rec.get(c) for c in cols])
        _conn.commit()
        return cur.lastrowid


def list_runs(indicator=None, source=None, mode=None, limit=500, full=False):
    q = "SELECT * FROM runs WHERE 1=1"
    args = []
    for col, v in (("indicator", indicator), ("source", source), ("mode", mode)):
        if v:
            q += f" AND {col}=?"
            args.append(v)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _lock:
        rows = [dict(r) for r in _conn.execute(q, args).fetchall()]
    if not full:
        for r in rows:
            r.pop("prompt", None)
    return rows


def get_run(run_id):
    with _lock:
        r = _conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(r) if r else None


def latest_preds(indicator, mode, source="backtest", model=None):
    """每个月份取最新一次成功预测。"""
    q = "SELECT target_month, value, model, id FROM runs WHERE indicator=? AND mode=? AND source=? AND value IS NOT NULL"
    args = [indicator, mode, source]
    if model:
        q += " AND model=?"
        args.append(model)
    q += " ORDER BY id"
    with _lock:
        rows = _conn.execute(q, args).fetchall()
    out = {}
    for r in rows:
        out[r["target_month"]] = r["value"]
    return out


def has_backtest_run(indicator, mode, month, model):
    with _lock:
        r = _conn.execute("SELECT 1 FROM runs WHERE indicator=? AND mode=? AND target_month=? AND model=? AND source='backtest' AND value IS NOT NULL LIMIT 1",
                          (indicator, mode, month, model)).fetchone()
    return bool(r)
