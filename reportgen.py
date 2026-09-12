"""报告装配：把「依据引擎 + 数据库 + 传导分析」组装成结构化内容，再导出为 Word / Excel / PPT / Markdown，
或作为 AI 写作的上下文（用户可用自己的 prompt 指定风格与重点）。"""
from __future__ import annotations

import math
import time

import engine
import freqs
import markets
import methodology
import office
import theory
from indicators import BY_ID, INDICATORS, hierarchy

METHOD_CN = {"persist": "沿用上期", "ar": "SARIMAX", "mf": "多因子回归", "bridge": "桥方程", "ai": "AI 研判", "ref": "参考"}


def _f(v, nd=2):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:,.{nd}f}"


def _num(v):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), 4)


# ------------------------------------------------------------------ 单指标报告
def indicator_report(ind_id, with_market=True):
    ind = BY_ID[ind_id]
    e = engine.evidence_for(ind_id, with_market=with_market)
    if not e:
        return None
    b = e["basis"]
    vw = engine.views(ind_id, (b.get("conclusion") or {}).get("value"))
    s = engine._state["series"][ind_id]
    unit = ind["unit"]
    blocks = [{"h1": f"{ind['name']} · {b.get('target_label')} 预测报告"},
              {"small": f"观数 · 宏观预测平台　|　{ind['country'] == 'CN' and '中国' or '美国'} / {ind['l1']} / {ind['l2']}　|　"
                        f"{freqs.FREQ_NAME[ind['freq']]}　|　生成时间 {time.strftime('%Y-%m-%d %H:%M')}"},
              {"h2": "一、结论"},
              {"p": e["conclusion"]["text"]},
              {"p": (b.get("conclusion") or {}).get("text") or ""},
              {"h2": "二、支撑依据"}]
    for p in e["points"]:
        blocks.append({"h3": f"{p['no']}. 【{p['tag']}】{p['title']}"})
        blocks.append({"p": p["text"]})
        if p.get("numbers"):
            blocks.append({"small": "关键数字：" + "；".join(f"{k} {v}" for k, v in p["numbers"] if v not in (None, "—"))})
        if p.get("method"):
            blocks.append({"small": "方法：" + p["method"]})
    if e.get("risks"):
        blocks += [{"h2": "三、风险与情景"}, {"p": e["risks"]["text"]},
                   {"table": {"head": ["情景", "取值", "说明"],
                              "rows": [["乐观（80% 上界）", _f(e["risks"]["up"]) + unit, "上行风险兑现"],
                                       ["基准", _f(e["risks"]["base"]) + unit, "本平台结论"],
                                       ["悲观（80% 下界）", _f(e["risks"]["down"]) + unit, "下行风险兑现"],
                                       ["95% 区间", f"{_f(e['risks']['down_ext'])} ~ {_f(e['risks']['up_ext'])}{unit}", "±1.96σ"]]}}]
    if e.get("market"):
        rows = [[m["name"], f"{m['implied_move']:+.2f}{m['unit']}", _f((m["release_month"] or {}).get("beta_std")),
                 _f((m["release_month"] or {}).get("t")), f"{((m['release_month'] or {}).get('r2') or 0) * 100:.0f}%",
                 {1: "利多", -1: "利空", 0: "不确定"}.get(m.get("sign_theory"), "—")] for m in e["market"]["rows"]]
        blocks += [{"h2": "四、对股市 / 债市的含义"}, {"p": e["market"]["text"]},
                   {"table": {"head": ["资产", "隐含变动", "β_std", "t 值", "R²", "理论方向"], "rows": rows}},
                   {"p": (b.get("theory") or "") + " " + (theory.for_indicator(ind).get("note") or "")}]
    # 多频率数据
    blocks.append({"h2": "五、多频率历史数据"})
    for f in ("M", "Q", "A"):
        v = vw.get(f)
        if not v:
            continue
        hist = v.get("history") or []
        rows = [[h[0] if f == "M" else freqs.period_label(h[0], f), _f(h[1]) + unit] + ([f"{h[2]} 期" ] if len(h) > 2 else []) for h in hist[-12:]]
        blocks.append({"h3": f"{freqs.FREQ_NAME[f]}口径（近 {len(rows)} 期）"})
        blocks.append({"table": {"head": ["期间", "数值"] + (["含期数"] if rows and len(rows[0]) > 2 else []), "rows": rows}})
        cur = v.get("current")
        if cur and cur.get("value") is not None:
            blocks.append({"small": f"当期 {cur['label']}：{_f(cur['value'])}{unit}（已实现 {cur.get('n_realized')}/{cur.get('n_total')} 期）"})
    # 方法论
    blocks.append({"h2": "六、方法论与预测因子"})
    blocks.append({"p": "常用预测因子：" + "；".join(e.get("factors") or []) + "。"})
    for m in e.get("methods") or []:
        blocks.append({"h3": f"{m['org']}｜{m['name']}"})
        blocks.append({"p": m["core"]})
        blocks.append({"small": "公式：" + m["formula"]})
        blocks.append({"small": "精度：" + (m.get("accuracy") or "—") + "　来源：" + m.get("ref", "")})
        blocks.append({"small": "本平台应用：" + m.get("use", "")})
    blocks.append({"small": "免责声明：本报告由模型与公开数据自动生成，仅供研究参考，不构成投资建议。"})
    return {"blocks": blocks, "evidence": e, "views": vw, "indicator": ind, "series": s}


# ------------------------------------------------------------------ 全库报告 / 表格
def overview_report(country=None):
    rows = engine.overview(country)
    blocks = [{"h1": "观数 · 宏观预测总览"},
              {"small": f"生成时间 {time.strftime('%Y-%m-%d %H:%M')}　|　指标 {len(rows)} 项"}]
    for blk in hierarchy(country):
        blocks.append({"h2": blk["l1"]})
        for g in blk["groups"]:
            items = [r for r in rows if r["id"] in g["ids"] and not r.get("missing")]
            if not items:
                continue
            blocks.append({"h3": g["l2"]})
            trows = []
            for r in items:
                con = (r.get("basis") or {}).get("conclusion") or {}
                trows.append([r["name"], r["unit"], r["last_month"], _f(r["last_value"]),
                              engine.month_label(r.get("pending_month"), r["freq"]), _f(con.get("value")),
                              METHOD_CN.get(con.get("used"), "—"), r.get("release_est") or r["release"]])
            blocks.append({"table": {"head": ["指标", "单位", "最新期", "最新值", "预测对象", "预测值", "方法", "预计公布"],
                                     "rows": trows, "widths": [2400, 700, 900, 900, 1100, 900, 900, 1560]}})
    return {"blocks": blocks, "rows": rows}


def data_workbook(country=None, months=60):
    """Excel 工作簿：总览 + 月/季/年三张数据表 + 回测 + 预测档案。"""
    sheets = {}
    ov = engine.overview(country)
    sheets["预测总览"] = {"head": ["国家", "一级分类", "二级分类", "指标", "单位", "频率", "最新期", "最新值", "预测对象", "预测值", "推荐方法", "理由", "预计公布"],
                      "rows": [[r["country"], BY_ID[r["id"]]["l1"], BY_ID[r["id"]]["l2"], r["name"], r["unit"], r["freq"], r.get("last_month"),
                                _num(r.get("last_value")), engine.month_label(r.get("pending_month"), r["freq"]),
                                _num(((r.get("basis") or {}).get("conclusion") or {}).get("value")),
                                METHOD_CN.get(((r.get("basis") or {}).get("conclusion") or {}).get("used"), ""), r.get("why"), r.get("release_est") or r.get("release")]
                               for r in ov if not r.get("missing")],
                      "widths": [7, 10, 10, 26, 8, 6, 10, 12, 12, 12, 12, 40, 22]}
    for f, nm, n in (("M", "月度数据", months), ("Q", "季度数据", 40), ("A", "年度数据", 20)):
        t = engine.data_table(country, n, f)
        head = ["期间"] + [f"{c['name']}（{c['unit'] or '指数'}）" + ("*" if c["derived"] else "") for c in t["columns"]]
        rows = []
        for i, m in enumerate(t["months"]):
            rows.append([freqs.period_label(m, f)] + [_num(c["values"][i]) for c in t["columns"]])
        sheets[nm] = {"head": head, "rows": rows[::-1], "widths": [12] + [14] * len(t["columns"])}
    bt = engine.backtest_table(country=country)
    sheets["回测评分"] = {"head": ["指标", "国家", "分类", "沿用上期corr", "沿用上期RMSE", "SARIMAX corr", "SARIMAX RMSE", "多因子corr", "多因子RMSE",
                              "桥方程corr", "桥方程RMSE", "AI corr", "推荐方法", "理由", "阶数"],
                      "rows": [[r["name"], r["country"], r["group"], _num((r["persist"] or {}).get("corr")), _num((r["persist"] or {}).get("rmse")),
                                _num((r["ar"] or {}).get("corr")), _num((r["ar"] or {}).get("rmse")), _num((r.get("mf") or {}).get("corr")),
                                _num((r.get("mf") or {}).get("rmse")), _num((r.get("bridge") or {}).get("corr")), _num((r.get("bridge") or {}).get("rmse")),
                                _num(((r["llm"] or {}).get("title") or {}).get("corr")), METHOD_CN.get(r["recommend"], r["recommend"]), r["why"], r.get("order")]
                               for r in bt], "widths": [24, 6, 10] + [13] * 9 + [12, 40, 12]}
    ms = markets.status()
    sheets["市场月度库"] = {"head": ["期间"] + [m[1] for m in markets.META],
                       "rows": _market_rows(), "widths": [12] + [13] * len(markets.META)}
    return sheets


def _market_rows(n=120):
    series = {m[0]: markets.series(m[0]) for m in markets.META}
    allm = sorted({x for s in series.values() for x in s})[-n:]
    return [[m] + [_num(series[k[0]].get(m)) for k in markets.META] for m in allm[::-1]]


def board_deck(country="CN", top=12):
    """PPT：封面 + 结论页 + 分类页 + 传导页。"""
    rows = [r for r in engine.overview(country) if not r.get("missing") and r["role"] != "ref"]
    cname = "中国" if country == "CN" else "美国"
    slides = [{"cover": True, "title": f"{cname}宏观数据预测简报",
               "bullets": ["观数 · 宏观预测平台", time.strftime("%Y 年 %m 月 %d 日"),
                           f"覆盖指标 {len(rows)} 项　方法：沿用上期 / SARIMAX / 多因子回归 / 桥方程 / AI 研判"]}]
    key = sorted(rows, key=lambda r: -abs(((r.get("basis") or {}).get("conclusion") or {}).get("value") or 0) if False else 0)[:top]
    bl = []
    for r in key:
        con = (r.get("basis") or {}).get("conclusion") or {}
        if con.get("value") is None:
            continue
        d = ""
        if r.get("last_value") is not None:
            diff = con["value"] - r["last_value"]
            d = f"（较上期 {diff:+.2f}）"
        bl.append(f"{r['name']}：{engine.month_label(r.get('pending_month'), r['freq'])} 预计 {_f(con['value'])}{r['unit']}{d}，方法 {METHOD_CN.get(con.get('used'), '')}")
    slides.append({"title": "核心结论", "subtitle": "本期待发布指标的预测值", "bullets": bl[:10]})
    for blk in hierarchy(country):
        items = [r for r in rows if BY_ID[r["id"]]["l1"] == blk["l1"]]
        if not items:
            continue
        bul = []
        for g in blk["groups"]:
            gi = [r for r in items if r["id"] in g["ids"]]
            if not gi:
                continue
            bul.append(g["l2"])
            for r in gi[:6]:
                con = (r.get("basis") or {}).get("conclusion") or {}
                bul.append([f"{r['name']}　最新 {_f(r['last_value'])}{r['unit']}（{r['last_month']}）"
                            + (f"　预测 {_f(con.get('value'))}{r['unit']}" if con.get("value") is not None else ""), 1])
        slides.append({"title": blk["l1"], "subtitle": f"{cname} · 共 {len(items)} 项指标", "bullets": bul[:14]})
    return slides


# ------------------------------------------------------------------ AI 上下文
def ai_context(ind_id=None, country=None, max_chars=14000):
    """给 AI 的“我的数据库”上下文：结论 + 依据 + 关键数据表。"""
    parts = []
    if ind_id:
        r = indicator_report(ind_id, with_market=True)
        if r:
            e = r["evidence"]
            parts.append(f"【预测对象】{r['indicator']['name']}（{e['conclusion']['label']}，单位 {r['indicator']['unit']}）")
            parts.append("【平台结论】" + e["conclusion"]["text"])
            parts.append("【量化支撑】")
            for p in e["points"]:
                parts.append(f"{p['no']}. [{p['tag']}] {p['title']}：{p['text']}")
            if e.get("risks"):
                parts.append("【风险分布】" + e["risks"]["text"])
            if e.get("market"):
                parts.append("【市场含义】" + e["market"]["text"])
            parts.append("【常用预测因子】" + "；".join(e.get("factors") or []))
            parts.append("【可引用的机构方法论】" + "；".join(f"{m['org']}·{m['name']}：{m['core'][:120]}" for m in (e.get("methods") or [])))
    else:
        parts.append(engine.ask_context())
    txt = "\n".join(parts)
    return txt[:max_chars]


def ai_report(ind_id=None, country=None, prompt="", model=None, kind="研报点评"):
    """让 AI 基于内嵌数据库写作，用户 prompt 决定风格与重点。"""
    import llm
    import store
    ctx = ai_context(ind_id, country)
    custom = store.get_setting("predict_requirements", "") or ""
    system = ("你是卖方宏观首席分析师，服务于投资经理。严格基于下方“平台数据库”的数值写作：每个判断都要有数字支撑，"
              "结构为：一、结论（含预测值与方向）；二、不少于 5 条量化依据（每条带数字与出处）；三、风险情景；四、对 A 股 / 港股 / 美股 / 中债 / 美债的含义与操作含义；五、跟踪清单。"
              "禁止编造数据库中没有的数字；不确定处注明“需进一步验证”。中文，结论先行，条理清晰。\n"
              + (f"【用户长期要求】{custom}\n" if custom else "")
              + (f"【本次写作要求】{prompt}\n" if prompt else "")
              + f"\n【平台数据库】\n{ctx}")
    res = llm.chat([{"role": "user", "content": f"请写一篇{kind}。"}], model, max_tokens=6000, system=system)
    return {"text": res.get("content") or "", "model": res.get("model"), "tokens": res.get("tokens"), "context_chars": len(ctx)}


# ------------------------------------------------------------------ 导出
def export(kind, scope, ind_id=None, country=None, text=None, title=None):
    """kind: docx|xlsx|pptx|md；scope: indicator|overview|data|deck|ai"""
    ts = time.strftime("%Y%m%d")
    if scope == "ai" and text:
        blocks = [{"h1": title or "宏观研究报告"}, {"small": f"观数 · 宏观预测平台　生成时间 {time.strftime('%Y-%m-%d %H:%M')}"}]
        for line in text.split("\n"):
            t = line.strip()
            if not t:
                continue
            if t.startswith("###"):
                blocks.append({"h3": t.lstrip("# ").strip()})
            elif t.startswith("##"):
                blocks.append({"h2": t.lstrip("# ").strip()})
            elif t.startswith("#"):
                blocks.append({"h2": t.lstrip("# ").strip()})
            elif t[:2] in ("- ", "* ") or t[:1] in ("•",):
                blocks.append({"bullets": [t[1:].strip()]})
            elif t[:2] in ("一、", "二、", "三、", "四、", "五、", "六、", "七、"):
                blocks.append({"h2": t})
            else:
                blocks.append({"p": t})
        if kind == "md":
            return text.encode("utf-8"), f"ai_report_{ts}.md", "text/markdown; charset=utf-8"
        if kind == "pptx":
            paras, slides, cur = [], [{"cover": True, "title": title or "宏观研究报告", "bullets": ["观数 · 宏观预测平台", time.strftime("%Y-%m-%d")]}], None
            for bkt in blocks:
                if "h2" in bkt:
                    cur = {"title": bkt["h2"], "bullets": []}
                    slides.append(cur)
                elif cur is not None:
                    v = bkt.get("p") or bkt.get("h3") or (bkt.get("bullets") or [""])[0] or bkt.get("small")
                    if v:
                        cur["bullets"].append(v[:220])
            return office.pptx(slides), f"ai_report_{ts}.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return office.docx(blocks, title=title or "宏观研究报告"), f"ai_report_{ts}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    if scope == "indicator":
        r = indicator_report(ind_id)
        if not r:
            raise ValueError("指标无数据")
        nm = BY_ID[ind_id]["short"]
        if kind == "md":
            return blocks_to_md(r["blocks"]).encode("utf-8"), f"{ind_id}_{ts}.md", "text/markdown; charset=utf-8"
        if kind == "xlsx":
            return office.xlsx(indicator_sheets(ind_id, r)), f"{ind_id}_{ts}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if kind == "pptx":
            return office.pptx(indicator_slides(r)), f"{ind_id}_{ts}.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return office.docx(r["blocks"], title=f"{nm}预测报告"), f"{ind_id}_{ts}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    if scope in ("overview", "deck"):
        if kind == "pptx" or scope == "deck":
            return office.pptx(board_deck(country or "CN")), f"board_{country or 'CN'}_{ts}.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        r = overview_report(country)
        if kind == "md":
            return blocks_to_md(r["blocks"]).encode("utf-8"), f"overview_{ts}.md", "text/markdown; charset=utf-8"
        if kind == "xlsx":
            return office.xlsx(data_workbook(country)), f"database_{ts}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return office.docx(r["blocks"], title="宏观预测总览"), f"overview_{ts}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # data
    return office.xlsx(data_workbook(country)), f"database_{ts}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def indicator_sheets(ind_id, r=None):
    r = r or indicator_report(ind_id)
    ind = BY_ID[ind_id]
    e, vw = r["evidence"], r["views"]
    sheets = {"结论与依据": {"head": ["项目", "内容"], "rows": [["结论", e["conclusion"]["text"]]] +
                                                     [[f"依据{p['no']}·{p['tag']}·{p['title']}", p["text"]] for p in e["points"]] +
                                                     ([["风险情景", e["risks"]["text"]]] if e.get("risks") else []) +
                                                     ([["市场含义", e["market"]["text"]]] if e.get("market") else []),
                         "widths": [28, 120]}}
    for f in ("M", "Q", "A"):
        v = vw.get(f)
        if not v or not v.get("history"):
            continue
        sheets[f"{freqs.FREQ_NAME[f]}序列"] = {"head": ["期间", f"{ind['name']}（{ind['unit'] or '指数'}）"],
                                            "rows": [[freqs.period_label(h[0], f), _num(h[1])] for h in v["history"]][::-1], "widths": [14, 20]}
    ser = engine.series_payload(ind_id)
    months = ser["months"][-120:]
    sheets["回测明细"] = {"head": ["期间", "实际值", "沿用上期", "SARIMAX", "多因子", "桥方程"],
                      "rows": [[m, _num(dict(zip(ser["months"], ser["values"])).get(m)), _num(ser["persist"].get(m)), _num(ser["ar"].get(m)),
                                _num(ser["mf"].get(m)), _num(engine.bridge_preds(ind_id).get(m))] for m in months][::-1],
                      "widths": [12, 14, 14, 14, 14, 14]}
    tr = e.get("market")
    if tr:
        sheets["传导分析"] = {"head": ["资产", "隐含变动", "β_std", "t 值", "R²", "样本数"],
                          "rows": [[m["name"], _num(m["implied_move"]), _num((m["release_month"] or {}).get("beta_std")),
                                    _num((m["release_month"] or {}).get("t")), _num((m["release_month"] or {}).get("r2")),
                                    (m["release_month"] or {}).get("n")] for m in tr["rows"]], "widths": [18, 14, 12, 10, 10, 10]}
    return sheets


def indicator_slides(r):
    e = r["evidence"]
    ind = r["indicator"]
    slides = [{"cover": True, "title": f"{ind['name']} · {e['conclusion']['label']}",
               "bullets": ["观数 · 宏观预测平台", time.strftime("%Y-%m-%d"), e["conclusion"]["text"][:120]]},
              {"title": "结论", "subtitle": e["conclusion"]["label"], "bullets": [e["conclusion"]["text"]]}]
    for i in range(0, len(e["points"]), 3):
        grp = e["points"][i:i + 3]
        bul = []
        for p in grp:
            bul.append(f"{p['no']}. 【{p['tag']}】{p['title']}")
            bul.append([p["text"][:180], 1])
        slides.append({"title": "支撑依据" + (f"（{i // 3 + 1}）" if len(e["points"]) > 3 else ""), "bullets": bul})
    if e.get("risks"):
        slides.append({"title": "风险情景", "bullets": [e["risks"]["text"]]})
    if e.get("market"):
        slides.append({"title": "市场含义", "bullets": [e["market"]["text"][:400]]})
    return slides


def blocks_to_md(blocks):
    out = []
    for b in blocks:
        if "h1" in b:
            out.append("# " + b["h1"])
        elif "h2" in b:
            out.append("## " + b["h2"])
        elif "h3" in b:
            out.append("### " + b["h3"])
        elif "p" in b:
            out.append(b["p"])
        elif "small" in b:
            out.append("> " + b["small"])
        elif "bullets" in b:
            out += ["- " + str(x) for x in b["bullets"]]
        elif "table" in b:
            t = b["table"]
            head = t.get("head") or []
            if head:
                out.append("| " + " | ".join(str(h) for h in head) + " |")
                out.append("|" + "---|" * len(head))
            for row in t.get("rows") or []:
                out.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------ 搜索
def search(q, limit=40):
    q = (q or "").strip().lower()
    if not q:
        return {"query": q, "groups": []}
    res = {"指标": [], "市场": [], "方法论": [], "计算方法": [], "预测因子": []}
    for ind in INDICATORS:
        hay = " ".join(str(x) for x in [ind["id"], ind["name"], ind["short"], ind["l1"], ind["l2"], ind.get("theory", ""),
                                        " ".join(ind.get("keywords") or []), ind["unit"]]).lower()
        if q in hay:
            s = engine._state["series"].get(ind["id"]) or {}
            pm = engine.pending_month(ind["id"]) if s.get("months") else None
            b = engine.basis(ind["id"]) if s.get("months") else None
            res["指标"].append({"id": ind["id"], "name": ind["name"], "country": ind["country"], "l1": ind["l1"], "l2": ind["l2"],
                              "unit": ind["unit"], "freq": ind["freq"], "role": ind["role"], "theory": ind.get("theory"),
                              "last_month": (s.get("months") or [None])[-1], "last_value": (s.get("values") or [None])[-1],
                              "pending": engine.month_label(pm, ind["freq"]) if pm else None,
                              "pred": ((b or {}).get("conclusion") or {}).get("value"), "release": ind["release"]})
    for k, name, mkt, typ, secid, tx in markets.META:
        if q in f"{k} {name} {mkt}".lower():
            ser = markets.series(k)
            lm = max(ser) if ser else None
            res["市场"].append({"key": k, "name": name, "market": mkt, "type": typ, "last_month": lm, "last": ser.get(lm) if lm else None})
    for m in methodology.INSTITUTIONS:
        if q in (m["org"] + m["name"] + m["core"] + m["use"] + m["scope"]).lower():
            res["方法论"].append({k: m[k] for k in ("id", "org", "name", "scope", "core", "formula", "accuracy", "use", "ref")})
    for m in methodology.FORMULAS:
        if q in (m["name"] + m["formula"] + m["how"]).lower():
            res["计算方法"].append(m)
    for k, v in methodology.FACTORS.items():
        if q in k.lower() or any(q in x.lower() for x in v):
            res["预测因子"].append({"category": k, "factors": v})
    return {"query": q, "groups": [{"name": k, "items": v[:limit]} for k, v in res.items() if v],
            "total": sum(len(v) for v in res.values())}
