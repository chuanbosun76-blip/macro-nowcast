/* 观数 · 宏观预测平台 v3（原生 JS，无框架） */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const S = { meta: null, country: "CN", view: "overview", status: null, ov: {}, seriesCache: {}, chat: [], settings: null, hier: null, meth: null, aiText: "", freq: {} };
const VIEW_TITLE = { overview: "总览", live: "实时看板", guide: "使用教程", predict: "预测中心", data: "数据库", search: "搜索", report: "报告生成", reports: "研报", backtest: "回测", archive: "预测档案", ask: "问 AI", settings: "设置" };
const REC_NAME = { persist: "沿用上期", ar: "SARIMAX", mf: "多因子回归", bridge: "桥方程", ai: "AI 研判", ref: "参考" };
const MODE_SHORT = { title: "AI·标题", chunk: "AI·正文", title_ar: "AI·标题+AR", data: "AI·纯数据" };
const MODES_ORDER = ["title", "chunk", "title_ar", "data"];
const COUNTRY_NAME = { CN: "中国", US: "美国" };
const FREQ_NAME = { M: "月度", Q: "季度", A: "年度" };

/* ---------------- 基础 ---------------- */
function pwd() { try { return localStorage.getItem("nowcast_pwd") || ""; } catch (e) { return ""; } }
async function api(path, opts = {}) {
  const headers = Object.assign({ "X-Access-Password": pwd() }, opts.headers || {});
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  let j = null; try { j = await r.json(); } catch (e) { j = { error: `HTTP ${r.status}` }; }
  if (r.status === 401) promptPwd();
  if (!r.ok) { const err = new Error((j && j.error) || `HTTP ${r.status}`); err.status = r.status; err.body = j; throw err; }
  return j;
}
function promptPwd() {
  openModal(`<h2>需要访问口令</h2><p class="muted">运行 AI、刷新数据、修改设置需要站点口令（部署时设置的 ACCESS_PASSWORD）。口令只保存在本浏览器。</p>
    <div class="ctl-row"><input type="password" id="pwdModal" placeholder="输入访问口令"><button class="btn primary" id="pwdModalSave">保存并重试</button></div>`);
  const save = () => { try { localStorage.setItem("nowcast_pwd", $("#pwdModal").value); } catch (e) { } $("#modal").hidden = true; };
  $("#pwdModalSave").onclick = save; $("#pwdModal").addEventListener("keydown", ev => { if (ev.key === "Enter") save(); });
  setTimeout(() => $("#pwdModal").focus(), 50);
}
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function ind(id) { return (S.meta.indicators || []).find(x => x.id === id); }
function fmtV(v, unit, sign) {
  if (v == null || !isFinite(v)) return "—";
  let s;
  if (["亿元", "千人", "千套", "万套"].includes(unit)) s = Math.round(v).toLocaleString("zh-CN");
  else if (unit === "亿美元") s = (Math.round(v * 10) / 10).toLocaleString("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  else s = (Math.round(v * 100) / 100).toFixed(Math.abs(v) < 10 ? 2 : 1);
  if (sign && v > 0) s = "+" + s;
  return s;
}
function fmtC(v) { return v == null || !isFinite(v) ? "—" : v.toFixed(2); }
function pctS(v) { return v == null ? "—" : (v * 100).toFixed(0) + "%"; }
function monthLabel(m, freq) {
  if (!m) return "—";
  if (freq === "Q") return `${m.slice(0, 4)}年Q${Math.ceil(+m.slice(5, 7) / 3)}`;
  if (freq === "A") return `${m.slice(0, 4)}年`;
  return `${m.slice(0, 4)}年${+m.slice(5, 7)}月`;
}
function openModal(html) { $("#modalBody").innerHTML = html; $("#modal").hidden = false; }
function openDrawer(html) { $("#drawerBody").innerHTML = html; $("#drawer").hidden = false; $(".drawer-card").scrollTop = 0; }
$("#modalX").onclick = () => { $("#modal").hidden = true; };
$("#drawerX").onclick = () => { $("#drawer").hidden = true; };
$("#modal").onclick = ev => { if (ev.target.id === "modal") $("#modal").hidden = true; };
$("#drawer").onclick = ev => { if (ev.target.id === "drawer") $("#drawer").hidden = true; };
document.addEventListener("keydown", ev => { if (ev.key === "Escape") { $("#modal").hidden = true; $("#drawer").hidden = true; } });
function mdLite(t) { return esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/^#{1,4}\s*(.+)$/gm, "<b>$1</b>").replace(/^\s*[-•]\s+/gm, "· "); }
function fillSelect(sel, opts, val) { if (!sel) return; sel.innerHTML = opts.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join(""); if (val != null) sel.value = val; }
function modelOpts() { return (S.status && S.status.models || []).map(m => [m.id, m.label]); }
function countryInds(role) { return (S.meta.indicators || []).filter(i => i.country === S.country && (!role || role.includes(i.role))); }

/* ---------------- 图表 ---------------- */
function lineChart(el, cfg) {
  const W = Math.max(el.clientWidth || 800, 320), H = cfg.height || 320, pad = { l: 58, r: 16, t: 14, b: 30 };
  const months = cfg.months;
  if (!months.length) { el.innerHTML = '<div class="skel">暂无数据</div>'; return; }
  const all = []; cfg.series.forEach(s => months.forEach(m => { const v = s.data[m]; if (v != null && isFinite(v)) all.push(v); }));
  if (!all.length) { el.innerHTML = '<div class="skel">暂无数据</div>'; return; }
  let lo = Math.min(...all), hi = Math.max(...all);
  if (cfg.clip && all.length > 20) { const srt = [...all].sort((a, b) => a - b); lo = srt[Math.floor(srt.length * 0.01)]; hi = srt[Math.ceil(srt.length * 0.99) - 1]; }
  if (lo === hi) { lo -= 1; hi += 1; } const span = hi - lo; lo -= span * 0.06; hi += span * 0.06;
  const x = i => pad.l + (W - pad.l - pad.r) * (months.length === 1 ? 0.5 : i / (months.length - 1));
  const y = v => pad.t + (H - pad.t - pad.b) * (1 - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo));
  const ticks = niceTicks(lo, hi, 5);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img">`;
  ticks.forEach(t => { svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}" stroke="#eef1f5"/><text x="${pad.l - 8}" y="${y(t) + 4}" font-size="11" text-anchor="end" fill="#8a97a6">${fmtTick(t)}</text>`; });
  if (lo < 0 && hi > 0) svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(0)}" y2="${y(0)}" stroke="#b9b2a4" stroke-dasharray="3 3"/>`;
  const step = Math.max(1, Math.ceil(months.length / Math.floor((W - pad.l) / 70)));
  months.forEach((m, i) => { if (i % step === 0) svg += `<text x="${x(i)}" y="${H - 8}" font-size="11" text-anchor="middle" fill="#8a97a6">${m.slice(2).replace("-", "/")}</text>`; });
  if (cfg.shadeFrom) { const i0 = months.indexOf(cfg.shadeFrom); if (i0 >= 0) svg += `<rect x="${x(i0) - 8}" y="${pad.t}" width="${Math.max(16, W - pad.r - x(i0) + 8)}" height="${H - pad.t - pad.b}" fill="#a8322a" opacity=".06"/>`; }
  cfg.series.forEach(s => {
    let d = "", pen = false;
    months.forEach((m, i) => { const v = s.data[m]; if (v == null || !isFinite(v)) { pen = false; return; } d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); pen = true; });
    svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 1.6}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round"/>`;
    if (s.dots) months.forEach((m, i) => { const v = s.data[m]; if (v != null && isFinite(v)) svg += `<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="${s.color}"/>`; });
    if (s.band) months.forEach((m, i) => { const b = s.band[m]; if (b) svg += `<line x1="${x(i)}" x2="${x(i)}" y1="${y(b[0])}" y2="${y(b[1])}" stroke="${s.color}" stroke-width="3" opacity=".35"/>`; });
  });
  svg += `<line id="hx" x1="0" x2="0" y1="${pad.t}" y2="${H - pad.b}" stroke="#14202e" stroke-width=".6" opacity="0"/><rect x="${pad.l}" y="${pad.t}" width="${W - pad.l - pad.r}" height="${H - pad.t - pad.b}" fill="transparent" class="hov"/></svg>`;
  el.innerHTML = svg;
  const rect = $(".hov", el), hx = $("#hx", el), tip = $("#tip");
  rect.addEventListener("mousemove", ev => {
    const bb = el.querySelector("svg").getBoundingClientRect(); const px = (ev.clientX - bb.left) * (W / bb.width);
    const i = Math.round((px - pad.l) / (W - pad.l - pad.r) * (months.length - 1)); if (i < 0 || i >= months.length) return;
    hx.setAttribute("x1", x(i)); hx.setAttribute("x2", x(i)); hx.setAttribute("opacity", 1); const m = months[i];
    tip.innerHTML = `<b>${monthLabel(m, cfg.freq)}</b><br>` + cfg.series.map(s => `<span style="color:${s.color === "#14202e" ? "#fff" : s.color}">■</span> ${esc(s.name)}：${fmtV(s.data[m], cfg.unit)}`).join("<br>");
    tip.hidden = false; tip.style.left = Math.min(ev.clientX + 14, innerWidth - 270) + "px"; tip.style.top = (ev.clientY + 14) + "px";
  });
  rect.addEventListener("mouseleave", () => { tip.hidden = true; hx.setAttribute("opacity", 0); });
}
function niceTicks(lo, hi, n) { const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag; const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag; const out = []; for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(+t.toFixed(10)); return out; }
function fmtTick(t) { return Math.abs(t) >= 10000 ? (t / 10000).toFixed(1) + "万" : (+t.toFixed(2)).toString(); }
function spark(values) {
  const v = (values || []).filter(x => x != null).slice(-24); if (v.length < 2) return "";
  const W = 110, H = 30, lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
  const d = v.map((a, i) => (i ? "L" : "M") + (i / (v.length - 1) * W).toFixed(1) + " " + (H - 3 - (a - lo) / r * (H - 6)).toFixed(1)).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><path d="${d}" fill="none" stroke="#44505e" stroke-width="1.3"/></svg>`;
}

/* ---------------- 状态 / 一键更新 ---------------- */
async function refreshStatus() {
  try {
    const st = await api("/api/status"); const changed = S.status && S.status.version !== st.version; S.status = st;
    if (S.meta && JSON.stringify(st.n_indicators) !== JSON.stringify(S.meta.n_indicators)) {
      try { S.meta = await api("/api/meta"); } catch (e) { }
    }
    const dot = st.error ? "bad" : (st.ready ? "ok" : "warn");
    const d = st.data || {}, src = d.source || {};
    const phase = st.ready ? (st.loading ? `就绪 · 后台${d.stage || "更新中"}` : "模型就绪") : st.loading ? (d.stage ? `${d.stage}…` : `模型计算中 ${Math.round((st.ar_progress || 0) * 100)}%`) : "等待加载";
    $("#sideStatus").innerHTML = `<div><span class="dot ${dot}"></span>${esc(phase)}</div>
      <div>中国：${esc(src.cn || "—")}</div><div>美国：${esc(src.us || "—")}</div><div>更新：${esc(d.fetched_at || "—")} · 每 ${st.refresh_hours} 小时</div>
      <div><span class="dot ${st.has_key ? "ok" : "bad"}"></span>模型：${(st.models || []).length} 个可用</div>
      <div>预测记录：${(st.runs || {}).ok || 0} 条</div>`;
    $("#topMeta").innerHTML = `指标 ${(st.n_indicators || {}).CN || 0} + ${(st.n_indicators || {}).US || 0} · 模型 <b>${esc(st.model)}</b>${st.auth_required ? " · 需口令" : ""}`;
    if (changed) refreshAll();
    return st;
  } catch (e) { $("#sideStatus").innerHTML = `<span class="dot bad"></span>服务不可达`; return null; }
}
function refreshAll() { S.ov = {}; S.seriesCache = {}; S.hier = null; show(S.view); }
async function syncAll() {
  const btn = $("#syncBtn"); btn.disabled = true;
  try { await api("/api/sync", { method: "POST", json: { predict: false } }); } catch (e) { btn.disabled = false; alertBox(e); return; }
  const poll = async () => {
    let u; try { u = await api("/api/sync_status"); } catch (e) { setTimeout(poll, 3000); return; }
    $("#syncBar").innerHTML = `<div class="job"><b>一键更新</b> · ${esc(u.stage || "")}${u.error ? ` <span class="err">${esc(u.error)}</span>` : ""}
      <div class="bar"><i style="width:${u.pct || 0}%"></i></div>
      ${(u.changed || []).length ? `<div class="hint">本次新增数据：${u.changed.map(esc).join("、")}</div>` : ""}</div>`;
    if (u.running) { setTimeout(poll, 2000); return; }
    btn.disabled = false;
    await refreshStatus(); refreshAll();
    setTimeout(() => { $("#syncBar").innerHTML = ""; }, 8000);
  };
  setTimeout(poll, 800);
}

/* ---------------- 总览（分层） ---------------- */
async function loadOverview() {
  let rows;
  try { rows = (await api(`/api/overview?country=${S.country}`)).rows; }
  catch (e) {
    if (e.status === 503) { $("#ovGroups").innerHTML = `<div class="skel">数据加载与模型计算中…</div>`; setTimeout(() => { if (S.view === "overview") loadOverview(); }, 3000); return; }
    $("#ovGroups").innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; return;
  }
  S.ov[S.country] = rows;
  if (!S.hier) { try { S.hier = (await api("/api/hierarchy")).hierarchy; } catch (e) { S.hier = null; } }
  const st = S.status || {};
  const now = rows.filter(r => r.role === "nowcast"), withAI = now.filter(r => r.ai), missing = rows.filter(r => r.missing);
  const byFreq = f => rows.filter(r => r.freq === f && !r.missing).length;
  $("#kpis").innerHTML = [
    ["指标总数", rows.filter(r => !r.missing).length, `月度 ${byFreq("M")} · 季度 ${byFreq("Q")} · 年度 ${byFreq("A")}`],
    ["待发布 · 实时预测", now.length, "五法并行：沿用上期 / SARIMAX / 多因子 / 桥方程 / AI"],
    ["AI 已覆盖", `${withAI.length}/${now.length}`, withAI.length ? "最近：" + (withAI[0].ai.created_at || "").slice(5, 16) : "去预测中心一键运行"],
    ["数据更新", (st.data || {}).fetched_at || "—", ((st.data || {}).source || {})[S.country.toLowerCase()] || ""],
  ].map(([k, v, s]) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join("");
  const blocks = (S.hier && S.hier[S.country]) || [];
  const map = Object.fromEntries(rows.map(r => [r.id, r]));
  let html = "";
  for (const blk of blocks) {
    const n = blk.groups.reduce((a, g) => a + g.items.length, 0);
    html += `<div class="l1-h">${esc(blk.l1)}<small>${n} 项</small><span class="line"></span></div>`;
    for (const g of blk.groups) {
      const rs = g.items.map(i => map[i.id]).filter(Boolean);
      if (!rs.length) continue;
      const main = rs.filter(r => r.role !== "ref" && !r.missing), ref = rs.filter(r => r.role === "ref" || r.missing);
      html += `<div class="l2-h">${esc(g.l2)}<small class="muted">${rs.length} 项</small></div>`;
      if (main.length) html += `<div class="cards">${main.map(cardHTML).join("")}</div>`;
      if (ref.length) html += `<div class="cards" style="margin-top:8px">${ref.map(refCardHTML).join("")}</div>`;
    }
  }
  $("#ovGroups").innerHTML = html || `<div class="skel">暂无数据</div>`;
  $$("[data-detail]").forEach(b => b.onclick = () => showDetail(b.dataset.detail));
  $$("[data-run]").forEach(b => b.onclick = () => runOne(b.dataset.run, b));
}
function cardHTML(r) {
  const chg = r.prev_value != null ? r.last_value - r.prev_value : null;
  const b = r.basis || {}, best = r.recommend, ai = r.ai;
  const box = (key, label, v, sub) => `<div class="pv-box ${best === key ? "best" : ""}"><span class="k">${label}</span><span class="x">${fmtV(v, r.unit)}</span><div class="s">${sub}</div></div>`;
  const bridge = b.bridge;
  return `<article class="card">
    <div class="card-h"><div><div class="nm">${esc(r.name)}</div><div class="grp">${esc(r.unit || "指数")} · ${FREQ_NAME[r.freq]} · ${esc(r.release)}</div></div><span class="tag ${best}">推荐：${REC_NAME[best]}</span></div>
    <div class="last"><span class="v">${fmtV(r.last_value, r.unit)}</span><span class="u">${esc(r.unit)} · ${monthLabel(r.last_month, r.freq)}已公布</span>
      ${chg != null ? `<span class="chg ${chg > 0 ? "up" : chg < 0 ? "down" : ""}">${chg > 0 ? "▲" : chg < 0 ? "▼" : "—"} ${fmtV(Math.abs(chg), r.unit)}</span>` : ""}${spark((r.history || []).map(h => h[1]))}</div>
    <div class="pend">本次预测 → <b>${monthLabel(r.pending_month, r.freq)}</b>${r.release_est ? `<span class="muted"> · 预计 ${esc(r.release_est.slice(5).replace("-", "/"))} 公布</span>` : ""}</div>
    <div class="preds">
      ${box("persist", "沿用上期", r.persist_pred, `corr ${fmtC(r.persist_corr)}`)}
      ${box("ar", "SARIMAX", r.ar_pred, `${esc(r.ar_order || "")} · ${fmtC(r.ar_corr)}`)}
      ${box("mf", "多因子", r.mf_pred, `${(r.mf_features || []).length} 因子 · ${fmtC(r.mf_corr)}`)}
      ${bridge ? box("bridge", "桥方程", bridge.value, `已公布 ${bridge.n_current}/3 月`) : ""}
      ${box("ai", "AI 研判", ai ? ai.value : null, ai ? `${ai.low != null ? fmtV(ai.low, r.unit) + "~" + fmtV(ai.high, r.unit) : ""} ${esc(ai.confidence || "")}` : "待运行")}
    </div>
    ${ai && ai.reason ? `<div class="ai-sum"><b>AI：</b>${esc(ai.reason)}</div>` : `<div class="why">${esc(r.why || "")}</div>`}
    <details class="basis-d"><summary>预测依据 · 五种方法的完整推导</summary>${basisHTML(r.basis, r)}</details>
    <div class="card-f"><span class="hint">${b.combo ? `组合值 ${fmtV(b.combo.value, r.unit)}` : ""}</span><span><button class="btn sm ghost" data-detail="${r.id}">完整依据</button> <button class="btn sm" data-run="${r.id}">AI 预测</button></span></div>
  </article>`;
}
function refCardHTML(r) {
  if (r.missing) return `<article class="card missing"><div class="card-h"><div class="nm">${esc(r.name)}</div><span class="tag ref">数据源</span></div><div class="hint">${esc((r.notes || []).join("；") || "暂无数据")}</div></article>`;
  const chg = r.prev_value != null ? r.last_value - r.prev_value : null;
  return `<article class="card"><div class="card-h"><div><div class="nm">${esc(r.name)}</div><div class="grp">${FREQ_NAME[r.freq]} · ${esc(r.release)}</div></div><span class="tag ref">参考</span></div>
    <div class="last"><span class="v">${fmtV(r.last_value, r.unit)}</span><span class="u">${esc(r.unit)} · ${monthLabel(r.last_month, r.freq)}</span>${chg != null ? `<span class="chg ${chg > 0 ? "up" : chg < 0 ? "down" : ""}">${chg > 0 ? "▲" : chg < 0 ? "▼" : "—"} ${fmtV(Math.abs(chg), r.unit)}</span>` : ""}${spark((r.history || []).map(h => h[1]))}</div>
    <div class="card-f"><span class="hint">${esc(r.theory || "")}</span><button class="btn sm ghost" data-detail="${r.id}">详情</button></div></article>`;
}

/* ---------------- 依据 / 证据 ---------------- */
function recentTable(rows, unit) {
  if (!rows || !rows.length) return "";
  return `<table class="mini"><tr><th>期间</th>${rows.map(r => `<th>${r[0].slice(2).replace("-", "/")}</th>`).join("")}</tr><tr><td>真实</td>${rows.map(r => `<td>${fmtV(r[1], unit)}</td>`).join("")}</tr><tr><td>SARIMAX 事前</td>${rows.map(r => `<td>${fmtV(r[2], unit)}</td>`).join("")}</tr></table>`;
}
function basisHTML(b, r) {
  if (!b) return `<div class="hint">数据加载中</div>`;
  const unit = r.unit || "", c = b.conclusion || {};
  const combo = b.combo ? `<div class="basis-row"><span class="k">⑤ 组合预测</span><div><b>${fmtV(b.combo.value, unit)}</b> — Bates–Granger 逆均方误差加权：${Object.entries(b.combo.weights).map(([k, v]) => `${REC_NAME[k] || k} ${(v * 100).toFixed(0)}%`).join("，")}。</div></div>` : "";
  return `<div class="basis">
    <div class="basis-row tgt"><span class="k">预测对象</span><div><b>${esc(b.target_label)} ${esc(r.name)}</b> <span class="muted">${b.release_est ? "预计 " + esc(b.release_est) + " 公布" : ""}（发布规律：${esc(b.release_rule)}）</span><br><span class="muted">已公布至 ${monthLabel(b.last_month, r.freq)}：${fmtV(b.last_value, unit)} ${esc(unit)}</span></div></div>
    ${b.modeled ? `<div class="basis-row con"><span class="k">综合结论</span><div>${esc(c.text || "")}</div></div>` : ""}
    <div class="basis-row"><span class="k">① 沿用上期</span><div><b>${fmtV(b.persist.value, unit)}</b> — ${esc(b.persist.text)}</div></div>
    <div class="basis-row"><span class="k">② SARIMAX</span><div>${b.ar ? `<b>${fmtV(b.ar.value, unit)}</b>${b.ar.band ? ` <span class="muted">[${fmtV(b.ar.band[0], unit)}, ${fmtV(b.ar.band[1], unit)}]</span>` : ""} — ${esc(b.ar.text)}${recentTable(b.ar.recent, unit)}` : "样本不足，未建模。"}</div></div>
    <div class="basis-row"><span class="k">③ 多因子回归</span><div>${b.mf ? `<b>${fmtV(b.mf.value, unit)}</b> — ${esc(b.mf.text)}` : "样本不足，未建模。"}</div></div>
    ${b.bridge ? `<div class="basis-row"><span class="k">④ 桥方程</span><div><b>${fmtV(b.bridge.value, unit)}</b> — ${esc(b.bridge.text)}</div></div>` : ""}
    <div class="basis-row"><span class="k">${b.bridge ? "⑤" : "④"} AI 研判</span><div>${b.ai ? `<b>${fmtV(b.ai.value, unit)}</b>${b.ai.low != null ? ` <span class="muted">[${fmtV(b.ai.low, unit)}, ${fmtV(b.ai.high, unit)}]</span>` : ""} — ${esc(b.ai.reason || "")}${analysisHTML(b.ai, unit)}` : `尚未运行。点击「AI 预测」后：召回 ${esc(b.target_label)} 截止前的研报（含直达链接）+ 平台数据库 + 上述统计模型参考，输出数值、区间、驱动因素、传导机制、证据与风险。`}</div></div>
    ${combo}
    <div class="basis-row"><span class="k">理论驱动</span><div>${esc(b.theory || "")}</div></div>
  </div>`;
}
function evidenceHTML(e, m) {
  if (!e) return `<div class="skel">无依据</div>`;
  const c = e.conclusion, unit = c.unit || "";
  const risk = e.risks ? `<h3 style="margin:16px 0 6px">风险与情景</h3>
    <div class="ev-risk"><div class="opt"><b>${fmtV(e.risks.up, unit)}</b><small>乐观 · 80% 上界</small></div>
      <div class="base"><b>${fmtV(e.risks.base, unit)}</b><small>基准</small></div>
      <div class="pes"><b>${fmtV(e.risks.down, unit)}</b><small>悲观 · 80% 下界</small></div>
      <div class="base"><b>${fmtV(e.risks.down_ext, unit)}~${fmtV(e.risks.up_ext, unit)}</b><small>95% 区间</small></div></div>
    <p class="hint">${esc(e.risks.text)}</p>` : "";
  const mk = e.market ? `<h3 style="margin:16px 0 6px">对股市 / 债市的含义</h3><p class="hint">${esc(e.market.text)}</p>
    <div class="tbl-wrap"><table class="bt"><tr><th>资产</th><th>本次隐含</th><th>β<small>每1σ惊喜</small></th><th>t 值</th><th>R²</th><th>方向一致率</th><th>理论方向</th></tr>
    ${e.market.rows.map(x => { const r = x.release_month || {}; const sig = r.t != null && Math.abs(r.t) >= 1.96;
      return `<tr class="${sig ? "sig" : ""}"><td>${esc(x.name)} <small class="muted">${x.market}</small></td><td class="mono"><b>${x.implied_move > 0 ? "+" : ""}${(x.implied_move || 0).toFixed(2)}${x.unit}</b></td>
      <td class="mono">${r.beta_std != null ? (r.beta_std > 0 ? "+" : "") + r.beta_std.toFixed(2) + x.unit : "—"}</td><td class="mono">${r.t != null ? r.t.toFixed(2) : "—"}${sig ? " *" : ""}</td>
      <td class="mono">${r.r2 != null ? (r.r2 * 100).toFixed(1) + "%" : "—"}</td><td class="mono">${r.hit != null ? (r.hit * 100).toFixed(0) + "%" : "—"}</td>
      <td class="${x.sign_theory > 0 ? "up" : x.sign_theory < 0 ? "down" : ""}">${x.sign_theory > 0 ? "▲ 利多/上行" : x.sign_theory < 0 ? "▼ 利空/下行" : "○ 视周期"}</td></tr>`; }).join("")}</table></div>` : "";
  const meths = (e.methods || []).map(x => `<div class="meth-card"><div class="org">${esc(x.org)}</div><h4>${esc(x.name)}</h4>
    <p>${esc(x.core)}</p><div class="formula">${esc(x.formula)}</div>
    <p class="hint"><b>精度：</b>${esc(x.accuracy || "—")}<br><b>本平台应用：</b>${esc(x.use)}<br><b>来源：</b>${esc(x.ref)}</p></div>`).join("");
  return `<div class="ev-con"><div class="lbl">结论 · ${esc(c.label || "")}</div>
      <div class="big">${fmtV(c.value, unit)}<small>${esc(unit)}</small>${c.band ? `<small> ｜ 80% 区间 ${fmtV(c.band[0], unit)} ~ ${fmtV(c.band[1], unit)}</small>` : ""}</div>
      <div class="txt">${esc(c.text)}</div>
      <div class="chips"><span>方法：${REC_NAME[c.method] || c.method || ""}</span><span>方向：${esc(c.direction)}</span><span>较上期 ${c.change != null ? (c.change > 0 ? "+" : "") + fmtV(c.change, unit) : "—"}</span><span>频率：${esc(e.frequency || "")}</span></div></div>
    <h3 style="margin:14px 0 8px">支撑依据（${e.points.length} 条，每条均可核验）</h3>
    ${e.points.map(p => `<div class="ev-pt"><div class="h"><span class="no">${p.no}</span><span class="ti">${esc(p.title)}</span><span class="tg">${esc(p.tag)}</span></div>
      <div class="bd">${esc(p.text)}</div>
      ${(p.numbers || []).length ? `<div class="ev-nums">${p.numbers.filter(n => n[1] != null && n[1] !== "—").map(n => `<span>${esc(n[0])} <b>${esc(n[1])}</b></span>`).join("")}</div>` : ""}
      ${p.method ? `<div class="ev-m">方法：${esc(p.method)}</div>` : ""}</div>`).join("")}
    ${risk}${mk}
    <h3 style="margin:16px 0 6px">常用预测因子（分析师口径）</h3>
    <div class="chips">${(e.factors || []).map(f => `<span class="chip" style="cursor:default">${esc(f)}</span>`).join("") || "—"}</div>
    <h3 style="margin:16px 0 6px">本指标适用的机构方法论</h3>${meths}`;
}
function viewsHTML(vw, unit, id) {
  if (!vw) return "";
  const tabs = ["M", "Q", "A"].filter(f => vw[f]);
  if (!tabs.length) return "";
  const cur = S.freq[id] && tabs.includes(S.freq[id]) ? S.freq[id] : vw.native;
  const v = vw[cur] || vw[tabs[0]];
  const c = v.current;
  const hist = (v.history || []).slice().reverse();
  const prog = c ? Math.round((c.share_realized != null ? c.share_realized : (c.n_realized / Math.max(1, c.n_total))) * 100) : 0;
  return `<div class="freq-tabs" data-freqtabs="${id}">${tabs.map(f => `<button data-f="${f}" class="${f === cur ? "on" : ""}">${FREQ_NAME[f]}${f === vw.native ? "" : "（派生）"}</button>`).join("")}</div>
    ${c ? `<div class="vw-cur"><div><div class="hint">${esc(c.label || "")}</div><div class="big">${fmtV(c.value, unit)}<small class="muted"> ${esc(unit)}</small></div></div>
      <div class="vw-prog"><div class="hint">已公布 ${c.n_realized}/${c.n_total} 期${c.realized_only != null ? ` · 已实现部分 ${fmtV(c.realized_only, unit)}` : ""}</div><div class="bar"><i style="width:${prog}%"></i></div>
        ${(c.forecast || []).length ? `<div class="hint">外推：${c.forecast.map(f => `${f[0].slice(5)}月 ${fmtV(f[1], unit)}（${esc(f[2])}）`).join("、")}</div>` : ""}
        ${c.note ? `<div class="hint">${esc(c.note)}</div>` : ""}</div></div>` : ""}
    <div class="tbl-wrap" style="max-height:240px"><table><tr><th>期间</th><th>数值</th>${hist[0] && hist[0].length > 2 ? "<th>含期数</th>" : ""}</tr>
      ${hist.map(h => `<tr><td>${monthLabel(h[0], cur)}</td><td class="mono">${fmtV(h[1], unit)} ${esc(unit)}</td>${h.length > 2 ? `<td class="mono">${h[2]}</td>` : ""}</tr>`).join("")}</table></div>
    ${v.bridge ? `<p class="hint">桥方程：以 ${esc(v.bridge.sample)} 共 ${v.bridge.n} 个季度估计，R²=${fmtC(v.bridge.r2)}，样本外 RMSE ${fmtC(v.bridge.rmse_oos)}；因子 ${(v.bridge.names || []).join("、")}。</p>` : ""}`;
}
function bindFreqTabs(root, onChange) {
  $$("[data-freqtabs]", root).forEach(box => $$("button", box).forEach(b => b.onclick = () => { S.freq[box.dataset.freqtabs] = b.dataset.f; onChange(); }));
}

/* ---------------- 详情抽屉 ---------------- */
function analysisHTML(r, unit) {
  const a = (r && r.analysis) || {};
  const li = arr => (arr || []).map(x => `<li>${esc(x)}</li>`).join("");
  const refs = (a.titles || []).slice(0, 12).map(t => `<a href="${esc(t.url || "#")}" target="_blank" rel="noopener">${esc(t.date)} ${esc(t.org)}：${esc(t.title)}</a>`).join("");
  return `<div class="ana">
    ${a.direction ? `<div><span class="pill">方向：${esc(a.direction)}</span> <span class="pill">置信：${esc(r.confidence || "—")}</span> <span class="pill">区间：${fmtV(r.low, unit)} ~ ${fmtV(r.high, unit)}</span> <span class="pill">${esc(r.model || "")} · ${MODE_SHORT[a.mode_used || r.mode] || ""}</span></div>` : ""}
    ${a.drivers ? `<h4>驱动因素</h4><ul>${li(a.drivers)}</ul>` : ""}
    ${a.mechanism ? `<h4>传导机制与理论依据</h4><div>${esc(a.mechanism)}</div>` : ""}
    ${a.evidence ? `<h4>证据</h4><ul>${li(a.evidence)}</ul>` : ""}
    ${a.risks ? `<h4>风险</h4><ul>${li(a.risks)}</ul>` : ""}
    ${a.vs_models ? `<h4>与统计模型的差异</h4><div>${esc(a.vs_models)}</div>` : ""}
    ${refs ? `<h4>参考研报（${(a.titles || []).length} 篇，点击直达）</h4><div class="refs">${refs}</div>` : ""}
    ${r && r.id ? `<p class="hint" style="margin-top:8px"><a href="#" data-run-id="${r.id}">查看完整 Prompt 与原始输出</a></p>` : ""}</div>`;
}
async function getSeries(id, force) {
  if (!force && S.seriesCache[id] && Date.now() - S.seriesCache[id]._t < 30000) return S.seriesCache[id];
  const d = await api(`/api/series/${id}`); d._t = Date.now(); S.seriesCache[id] = d; return d;
}
async function showDetail(id) {
  const m = ind(id);
  openDrawer(`<h2>${esc(m.name)}</h2><div class="hint">${esc(m.l1)} / ${esc(m.l2)} · ${FREQ_NAME[m.freq]} · ${esc(m.release)} · ${esc(m.theory || "")}</div>
    <div class="ctl-row" style="margin-top:10px"><button class="btn sm" data-export="docx|indicator|${id}">导出 Word</button><button class="btn sm" data-export="pptx|indicator|${id}">导出 PPT</button><button class="btn sm" data-export="xlsx|indicator|${id}">导出 Excel</button></div>
    <div class="legend" id="dLegend" style="margin:10px 0"></div><div class="chart" id="dChart"></div><div class="stat-row" id="dStat"></div>
    <h3 style="margin:14px 0 6px">多频率口径</h3><div id="dViews" class="skel">加载中…</div>
    <h3 style="margin:18px 0 6px">预测依据 · 结论先行</h3><div id="dEv" class="skel">计算中…</div>`);
  bindExport($("#drawerBody"));
  const ser = await getSeries(id, true);
  const from = ser.months[Math.max(0, ser.months.length - 72)], months = ser.months.filter(x => x >= from).concat(ser.pending_month ? [ser.pending_month] : []);
  const act = Object.fromEntries(ser.months.map((x, i) => [x, ser.values[i]]));
  const series = [{ name: "真实值", color: "#14202e", data: act, width: 2.2 }];
  if (Object.keys(ser.persist).length) series.push({ name: "沿用上期", color: "#9aa3ad", data: ser.persist, dash: "4 3" });
  if (Object.keys(ser.ar).length) series.push({ name: "SARIMAX", color: "#1d6b73", data: Object.assign({}, ser.ar, ser.ar_nowcast != null ? { [ser.pending_month]: ser.ar_nowcast } : {}) });
  if (ser.mf && Object.keys(ser.mf).length) series.push({ name: "多因子回归", color: "#5a4a9c", data: Object.assign({}, ser.mf, ser.mf_nowcast != null ? { [ser.pending_month]: ser.mf_nowcast } : {}), dash: "6 3" });
  if (ser.llm && ser.llm.title) series.push({ name: "AI 回测", color: "#a8832f", data: ser.llm.title, dots: true });
  const live = (ser.live || [])[0];
  if (live) series.push({ name: "AI 当期", color: "#a8322a", data: { [ser.pending_month]: live.value }, dots: true, band: live.low != null ? { [ser.pending_month]: [live.low, live.high] } : null });
  $("#dLegend").innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
  lineChart($("#dChart"), { months, series, unit: m.unit, freq: m.freq, shadeFrom: ser.pending_month, clip: true, height: 300 });
  const d = ser.diag || {};
  $("#dStat").innerHTML = `<span>最新 <b>${monthLabel(ser.months[ser.months.length - 1], m.freq)} ${fmtV(ser.values[ser.values.length - 1], m.unit)}</b></span>
    <span>样本 <b>${ser.months.length}</b> 期（${ser.months[0]} 起）</span>
    ${d.final_order ? `<span>SARIMAX <b>${esc(d.final_order)}</b></span><span>ADF p <b>${d.adf_p != null ? d.adf_p.toFixed(3) : "—"}</b></span>` : ""}
    <span>${esc((ser.notes || []).join("；"))}</span>`;
  try {
    const vw = (await api(`/api/views/${id}`)).views;
    const draw = () => { $("#dViews").className = ""; $("#dViews").innerHTML = viewsHTML(vw, m.unit, id); bindFreqTabs($("#dViews"), draw); };
    draw();
  } catch (e) { $("#dViews").innerHTML = `<div class="hint">${esc(e.message)}</div>`; }
  try {
    const ev = await api(`/api/evidence/${id}`);
    $("#dEv").className = ""; $("#dEv").innerHTML = evidenceHTML(ev, m);
  } catch (e) { $("#dEv").innerHTML = `<div class="hint">${esc(e.message)}</div>`; }
  const runs = await api(`/api/runs?indicator=${id}&limit=20&ok=1`).catch(() => []);
  const mp = ser.months_predictable || {};
  const monthOpts = (mp.live ? `<option value="${mp.live}">${monthLabel(mp.live, m.freq)}（当期 · 尚未公布）</option>` : "") + (mp.backtest || []).map(x => `<option value="${x}">${monthLabel(x, m.freq)}（回测 · 真实值 ${fmtV(act[x], m.unit)}）</option>`).join("");
  $("#drawerBody").insertAdjacentHTML("beforeend",
    (live ? `<h3 style="margin-top:16px">AI 当期研判 · ${monthLabel(live.target_month, m.freq)} → <span class="up">${fmtV(live.value, m.unit)} ${esc(m.unit)}</span></h3><div class="sum">${esc(live.reason || "")}</div>${analysisHTML(live, m.unit)}` : "") +
    `<div class="ctl-row" style="margin-top:12px"><label>预测期<select id="dMonth">${monthOpts}</select></label><button class="btn primary sm" data-run="${id}">运行 AI 预测</button><span class="hint">当期 = 用最新研报与数据预测尚未公布的值；历史期 = 只用该期截止前的信息，与真实值对照</span></div><div id="dJob"></div>` +
    ((runs || []).length > 1 ? `<h3 style="margin-top:14px">历史记录</h3><div class="tbl-wrap"><table class="arc"><tr><th>时间</th><th>目标期</th><th>预测</th><th>真实</th><th>模型</th><th>结论</th></tr>` +
      runs.map(x => `<tr><td>${esc((x.created_at || "").slice(0, 16))}</td><td>${x.target_month}</td><td><b>${fmtV(x.value, m.unit)}</b></td><td>${fmtV(act[x.target_month], m.unit)}</td><td>${esc(x.model)}</td><td>${esc((x.reason || "").slice(0, 70))} <a href="#" data-run-id="${x.id}">详情</a></td></tr>`).join("") + `</table></div>` : ""));
  bindRunLinks($("#drawerBody"));
  $$("[data-run]", $("#drawerBody")).forEach(b => b.onclick = () => runOne(b.dataset.run, b, true, ($("#dMonth") || {}).value || null));
}
function bindRunLinks(root) { $$("[data-run-id]", root).forEach(a => a.onclick = ev => { ev.preventDefault(); showRun(a.dataset.runId); }); }
async function runOne(id, btn, inDrawer, month) {
  if (btn) btn.disabled = true;
  try {
    const body = { indicators: [id], mode: ($("#pMode") || {}).value || "title", model: ($("#pModel") || {}).value || (S.status || {}).model };
    if (month) body.month = month;
    const job = await api("/api/nowcast", { method: "POST", json: body });
    const box = document.createElement("div"); (btn ? btn.closest(".card") || $("#dJob") || $("#pJob") : $("#pJob")).appendChild(box);
    trackJob(job.id, box, () => { if (btn) btn.disabled = false; if (S.view === "overview") loadOverview(); if (inDrawer) showDetail(id); if (S.view === "predict") renderPredictResults(); });
  } catch (e) { if (btn) btn.disabled = false; alertBox(e); }
}
function alertBox(e) { openModal(`<h2>操作失败</h2><p>${esc(e.message)}${e.status === 401 ? "（请先输入访问口令）" : ""}</p>`); }
function trackJob(id, box, onDone) {
  const tick = async () => {
    let j; try { j = await api(`/api/jobs/${id}`); } catch (e) { return; }
    const pct = j.total ? Math.round(j.done / j.total * 100) : 100;
    let html = `<div class="job"><b>${esc(j.label)}</b> · ${esc(j.model)} · ${j.done}/${j.total}（成功 ${j.ok}，失败 ${j.failed}${j.skipped ? `，跳过 ${j.skipped}` : ""}）${j.status === "done" ? " · 已完成" : " · 运行中…"}<div class="bar"><i style="width:${pct}%"></i></div>`;
    const res = (j.results || []).slice(-5).reverse();
    if (res.length) html += res.map(r => { const m = ind(r.indicator) || {}; return `<div>${esc(m.short || r.indicator)} ${monthLabel(r.target_month, m.freq)}：<b>${r.value != null ? fmtV(r.value, m.unit) : "—"}</b> <span class="muted">${esc((r.reason || r.error || "").slice(0, 90))}</span></div>`; }).join("");
    if (j.errors && j.errors.length) html += `<div class="err">${j.errors.slice(-3).map(esc).join("<br>")}</div>`;
    box.innerHTML = html + "</div>";
    if (j.status !== "done") setTimeout(tick, 2500); else onDone && onDone(j);
  };
  tick();
}
async function showRun(id) {
  const r = await api(`/api/runs/${id}`), m = ind(r.indicator) || {};
  openModal(`<h2>预测记录 #${r.id} · ${esc(m.name || r.indicator)}</h2><div class="kv">
    <div>目标期</div><div>${monthLabel(r.target_month, m.freq)}（信息截至 ${esc(r.cutoff)}）</div>
    <div>预测值</div><div><b>${fmtV(r.value, m.unit)} ${esc(m.unit || "")}</b>　区间 ${fmtV(r.low, m.unit)} ~ ${fmtV(r.high, m.unit)}　置信 ${esc(r.confidence || "—")}</div>
    <div>模型</div><div>${esc(r.model)} · ${MODE_SHORT[r.mode] || r.mode} · ${r.latency ? r.latency.toFixed(1) + " 秒" : ""} · ${r.tokens || "—"} tokens · 研报 ${r.n_titles || 0} 篇</div>
    <div>结论</div><div>${esc(r.reason || "—")}</div>${r.error ? `<div>错误</div><div class="up">${esc(r.error)}</div>` : ""}</div>
    ${analysisHTML(r, m.unit).replace(/<p class="hint"[\s\S]*?<\/p>/, "")}
    <h3>Prompt</h3><pre>${esc(r.prompt || "—")}</pre><h3>模型原始输出</h3><pre>${esc(r.answer_raw || "—")}</pre>${r.thinking ? `<h3>思考过程</h3><pre>${esc(r.thinking)}</pre>` : ""}`);
}

/* ---------------- 预测中心 ---------------- */
function renderPredictControls() {
  fillSelect($("#pModel"), modelOpts(), (S.settings || {}).default_model || (S.status || {}).model);
  fillSelect($("#pMode"), MODES_ORDER.map(k => [k, S.meta.modes[k]]), "title");
  const modeled = countryInds(["nowcast", "persist"]);
  fillSelect($("#pcInd"), countryInds().map(i => [i.id, `${i.l1}/${i.l2} · ${i.name}`]));
  fillSelect($("#rgInd"), countryInds().map(i => [i.id, `${i.name}`]));
  $("#aiScope").innerHTML = `<option value="">全库（${COUNTRY_NAME[S.country]}）</option>` + countryInds(["nowcast", "persist"]).map(i => `<option value="${i.id}">${esc(i.name)}</option>`).join("");
  $("#pInds").innerHTML = `<span class="chip grp">${COUNTRY_NAME[S.country]}</span>` + modeled.map(i => `<span class="chip ${i.role === "nowcast" ? "on" : ""}" data-id="${i.id}">${esc(i.short)}</span>`).join("") +
    `<span class="chip" id="pAll">全选</span><span class="chip" id="pNone">清空</span>`;
  $$("#pInds .chip[data-id]").forEach(c => c.onclick = () => { c.classList.toggle("on"); renderTargets(); });
  $("#pAll").onclick = () => { $$("#pInds .chip[data-id]").forEach(c => c.classList.add("on")); renderTargets(); };
  $("#pNone").onclick = () => { $$("#pInds .chip[data-id]").forEach(c => c.classList.remove("on")); renderTargets(); };
  const sel = $("#pMonth"), cur = sel.value, opts = ['<option value="">当期（各指标最新待公布期）</option>'];
  const now = new Date(), earliest = (S.status || {}).llm_earliest || "2017-01";
  for (let y = now.getFullYear(), mo = now.getMonth() + 1; `${y}-${String(mo).padStart(2, "0")}` >= earliest; mo--) { if (mo === 0) { mo = 12; y--; } const k = `${y}-${String(mo).padStart(2, "0")}`; opts.push(`<option value="${k}">${k.slice(0, 4)}年${+k.slice(5)}月（回测：只用当时信息）</option>`); }
  sel.innerHTML = opts.join(""); sel.value = cur || ""; sel.onchange = renderTargets;
  renderTargets();
}
async function getRows(country) {
  if (S.ov[country]) return S.ov[country];
  try { S.ov[country] = (await api(`/api/overview?country=${country}`)).rows; } catch (e) { return []; }
  return S.ov[country];
}
async function renderTargets() {
  const ids = $$("#pInds .chip.on[data-id]").map(c => c.dataset.id), month = $("#pMonth").value, rows = await getRows(S.country);
  if (!ids.length) { $("#pTargets").innerHTML = `<span class="hint">未勾选指标</span>`; return; }
  $("#pTargets").innerHTML = `<div class="hint">将预测（${ids.length} 项）：</div>` + ids.map(id => { const r = rows.find(x => x.id === id) || {}, m = ind(id); const tm = month || r.pending_month;
    return `<span class="tgt"><b>${esc(m.short)}</b> → ${monthLabel(tm, m.freq)}${!month && r.release_est ? `<i>预计 ${esc(r.release_est)} 公布</i>` : month ? `<i>回测</i>` : ""}</span>`; }).join("");
}
async function pcShow() {
  const id = $("#pcInd").value; if (!id) return;
  const m = ind(id);
  $("#pcOut").innerHTML = `<div class="skel">正在计算 ${esc(m.name)} 的结论与依据…</div>`;
  $("#pcHint").textContent = `${m.l1} / ${m.l2} · ${FREQ_NAME[m.freq]} · ${m.release}`;
  try {
    const [ev, vwr] = await Promise.all([api(`/api/evidence/${id}`), api(`/api/views/${id}`)]);
    const draw = () => {
      $("#pcOut").innerHTML = viewsHTML(vwr.views, m.unit, id) + evidenceHTML(ev, m) +
        `<div class="ctl-row" style="margin-top:12px"><button class="btn primary sm" data-run="${id}">对该指标运行 AI 研判</button>
         <button class="btn sm ghost" data-export="docx|indicator|${id}">导出 Word</button><button class="btn sm ghost" data-export="pptx|indicator|${id}">导出 PPT</button>
         <button class="btn sm ghost" data-detail="${id}">打开完整详情</button></div><div id="pcJob"></div>`;
      bindFreqTabs($("#pcOut"), draw); bindExport($("#pcOut"));
      $$("[data-run]", $("#pcOut")).forEach(b => b.onclick = () => runOne(b.dataset.run, b));
      $$("[data-detail]", $("#pcOut")).forEach(b => b.onclick = () => showDetail(b.dataset.detail));
    };
    draw();
    $("#pcFreq").innerHTML = "";
  } catch (e) { $("#pcOut").innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; }
}
async function runSelected() {
  const ids = $$("#pInds .chip.on[data-id]").map(c => c.dataset.id); if (!ids.length) return;
  $("#pRun").disabled = true;
  const body = { indicators: ids, mode: $("#pMode").value, model: $("#pModel").value }; if ($("#pMonth").value) body.month = $("#pMonth").value;
  try { const job = await api("/api/nowcast", { method: "POST", json: body }); trackJob(job.id, $("#pJob"), () => { $("#pRun").disabled = false; renderPredictResults(); }); }
  catch (e) { $("#pRun").disabled = false; alertBox(e); }
}
async function updateAndPredict() {
  const btn = $("#pUpdate"); btn.disabled = true; const box = $("#pJob");
  box.innerHTML = `<div class="job">正在拉取最新数据并增量重算模型…<div class="bar"><i style="width:10%"></i></div></div>`;
  try { await api("/api/sync", { method: "POST", json: { predict: true, mode: $("#pMode").value, model: $("#pModel").value } }); }
  catch (e) { btn.disabled = false; box.innerHTML = ""; alertBox(e); return; }
  const poll = async () => {
    let u; try { u = await api("/api/sync_status"); } catch (e) { setTimeout(poll, 3000); return; }
    if (u.error) { box.innerHTML = `<div class="job"><span class="err">更新失败：${esc(u.error)}</span></div>`; btn.disabled = false; return; }
    if (u.running || !u.job_id) { box.innerHTML = `<div class="job">${esc(u.stage)}<div class="bar"><i style="width:${u.pct || 5}%"></i></div></div>`; setTimeout(poll, 2500); return; }
    S.seriesCache = {}; S.ov = {}; await refreshStatus();
    trackJob(u.job_id, box, () => { btn.disabled = false; renderPredictResults(); });
  };
  setTimeout(poll, 1500);
}
async function renderPredictResults() {
  const rows = await api(`/api/runs?country=${S.country}&limit=300&ok=1`).catch(() => []), ov = await getRows(S.country);
  const seen = new Set(), latest = [];
  for (const r of rows) { const k = r.indicator + r.target_month; if (seen.has(k)) continue; seen.add(k); latest.push(r); }
  $("#pResults").innerHTML = latest.length ? latest.slice(0, 60).map(r => { const m = ind(r.indicator); if (!m) return ""; const o = ov.find(x => x.id === r.indicator) || {}; const isLive = r.source === "live" && r.target_month === o.pending_month; const act = (o.history || []).find(h => h[0] === r.target_month);
    return `<div class="res ${isLive ? "" : "bt"}"><div class="res-h"><span class="nm">${esc(m.name)} · <b>${monthLabel(r.target_month, m.freq)}</b> ${isLive ? `<span class="pill live">当期 · 尚未公布${o.release_est ? " · 预计 " + esc(o.release_est) : ""}</span>` : `<span class="pill">回测${act ? " · 真实值 " + fmtV(act[1], m.unit) : ""}</span>`}</span><span class="val">${fmtV(r.value, m.unit)} <small>${esc(m.unit)}</small>${r.low != null ? `<small class="muted"> 区间 ${fmtV(r.low, m.unit)}~${fmtV(r.high, m.unit)}</small>` : ""}</span></div>
    <div class="sum">${esc(r.reason || "")}</div><details><summary>原理与支撑 · ${esc((r.created_at || "").slice(0, 16))} · ${esc(r.model)}</summary>${analysisHTML(r, m.unit)}</details></div>`; }).join("") : `<div class="skel">暂无当期研判，点击上方按钮运行。</div>`;
  bindRunLinks($("#pResults"));
}

/* ---------------- 数据库 ---------------- */
function curFreq() { return ($("#tblFreqTabs .on") || {}).dataset ? $("#tblFreqTabs .on").dataset.f : "M"; }
async function renderTable() {
  const n = $("#tblMonths").value, freq = curFreq(), l1 = $("#tblL1").value;
  let t; try { t = await api(`/api/table?country=${S.country}&months=${n}&freq=${freq}${l1 ? "&l1=" + encodeURIComponent(l1) : ""}`); } catch (e) { $("#dataTable").innerHTML = `<tr><td>${esc(e.message)}</td></tr>`; return; }
  const st = S.status || {}; $("#tblMeta").textContent = `· ${COUNTRY_NAME[S.country]} · ${FREQ_NAME[freq]} · ${t.columns.length} 项 · 数据版本 ${st.loaded_at || ""}`;
  $("#tblSrc").textContent = `来源：${((st.data || {}).source || {})[S.country.toLowerCase()] || ""}`; $("#csvAll").href = `/api/data.csv?country=${S.country}`;
  const months = t.months;
  let h = `<tr><th>指标（单位）</th>${months.map(m => `<th>${freq === "Q" ? m.slice(2, 4) + "Q" + Math.ceil(+m.slice(5, 7) / 3) : freq === "A" ? m.slice(0, 4) : m.slice(2).replace("-", "/")}</th>`).join("")}</tr>`;
  let l1cur = "", l2cur = "";
  t.columns.forEach(c => {
    if (c.l1 !== l1cur) { l1cur = c.l1; l2cur = ""; h += `<tr class="grp-row"><td colspan="${months.length + 1}"><span class="gl">${esc(c.l1)}</span></td></tr>`; }
    if (c.l2 !== l2cur) { l2cur = c.l2; h += `<tr class="grp-row l2"><td colspan="${months.length + 1}"><span class="gl">　${esc(c.l2)}</span></td></tr>`; }
    h += `<tr class="${c.role}" data-detail="${c.id}" style="cursor:pointer"><td title="${esc(c.name)}${c.derived ? " · " + esc(c.derive_note) : ""}">${esc(c.short)}${c.derived ? "*" : ""} <span class="lo">${esc(c.unit)}</span></td>` +
      c.values.map((v, i) => `<td class="${months[i] === c.latest_month ? "latest" : ""}">${v == null ? "" : fmtV(v, c.unit)}</td>`).join("") + "</tr>";
  });
  $("#dataTable").innerHTML = h || `<tr><td class="skel">暂无数据</td></tr>`;
  const wrap = $("#dataTable").parentElement; wrap.scrollLeft = wrap.scrollWidth;
  $$("#dataTable tr[data-detail]").forEach(tr => tr.onclick = () => showDetail(tr.dataset.detail));
}
async function renderSeries() {
  const id = $("#serInd").value; if (!id) return; const m = ind(id), from = $("#serFrom").value || "2010-01";
  const ser = await getSeries(id); const months = ser.months.filter(x => x >= from);
  const act = Object.fromEntries(ser.months.map((x, i) => [x, ser.values[i]]));
  lineChart($("#serChart"), { months, series: [{ name: m.short, color: "#14202e", data: act, width: 2 }], unit: m.unit, freq: m.freq, clip: false });
  const d = ser.diag || {};
  $("#serDiag").innerHTML = `<span>最新 <b>${monthLabel(ser.months[ser.months.length - 1], m.freq)} ${fmtV(ser.values[ser.values.length - 1], m.unit)} ${esc(m.unit)}</b></span><span>样本 <b>${ser.months.length}</b> 期（${ser.months[0]} 起）</span>
    ${d.adf_p != null ? `<span>ADF p = <b>${d.adf_p.toFixed(3)}</b>${d.adf_p < 0.05 ? "（平稳）" : "（非平稳）"}</span><span>SARIMAX <b>${esc(d.final_order || "")}</b></span>` : ""}<span>${esc(m.release)}</span>`;
  $("#serNotes").textContent = (ser.notes || []).join("；");
  try {
    const vw = (await api(`/api/views/${id}`)).views;
    const draw = () => { $("#serViews").innerHTML = viewsHTML(vw, m.unit, "ser" + id); bindFreqTabs($("#serViews"), draw); };
    draw();
  } catch (e) { $("#serViews").innerHTML = ""; }
}

/* ---------------- 搜索 ---------------- */
async function runSearch(q) {
  q = q != null ? q : $("#sqInput").value;
  $("#sqInput").value = q;
  if (!q.trim()) { $("#sqOut").innerHTML = `<div class="skel">输入关键词开始搜索</div>`; return; }
  $("#sqOut").innerHTML = `<div class="skel">搜索中…</div>`;
  let d; try { d = await api("/api/search?q=" + encodeURIComponent(q)); } catch (e) { $("#sqOut").innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; return; }
  if (!d.total) { $("#sqOut").innerHTML = `<div class="skel">没有匹配「${esc(q)}」的内容</div>`; return; }
  $("#sqOut").innerHTML = `<p class="hint">共 ${d.total} 条结果</p>` + d.groups.map(g => `<div class="sr-group"><div class="l1-h">${esc(g.name)}<small>${g.items.length}</small><span class="line"></span></div>` +
    g.items.map(it => {
      if (g.name === "指标") return `<div class="sr-item" data-detail="${it.id}"><span class="v">${fmtV(it.last_value, it.unit)}<small class="muted"> ${esc(it.unit)}</small></span>
        <div class="t">${esc(it.name)} <span class="tag ${it.role}">${COUNTRY_NAME[it.country]} · ${esc(it.l1)}/${esc(it.l2)} · ${FREQ_NAME[it.freq]}</span></div>
        <div class="m">最新 ${esc(it.last_month || "")}${it.pending ? ` · 待预测 ${esc(it.pending)}${it.pred != null ? ` → <b>${fmtV(it.pred, it.unit)}</b>` : ""}` : ""} · ${esc(it.release)}</div>
        <div class="m">${esc(it.theory || "")}</div></div>`;
      if (g.name === "市场") return `<div class="sr-item"><span class="v">${fmtV(it.last, "")}</span><div class="t">${esc(it.name)}</div><div class="m">${esc(it.market)} · ${it.type === "equity" ? "价格指数" : "收益率"} · 最新 ${esc(it.last_month || "")}</div></div>`;
      if (g.name === "方法论") return `<div class="meth-card"><div class="org">${esc(it.org)} · ${esc(it.scope)}</div><h4>${esc(it.name)}</h4><p>${esc(it.core)}</p><div class="formula">${esc(it.formula)}</div><p class="hint"><b>精度：</b>${esc(it.accuracy || "—")}<br><b>本平台应用：</b>${esc(it.use)}<br><b>来源：</b>${esc(it.ref)}</p></div>`;
      if (g.name === "计算方法") return `<div class="meth-card"><h4>${esc(it.name)}</h4><div class="formula">${esc(it.formula)}</div><p class="hint">${esc(it.how)}${it.diag ? "<br>" + esc(it.diag) : ""}</p></div>`;
      return `<div class="sr-item"><div class="t">${esc(it.category)}</div><div class="m">${(it.factors || []).map(esc).join(" · ")}</div></div>`;
    }).join("") + `</div>`).join("");
  $$("#sqOut [data-detail]").forEach(b => b.onclick = () => showDetail(b.dataset.detail));
}

/* ---------------- 报告生成 / 导出 ---------------- */
function bindExport(root) {
  $$("[data-export]", root || document).forEach(b => {
    if (b._bound) return; b._bound = true;
    b.onclick = async () => {
      const [kind, scope, id] = b.dataset.export.split("|");
      const body = { kind, scope, country: S.country };
      if (scope === "indicator") body.indicator = id || ($("#rgInd") || {}).value || ($("#serInd") || {}).value || ($("#pcInd") || {}).value;
      if (scope === "ai") { if (!S.aiText) { alertBox(new Error("请先生成 AI 报告")); return; } body.text = S.aiText; body.title = $("#aiKind").value; }
      const old = b.textContent; b.disabled = true; b.textContent = "生成中…";
      try {
        const r = await fetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json", "X-Access-Password": pwd() }, body: JSON.stringify(body) });
        if (!r.ok) { let j = {}; try { j = await r.json(); } catch (e) { } throw new Error(j.error || `HTTP ${r.status}`); }
        const blob = await r.blob();
        const cd = r.headers.get("Content-Disposition") || "";
        const fn = (cd.match(/filename=([^;]+)/) || [, `report.${kind}`])[1].trim();
        const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = fn; document.body.appendChild(a); a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
      } catch (e) { alertBox(e); }
      b.disabled = false; b.textContent = old;
    };
  });
}
async function aiGenerate() {
  const btn = $("#aiGo"); btn.disabled = true;
  $("#aiOut").innerHTML = `<div class="skel">AI 正在读取平台数据库并写作…（约 30–90 秒）</div>`;
  try {
    const r = await api("/api/ai/report", { method: "POST", json: { indicator: $("#aiScope").value || null, country: S.country, prompt: $("#aiPrompt").value, model: $("#aiModel").value, kind: $("#aiKind").value } });
    S.aiText = r.text || "";
    $("#aiOut").innerHTML = `<div class="msg ai" style="max-width:100%">${mdLite(S.aiText)}</div>`;
    $("#aiMeta").textContent = `${r.model || ""} · 注入上下文 ${r.context_chars || 0} 字 · ${(r.tokens || "")} tokens`;
  } catch (e) { $("#aiOut").innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; }
  btn.disabled = false;
}

/* ---------------- 研报 ---------------- */
async function renderReports() {
  const id = $("#repInd").value, month = $("#repMonth").value, mode = $("#repMode").value; if (!month || !id) return;
  $("#repOut").innerHTML = `<div class="skel">正在召回 ${monthLabel(month)} 研报…</div>`;
  try {
    const d = await api(`/api/reports?indicator=${id}&month=${month}&mode=${mode}`); const info = d.info;
    let html = `<p class="muted">当月宏观 + 策略研报共 <b>${info.n_all}</b> 篇；按「${esc((ind(id).keywords || []).join("、"))}${(d.rules.include || []).length ? "、" + esc(d.rules.include.join("、")) : ""}」召回并去重后 <b>${info.n_titles}</b> 条${info.supplemented ? `（命中不足，补充 ${info.supplemented} 条）` : ""}。</p>`;
    if (mode === "chunk") html += `<h3>正文片段（${info.chunks.length} 段）</h3>` + (info.chunks.length ? info.chunks.map(c => `<div class="chunk">${esc(c)}</div>`).join("") : `<p class="muted">未取得正文片段</p>`);
    html += `<ol>` + d.titles.map(t => `<li><a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.title)}</a> <span class="org">${esc(t.org)} · ${t.date}${t.researcher ? " · " + esc(t.researcher) : ""}</span></li>`).join("") + "</ol>";
    $("#repOut").innerHTML = html;
  } catch (e) { $("#repOut").innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; }
}
function fillRules() { const r = (S.settings || {}).recall_rules || {}; $("#rInclude").value = (r.include || []).join(", "); $("#rExclude").value = (r.exclude || []).join(", "); $("#rOrgs").value = (r.orgs || []).join(", "); $("#rLimit").value = r.limit || 150; }
async function saveRules() {
  const split = s => s.split(/[,，、\n]/).map(x => x.trim()).filter(Boolean);
  try { S.settings = await api("/api/settings", { method: "POST", json: { recall_rules: { include: split($("#rInclude").value), exclude: split($("#rExclude").value), orgs: split($("#rOrgs").value), limit: +$("#rLimit").value || 150 } } }); $("#rMsg").textContent = "✓ 已保存，召回与预测将按此规则执行"; }
  catch (e) { $("#rMsg").textContent = "✗ " + e.message; }
}

/* ---------------- 回测 ---------------- */
async function renderBacktest() {
  const q = new URLSearchParams({ start: $("#btFrom").value || "", end: $("#btTo").value || "", model: $("#btModel").value, country: S.country });
  $("#btTable").innerHTML = `<tr><td class="skel">计算中…</td></tr>`;
  let rows; try { rows = (await api("/api/backtest?" + q)).rows; } catch (e) { $("#btTable").innerHTML = `<tr><td>${esc(e.message)}</td></tr>`; return; }
  const metric = $("#btMetric").value, better = metric === "rmse" ? -1 : 1;
  const g = o => o ? (metric === "rmse" ? (o.rmse_used != null ? o.rmse_used : o.rmse) : metric === "hit" ? o.hit : (o.corr_used != null ? o.corr_used : o.corr)) : null;
  const f = v => v == null ? "—" : metric === "hit" ? (v * 100).toFixed(0) + "%" : v.toFixed(2);
  let h = `<tr><th>指标</th><th>分类</th><th>频率</th><th>沿用上期</th><th>SARIMAX</th><th>多因子</th><th>桥方程</th>${MODES_ORDER.map(m => `<th>${MODE_SHORT[m]}</th>`).join("")}<th>阶数</th><th>推荐</th></tr>`;
  let l1 = "";
  rows.forEach(r => {
    if (r.l1 !== l1) { l1 = r.l1; h += `<tr class="grp-row"><td colspan="${11 + MODES_ORDER.length}"><span class="gl">${esc(l1)}</span></td></tr>`; }
    const vals = [g(r.persist), g(r.ar), g(r.mf), g(r.bridge), ...MODES_ORDER.map(m => g(r.llm[m]))].filter(v => v != null);
    const best = vals.length ? (better > 0 ? Math.max(...vals) : Math.min(...vals)) : null;
    const cell = (o, title) => { const v = g(o); return `<td class="${v != null && v === best ? "hi" : v == null ? "lo" : ""}" title="${esc(title || "")}">${f(v)}${o && o.n ? `<span class="pp">n=${o.n}</span>` : ""}</td>`; };
    h += `<tr data-detail="${r.id}" style="cursor:pointer"><td>${esc(r.name)}${r.spring ? ' <span class="tag">春节</span>' : ""}</td><td class="muted">${esc(r.l2)}</td><td>${FREQ_NAME[r.freq]}</td>
      ${cell(r.persist)}${cell(r.ar)}${cell(r.mf, (r.mf_features || []).join("、"))}${cell(r.bridge)}${MODES_ORDER.map(m => cell(r.llm[m])).join("")}
      <td>${esc(r.order || "")}</td><td title="${esc(r.why)}"><span class="tag ${r.recommend}">${REC_NAME[r.recommend]}</span></td></tr>`;
  });
  $("#btTable").innerHTML = h;
  $$("#btTable tr[data-detail]").forEach(tr => tr.onclick = () => showDetail(tr.dataset.detail));
  renderBtChart();
}
async function renderBtChart() {
  const id = $("#btInd").value; if (!id) return; const m = ind(id); const ser = await getSeries(id, true);
  const from = $("#btFrom").value || "2014-01", to = $("#btTo").value || "9999"; const months = ser.months.filter(x => x >= from && x <= to);
  const act = Object.fromEntries(ser.months.map((x, i) => [x, ser.values[i]])); const colors = { title: "#a8322a", chunk: "#a8832f", title_ar: "#5a4a9c", data: "#2f7d4f" };
  const series = [{ name: "真实值", color: "#14202e", data: act, width: 2.2 }, { name: "沿用上期", color: "#9aa3ad", data: ser.persist, dash: "4 3" }, { name: "SARIMAX", color: "#1d6b73", data: ser.ar }];
  if (ser.mf && Object.keys(ser.mf).length) series.push({ name: "多因子回归", color: "#5a4a9c", data: ser.mf, dash: "6 3" });
  Object.keys(ser.llm || {}).forEach(k => series.push({ name: MODE_SHORT[k], color: colors[k], data: ser.llm[k], dots: true }));
  $("#btLegend").innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
  lineChart($("#btChart"), { months, series, unit: m.unit, freq: m.freq, clip: true, height: 340 });
}
async function runLlmBacktest() {
  const ids = $$("#llmInds .chip.on[data-id]").map(c => c.dataset.id); if (!ids.length) return;
  $("#llmGo").disabled = true;
  try { const job = await api("/api/backtest/llm", { method: "POST", json: { indicators: ids, modes: [$("#llmMode").value], start: $("#llmFrom").value, end: $("#llmTo").value || "9999-12", model: $("#llmModel").value } }); trackJob(job.id, $("#llmJob"), () => { $("#llmGo").disabled = false; renderBacktest(); }); }
  catch (e) { $("#llmGo").disabled = false; alertBox(e); }
}
async function runLeak() {
  const id = $("#leakInd").value; const d = await api(`/api/leak/${id}?split=${$("#leakSplit").value}&mode=title`);
  const row = (k, a, b) => `<tr><td>${k}</td><td>${a.n}</td><td>${fmtC(a.corr)}</td><td>${a.mae != null ? fmtV(a.mae, ind(id).unit) : "—"}</td><td>${fmtC(b.corr)}</td></tr>`;
  $("#leakOut").innerHTML = `<div class="tbl-wrap"><table><tr><th>区间</th><th>期数</th><th>AI 相关性</th><th>AI 平均绝对误差</th><th>沿用上期相关性</th></tr>${row(`${d.split} 之前`, d.before, d.persist_before)}${row(`${d.split} 及之后`, d.after, d.persist_after)}</table></div>`;
}

/* ---------------- 档案 ---------------- */
async function renderArchive() {
  const q = new URLSearchParams({ indicator: $("#arcInd").value, source: $("#arcSrc").value, limit: 500, ok: $("#arcOk").checked ? "1" : "0" });
  const rows = await api("/api/runs?" + q); $("#arcCsv").href = "/api/runs.csv?indicator=" + $("#arcInd").value; $("#arcMeta").textContent = `· ${rows.length} 条`;
  $("#arcTable").innerHTML = `<tr><th>#</th><th>时间</th><th>类型</th><th>指标</th><th>目标期</th><th>预测</th><th>区间</th><th>置信</th><th>模型</th><th>结论</th></tr>` +
    (rows.length ? rows.map(r => { const m = ind(r.indicator) || {}; return `<tr><td>${r.id}</td><td>${esc((r.created_at || "").slice(0, 16))}</td><td>${r.source === "live" ? "实时" : "回测"}</td><td>${esc(m.short || r.indicator)}</td><td>${r.target_month}</td><td><b>${fmtV(r.value, m.unit)}</b></td><td>${r.low != null ? fmtV(r.low, m.unit) + "~" + fmtV(r.high, m.unit) : ""}</td><td>${esc(r.confidence || "")}</td><td>${esc(r.model)}</td><td>${esc((r.reason || r.error || "").slice(0, 110))} <a href="#" data-run-id="${r.id}">详情</a></td></tr>`; }).join("") : `<tr><td colspan="10" class="skel">暂无记录</td></tr>`);
  bindRunLinks($("#arcTable"));
}

/* ---------------- 问 AI ---------------- */
function addMsg(role, text, meta) { const d = document.createElement("div"); d.className = "msg " + role; d.innerHTML = role.startsWith("ai") ? mdLite(text) + (meta ? `<span class="meta">${esc(meta)}</span>` : "") : esc(text); $("#chatBox").appendChild(d); $("#chatBox").scrollTop = 1e9; return d; }
async function askSend() {
  const q = $("#askInput").value.trim(); if (!q) return;
  $("#askInput").value = ""; addMsg("user", q); S.chat.push({ role: "user", content: q });
  const wait = addMsg("ai think", "思考中…（约 10–60 秒）"); $("#askSend").disabled = true;
  try { const r = await api("/api/ask", { method: "POST", json: { messages: S.chat, model: $("#askModel").value } }); wait.remove(); addMsg("ai", r.content, `${r.model} · ${r.latency ? r.latency.toFixed(1) + " 秒" : ""}`); S.chat.push({ role: "assistant", content: r.content }); }
  catch (e) { wait.remove(); addMsg("ai", "出错：" + e.message); S.chat.pop(); }
  $("#askSend").disabled = false; $("#askInput").focus();
}

/* ---------------- 设置 ---------------- */
const REQ_HINTS = ["每条依据必须带数字", "拆分食品/能源/核心三项", "给出对 10Y 国债的操作含义", "给出对沪深300与创业板的相对强弱", "优先引用中金、中信、华泰",
  "说明翘尾与新涨价的拆分", "指出与市场一致预期的差异", "结论控制在 300 字以内", "补充未来两周的跟踪清单", "风险情景要量化到具体数值"];
async function loadSettings() { try { S.settings = await api("/api/settings"); } catch (e) { S.settings = {}; } }
function renderSettings() {
  const s = S.settings || {}, st = S.status || {}, d = st.data || {}, src = d.source || {};
  $("#sReq").value = s.predict_requirements || ""; fillSelect($("#sModel"), modelOpts(), s.default_model || st.model); $("#sAuto").checked = !!s.auto_predict; $("#pwd").value = pwd();
  $("#reqHints").innerHTML = `<span class="chip grp">点一下加入：</span>` + REQ_HINTS.map(h => `<span class="chip" data-req="${esc(h)}">${esc(h)}</span>`).join("");
  $$("#reqHints [data-req]").forEach(c => c.onclick = () => { const t = $("#sReq"); t.value = (t.value ? t.value.replace(/\s*$/, "") + "\n" : "") + "- " + c.dataset.req; });
  $("#srcInfo").innerHTML = `
    <div class="src-card"><h3>大模型</h3>${(st.models || []).map(m => `<div>● ${esc(m.label)}</div>`).join("") || "<div class='up'>未配置任何模型密钥</div>"}<div class="hint">DeepSeek：DEEPSEEK_API_KEY；Claude：ANTHROPIC_API_KEY</div></div>
    <div class="src-card"><h3>中国数据</h3><div>${esc(src.cn || "—")}</div><div class="hint">国家统计局 / 海关总署 / 央行口径，经东方财富数据中心；每 ${st.refresh_hours} 小时轮询</div></div>
    <div class="src-card"><h3>美国数据</h3><div>${esc(src.us || "—")}</div><div class="hint">东方财富·全球宏观（BLS / BEA / Census / ISM / 美联储官方口径转载）为主源，FRED 为备源</div></div>
    <div class="src-card"><h3>市场库</h3><div>股指 / 汇率 / 商品月收盘 + 中美国债收益率月均，2005 年起</div><div class="hint">用于宏观→资产传导的事件回归</div></div>
    <div class="src-card"><h3>研报</h3><div>东方财富研报中心（宏观研究 + 策略报告），按指标关键词 + 自定义规则召回</div></div>
    ${(d.errors || []).length ? `<div class="src-card"><h3>最近抓取异常</h3>${d.errors.slice(0, 6).map(e => `<div class="up">${esc(e)}</div>`).join("")}</div>` : ""}`;
}
async function saveSettings() {
  try { S.settings = await api("/api/settings", { method: "POST", json: { predict_requirements: $("#sReq").value, default_model: $("#sModel").value, auto_predict: $("#sAuto").checked } }); $("#sMsg").textContent = "✓ 已保存，将作用于预测、问答与报告生成"; }
  catch (e) { $("#sMsg").textContent = "✗ " + e.message; }
}
async function savePwd() { try { localStorage.setItem("nowcast_pwd", $("#pwd").value); } catch (e) { } try { await api("/api/auth/check", { method: "POST", json: {} }); $("#pwdMsg").textContent = "✓ 口令有效"; } catch (e) { $("#pwdMsg").textContent = "✗ " + e.message; } }
async function doRefresh() { try { await api("/api/refresh", { method: "POST", json: {} }); $("#tblSrc").textContent = "已开始重新抓取…"; S.seriesCache = {}; setTimeout(() => { refreshStatus(); if (S.view === "data") { renderTable(); renderSeries(); } }, 20000); } catch (e) { alertBox(e); } }
async function doOverride(clear) {
  const id = $("#ovInd").value;
  try { let body = ""; if (!clear) { const f = $("#ovFile").files[0]; if (!f) { $("#ovMsg").textContent = "请选择 CSV 文件"; return; } body = await f.text(); }
    const r = await fetch(`/api/override/${id}${clear ? "?clear=1" : ""}`, { method: "POST", body, headers: { "X-Access-Password": pwd(), "Content-Type": "text/plain" } }); const j = await r.json(); if (!r.ok) throw new Error(j.error);
    $("#ovMsg").textContent = clear ? "已清除，模型重算中" : `已导入 ${j.rows} 行，模型重算中`; S.seriesCache = {}; } catch (e) { $("#ovMsg").textContent = e.message; }
}

/* ---------------- 路由 ---------------- */
function setCountry(c) { S.country = c; $$("#countrySeg button").forEach(b => b.classList.toggle("on", b.dataset.c === c)); try { localStorage.setItem("nowcast_country", c); } catch (e) { } fillCountrySelects(); show(S.view); }
function fillCountrySelects() {
  const all = countryInds(), modeled = countryInds(["nowcast", "persist"]);
  fillSelect($("#serInd"), all.map(i => [i.id, `${i.l1}/${i.l2} · ${i.short}`]));
  fillSelect($("#repInd"), modeled.map(i => [i.id, i.short])); fillSelect($("#btInd"), modeled.map(i => [i.id, i.short])); fillSelect($("#leakInd"), modeled.map(i => [i.id, i.short]));
  fillSelect($("#ovInd"), all.map(i => [i.id, i.short]));
  const l1s = [...new Set(all.map(i => i.l1))];
  $("#tblL1").innerHTML = `<option value="">全部分类</option>` + l1s.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
  $("#arcInd").innerHTML = `<option value="">全部</option>` + (S.meta.indicators || []).map(i => `<option value="${i.id}">${esc(COUNTRY_NAME[i.country])} · ${esc(i.short)}</option>`).join("");
  $("#llmInds").innerHTML = modeled.map(i => `<span class="chip ${i.role === "nowcast" ? "on" : ""}" data-id="${i.id}">${esc(i.short)}</span>`).join("");
  $$("#llmInds .chip").forEach(c => c.onclick = () => c.classList.toggle("on"));
  renderPredictControls();
}
function show(v) {
  if (!VIEW_TITLE[v]) v = "overview"; S.view = v;
  $$(".view").forEach(s => s.hidden = s.id !== "v-" + v); $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.v === v)); $("#viewTitle").textContent = VIEW_TITLE[v];
  $("#countrySeg").style.visibility = ["ask", "settings", "archive", "live", "guide", "search"].includes(v) ? "hidden" : "visible";
  if (v !== "live") stopLive();
  if (!S.meta) return;
  if (v === "overview") loadOverview();
  if (v === "live") startLive();
  if (v === "predict") { renderPredictControls(); renderPredictResults(); }
  if (v === "data") { renderTable(); renderSeries(); }
  if (v === "search") { $$("#sqQuick .chip").forEach(c => c.onclick = () => runSearch(c.textContent)); setTimeout(() => $("#sqInput").focus(), 50); }
  if (v === "report") { fillSelect($("#aiModel"), modelOpts(), (S.settings || {}).default_model || S.status.model); bindExport(document); }
  if (v === "reports") { fillRules(); renderReports(); }
  if (v === "backtest") renderBacktest();
  if (v === "archive") renderArchive();
  if (v === "ask") { fillSelect($("#askModel"), modelOpts(), (S.settings || {}).default_model || S.status.model); setTimeout(() => $("#askInput").focus(), 50); }
  if (v === "guide") renderGuide();
  if (v === "settings") renderSettings();
}
async function init() {
  try { S.meta = await api("/api/meta"); } catch (e) { $("#ovGroups").innerHTML = `<div class="banner warn">无法连接服务：${esc(e.message)}</div>`; setTimeout(init, 3000); return; }
  await refreshStatus(); await loadSettings();
  try { S.country = localStorage.getItem("nowcast_country") || "CN"; } catch (e) { }
  $$("#countrySeg button").forEach(b => { b.onclick = () => setCountry(b.dataset.c); b.classList.toggle("on", b.dataset.c === S.country); });
  fillSelect($("#llmModel"), modelOpts(), S.status.model); fillSelect($("#llmMode"), MODES_ORDER.map(k => [k, S.meta.modes[k]]), "title");
  $("#btModel").innerHTML = `<option value="">全部</option>` + modelOpts().map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
  const now = new Date(), ym = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`, prev = new Date(now.getFullYear(), now.getMonth() - 1, 1), pym = `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, "0")}`;
  $("#repMonth").value = ym; $("#repMonth").max = ym; $("#llmTo").value = pym; $("#btFrom").value = S.meta.backtest_start; $("#leakSplit").value = S.meta.leak_split; $("#llmFrom").min = S.meta.llm_earliest;
  $("#sqQuick").innerHTML = ["CPI", "出口", "信贷", "GDP", "非农", "房价", "GDPNow", "岭回归", "翘尾", "桥方程", "预期差", "组合预测"].map(x => `<span class="chip">${x}</span>`).join("");
  fillCountrySelects();
  $("#syncBtn").onclick = syncAll;
  $("#topSearch").addEventListener("keydown", ev => { if (ev.key === "Enter") { location.hash = "#search"; runSearch($("#topSearch").value); } });
  $("#pUpdate").onclick = updateAndPredict; $("#pRun").onclick = runSelected; $("#pcGo").onclick = pcShow; $("#pcInd").onchange = pcShow;
  $$("#tblFreqTabs button").forEach(b => b.onclick = () => { $$("#tblFreqTabs button").forEach(x => x.classList.remove("on")); b.classList.add("on"); renderTable(); });
  $("#tblMonths").onchange = renderTable; $("#tblL1").onchange = renderTable; $("#refreshData").onclick = doRefresh; $("#serInd").onchange = renderSeries; $("#serFrom").onchange = renderSeries;
  $("#sqGo").onclick = () => runSearch(); $("#sqInput").addEventListener("keydown", ev => { if (ev.key === "Enter") runSearch(); });
  $("#aiGo").onclick = aiGenerate;
  $("#repGo").onclick = renderReports; $("#rSave").onclick = saveRules;
  $("#btGo").onclick = renderBacktest; $("#btMetric").onchange = renderBacktest; $("#btInd").onchange = renderBtChart; $("#llmGo").onclick = runLlmBacktest; $("#leakGo").onclick = runLeak;
  $("#arcGo").onclick = renderArchive; $("#arcInd").onchange = renderArchive; $("#arcSrc").onchange = renderArchive; $("#arcOk").onchange = renderArchive;
  $("#askSend").onclick = askSend; $("#askClear").onclick = () => { S.chat = []; $("#chatBox").innerHTML = ""; }; $("#askInput").addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); askSend(); } });
  $("#sSave").onclick = saveSettings; $("#pwdSave").onclick = savePwd; $("#ovUp").onclick = () => doOverride(false); $("#ovClear").onclick = () => doOverride(true);
  bindExport(document);
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (S.view === "data") renderSeries(); if (S.view === "backtest") renderBtChart(); }, 200); });
  setInterval(refreshStatus, 30000);
  show(location.hash.slice(1) || "overview");
}
addEventListener("hashchange", () => show(location.hash.slice(1)));
init();

/* ---------------- 实时看板 ---------------- */
const LV = { timers: [], last: {}, trends: {}, feedSeen: new Set(), hist: {} };
function stopLive() { LV.timers.forEach(clearInterval); LV.timers = []; }
function startLive() {
  stopLive(); tickClock(); pollQuotes(); loadBoard(); loadPulse(); loadCalendar(); loadFeed(); loadTrends();
  LV.timers.push(setInterval(tickClock, 1000), setInterval(pollQuotes, 5000), setInterval(loadTrends, 60000), setInterval(loadFeed, 120000), setInterval(() => { loadBoard(); loadPulse(); loadCalendar(); }, 300000));
}
function tickClock() {
  const d = new Date(), bj = new Date(d.getTime() + (d.getTimezoneOffset() + 480) * 60000);
  $("#lvClock").textContent = bj.toTimeString().slice(0, 8);
  const ny = new Date(d.getTime() + (d.getTimezoneOffset() - 240) * 60000);
  $("#lvClockSub").textContent = `北京 ${bj.toISOString().slice(5, 10).replace("-", "/")} · 纽约 ${ny.toTimeString().slice(0, 5)} · 行情每 5 秒刷新`;
}
function lvSpark(pts, pre) {
  if (!pts || pts.length < 2) return "";
  const W = 120, H = 34, vs = pts.map(p => p[1]); let lo = Math.min(...vs), hi = Math.max(...vs); if (pre != null) { lo = Math.min(lo, pre); hi = Math.max(hi, pre); } if (hi === lo) { hi += 1; lo -= 1; }
  const x = i => (i / (pts.length - 1)) * W, y = v => H - 3 - (v - lo) / (hi - lo) * (H - 6);
  const d = pts.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p[1]).toFixed(1)).join("");
  const up = vs[vs.length - 1] >= (pre != null ? pre : vs[0]);
  return `<svg viewBox="0 0 ${W} ${H}" class="lv-spark">${pre != null ? `<line x1="0" x2="${W}" y1="${y(pre)}" y2="${y(pre)}" stroke="#4a5568" stroke-dasharray="2 2"/>` : ""}<path d="${d}" fill="none" stroke="${up ? "#ff5a5a" : "#3ddc97"}" stroke-width="1.5"/></svg>`;
}
async function pollQuotes() {
  let q; try { q = await api("/api/live/quotes"); } catch (e) { return; }
  $("#lvQuoteMeta").textContent = `· ${q.n} 项 · ${q.provider || ""} · ${q.fetched_at ? q.fetched_at.slice(11) : ""}${q.error ? " · 行情源异常，显示上次值" : ""}`;
  if (!q.items.length) { $("#lvQuotes").innerHTML = `<div class="hint">${esc(q.error || "暂无行情")}</div>`; return; }
  const groups = {}; q.items.forEach(it => (groups[it.group] = groups[it.group] || []).push(it));
  const tile = it => {
    const prev = LV.last[it.secid]; const flash = prev != null && prev !== it.price ? (it.price > prev ? "flash-up" : "flash-down") : ""; LV.last[it.secid] = it.price;
    const hh = (LV.hist[it.secid] = LV.hist[it.secid] || []); if (!hh.length || hh[hh.length - 1][1] !== it.price) hh.push([new Date().toTimeString().slice(0, 5), it.price]); if (hh.length > 240) hh.shift();
    const t = LV.trends[it.secid] && LV.trends[it.secid].points && LV.trends[it.secid].points.length ? LV.trends[it.secid] : (hh.length > 2 ? { points: hh, pre_close: it.price - it.chg } : null);
    const dec = Math.abs(it.price) < 10 ? 4 : 2;
    return `<div class="lv-q ${it.pct > 0 ? "up" : it.pct < 0 ? "down" : ""} ${flash}" data-sid="${it.secid}"><div class="lv-q-n">${esc(it.name)}<small>${esc(it.em_name || "")}</small></div><div class="lv-q-p">${it.price.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec })}</div><div class="lv-q-c">${it.pct > 0 ? "▲" : it.pct < 0 ? "▼" : ""} ${it.chg > 0 ? "+" : ""}${(+it.chg).toFixed(dec)} · ${it.pct > 0 ? "+" : ""}${(+it.pct).toFixed(2)}%</div>${t ? lvSpark(t.points, t.pre_close) : ""}</div>`;
  };
  $("#lvQuotes").innerHTML = Object.entries(groups).map(([g, items]) => `<div class="lv-g">${esc(g)}</div><div class="lv-qgrid">${items.map(tile).join("")}</div>`).join("");
  $("#lvStrip").innerHTML = `<div class="lv-marquee">${(q.items.concat(q.items)).map(it => `<span class="${it.pct > 0 ? "up" : it.pct < 0 ? "down" : ""}">${esc(it.name)} <b>${it.price}</b> ${it.pct > 0 ? "+" : ""}${(+it.pct).toFixed(2)}%</span>`).join("")}</div>`;
}
async function loadTrends() {
  let q; try { q = await api("/api/live/quotes"); } catch (e) { return; }
  await Promise.all(q.items.map(async it => { try { LV.trends[it.secid] = await api(`/api/live/trend?secid=${encodeURIComponent(it.secid)}`); } catch (e) { } }));
  $$("#lvQuotes .lv-q").forEach(el => { const t = LV.trends[el.dataset.sid]; if (!t) return; const old = el.querySelector("svg"); const html = lvSpark(t.points, t.pre_close); if (old) old.outerHTML = html; else el.insertAdjacentHTML("beforeend", html); });
}
async function loadPulse() {
  const [cn, us] = await Promise.all([getRows("CN"), getRows("US")]);
  const rows = cn.concat(us).filter(r => r.role === "nowcast" && !r.missing && r.basis);
  $("#lvPulse").innerHTML = rows.map(r => { const c = r.basis.conclusion || {}, v = c.value, d = v != null && r.last_value != null ? v - r.last_value : null;
    return `<div class="lv-p"><div class="lv-p-n"><span class="flag">${r.country}</span>${esc(r.short)}<small>${monthLabel(r.pending_month, r.freq)}${r.release_est ? " · " + esc(r.release_est.slice(5)) : ""}</small></div>
      <div class="lv-p-v"><span class="muted">${fmtV(r.last_value, r.unit)}</span><span class="arrow ${d > 0 ? "up" : d < 0 ? "down" : ""}">${d > 0 ? "↗" : d < 0 ? "↘" : "→"}</span><b>${fmtV(v, r.unit)}</b><small>${esc(r.unit)}</small></div>
      <div class="lv-p-m ${c.used}">${REC_NAME[c.used] || ""}${r.ai ? ` · AI 置信 ${esc(r.ai.confidence || "")}` : ""}</div></div>`; }).join("") || `<div class="skel">暂无</div>`;
}
async function loadCalendar() {
  let c; try { c = await api("/api/calendar?days=45"); } catch (e) { return; }
  $("#lvCal").innerHTML = c.items.length ? c.items.map(it => `<div class="lv-c ${it.days < 0 ? "past" : it.days <= 3 ? "soon" : ""}"><div class="lv-c-d"><b>${it.date.slice(5).replace("-", "/")}</b><small>${it.days < 0 ? "已过期" : it.days === 0 ? "今天" : "D-" + it.days}</small></div><div class="lv-c-n"><span class="flag">${it.country}</span>${esc(it.name)}<small>${esc(it.target_label)} · ${esc(it.release)}</small></div><div class="lv-c-v">${it.pred != null ? `<b>${fmtV(it.pred, it.unit)}</b><small>${REC_NAME[it.method] || ""}预测</small>` : `<span class="muted">${fmtV(it.last_value, it.unit)}</span><small>上期</small>`}</div></div>`).join("") : `<div class="skel">未来 45 天无可估算的发布</div>`;
}
async function loadFeed() {
  let f; try { f = await api("/api/live/reports?limit=40"); } catch (e) { return; }
  if (f.error) { $("#lvFeed").innerHTML = `<div class="hint">${esc(f.error)}</div>`; return; }
  const first = LV.feedSeen.size === 0;
  $("#lvFeed").innerHTML = f.items.map(it => { const k = it.url || it.title, fresh = !first && !LV.feedSeen.has(k); LV.feedSeen.add(k);
    return `<a class="lv-f ${fresh ? "fresh" : ""}" href="${esc(it.url || "#")}" target="_blank" rel="noopener"><div class="lv-f-m">${esc(it.date || "")} · ${esc(it.org || "")}${it.researcher ? " · " + esc(it.researcher) : ""}</div><div class="lv-f-t">${esc(it.title)}</div></a>`; }).join("") || `<div class="skel">暂无</div>`;
  $("#lvRepMeta").textContent = `· 本月 ${f.n_month || 0} 篇 · ${new Date().toTimeString().slice(0, 5)} 刷新`;
}
function lvMini(vals) {
  const v = (vals || []).filter(x => x != null && isFinite(x)); if (v.length < 2) return "";
  const W = 70, H = 20, lo = Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1;
  const d = v.map((x, i) => (i ? "L" : "M") + (i / (v.length - 1) * W).toFixed(1) + " " + (H - 2 - (x - lo) / sp * (H - 4)).toFixed(1)).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="lv-mini"><path d="${d}" fill="none" stroke="${v[v.length - 1] >= v[0] ? "#ff7b7b" : "#4fe3a6"}" stroke-width="1.3"/></svg>`;
}
const SG = v => v > 0 ? `<i class="sg up">▲</i>` : v < 0 ? `<i class="sg down">▼</i>` : `<i class="sg">○</i>`;
async function loadBoard() {
  let b; try { b = await api("/api/board"); } catch (e) { $("#lvBoard").innerHTML = `<div class="hint">${esc(e.message)}</div>`; return; }
  const NC = 9;
  const col = (c, blocks) => `<div class="lv-bcol"><div class="lv-bc-h">${COUNTRY_NAME[c]}<small>${blocks.reduce((n, x) => n + x.groups.reduce((k, g) => k + g.items.length, 0), 0)} 项 · ${esc(((b.status || {}).data || {}).source ? (b.status.data.source[c.toLowerCase()] || "") : "")}</small></div>
    <table class="lv-bt"><tr><th>指标</th><th>最新期</th><th>最新值</th><th>较上期</th><th>走势</th><th>待发布<small>预计公布</small></th><th>预测</th><th>方法</th><th>传导<small>${c === "CN" ? "A股/中债" : "美股/美债"}</small></th></tr>
    ${blocks.map(blk => `<tr class="lv-bg"><td colspan="${NC}">${esc(blk.l1)}</td></tr>` + blk.groups.map(g => `<tr class="lv-bg2"><td colspan="${NC}">${esc(g.l2)}</td></tr>` + g.items.map(it => {
      const d = it.prev_value != null && it.last_value != null ? it.last_value - it.prev_value : null;
      const eq = c === "CN" ? it.sign.hs300 : it.sign.spx, bd = c === "CN" ? it.sign.cn10y : it.sign.us10y;
      return `<tr data-detail="${it.id}" class="${it.role === "ref" ? "ref" : ""}"><td class="nm" title="${esc(it.name)}">${esc(it.short)}<small>${esc(it.unit)}</small></td><td class="mono">${(it.last_month || "").slice(2)}</td><td class="mono b">${fmtV(it.last_value, it.unit)}</td><td class="mono ${d > 0 ? "up" : d < 0 ? "down" : ""}">${d == null ? "—" : (d > 0 ? "+" : "") + fmtV(d, it.unit)}</td><td>${lvMini(it.spark)}</td><td class="mono">${it.role === "ref" ? "—" : monthLabel(it.pending_month, it.freq).replace("年", "/").replace("月", "")}<small class="sub">${it.role === "ref" ? "" : (it.release_est || "").slice(5).replace("-", "/")}</small></td><td class="mono b">${it.role === "ref" || it.pred == null ? "—" : fmtV(it.pred, it.unit)}</td><td><span class="lv-m ${it.method || ""}">${it.role === "ref" ? "" : (REC_NAME[it.method] || "")}${it.ai ? "·AI" : ""}</span></td><td class="sgs">${SG(eq)}${SG(bd)}</td></tr>`;
    }).join("")).join("")).join("")}</table></div>`;
  $("#lvBoard").innerHTML = col("CN", b.board.CN || []) + col("US", b.board.US || []);
  const mk = b.markets || {}; $("#lvBoardMeta").textContent = `· 中国 ${((b.status || {}).n_indicators || {}).CN || 0} 项 + 美国 ${((b.status || {}).n_indicators || {}).US || 0} 项 · 市场库：${esc((mk.source || {}).equity || "")} / ${esc((mk.source || {}).yield || "")} · 更新 ${esc(((b.status || {}).data || {}).fetched_at || "")}`;
  $$("#lvBoard tr[data-detail]").forEach(tr => tr.onclick = () => showDetail(tr.dataset.detail));
}

/* ---------------- 使用教程（数据驱动） ---------------- */
async function renderGuide() {
  if (!S.meth) { try { S.meth = await api("/api/methodology"); } catch (e) { S.meth = { institutions: [], formulas: [], factors: {}, framework: {} }; } }
  const M = S.meth;
  const scene = (t, h) => `<div class="scene"><b class="t">场景</b><div><b>${t}</b><br>${h}</div></div>`;
  const inst = M.institutions.map(x => `<div class="meth-card"><div class="org">${esc(x.org)} · ${esc(x.scope)}</div><h4>${esc(x.name)}</h4>
      <p><b>核心思想：</b>${esc(x.core)}</p><div class="formula">${esc(x.formula)}</div>
      <p><b>步骤：</b>${(x.steps || []).map((s, i) => `${i + 1}) ${esc(s)}`).join("；")}</p>
      <p><b>数据：</b>${esc(x.data || "—")}<br><b>公开精度：</b>${esc(x.accuracy || "—")}</p>
      <p class="hint"><b>本平台如何借鉴：</b>${esc(x.use)}<br><b>来源：</b>${esc(x.ref)}</p></div>`).join("");
  const forms = M.formulas.map(x => `<h4>${esc(x.name)}</h4><div class="formula">${esc(x.formula)}</div><p class="hint">${esc(x.how)}${x.diag ? "<br>" + esc(x.diag) : ""}</p>`).join("");
  const facs = Object.entries(M.factors || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.map(esc).join("；")}</td></tr>`).join("");
  const chan = ((M.framework || {}).channels || []).map(c => `<p><b>${esc(c[0])}</b>：${esc(c[1])}</p>`).join("");
  const cav = ((M.framework || {}).caveats || []).map(c => `<li>${esc(c)}</li>`).join("");
  $("#guideBody").innerHTML = `
  <div class="toc">
    <a href="#g1">1 这是什么</a><a href="#g2">2 十分钟上手</a><a href="#g3">3 逐个功能 + 场景</a><a href="#g4">4 五种预测方法与公式</a>
    <a href="#g5">5 依据引擎：结论 + 5 条支撑</a><a href="#g6">6 频率体系：月/季/年</a><a href="#g7">7 权威机构方法论</a>
    <a href="#g8">8 回测与检验</a><a href="#g9">9 传导：股市 / 债市</a><a href="#g10">10 分析师工作流</a><a href="#g11">11 数据字典</a><a href="#g12">12 局限与纪律</a>
  </div>

  <h2 id="g1">一、这是什么</h2>
  <p>这是一个面向宏观与策略分析师的<b>指标实时预测（nowcasting）+ 依据生成 + 资产传导</b>工作台。它要解决的问题是：官方数据有 1–6 周时滞，而市场在数据公布前已经开始定价；你需要在公布前给出一个<b>有数字、有依据、经得起追问</b>的判断。</p>
  <p>平台做三件事：① 把公布前可得的一切信息（指标历史、同期已公布的关联指标、当期研报）压缩成带区间的数值预测；② 自动生成<b>结论先行 + 不少于 5 条量化支撑</b>的论证，每条都带统计量与方法出处；③ 把预测翻译成对 A 股 / 港股 / 美股 / 中债 / 美债的<b>隐含影响</b>。</p>
  <div class="callout">与 Wind / iFinD 的关系：终端是<b>数据的权威来源与查询工具</b>，本平台是<b>数据之上的预测、论证与归因层</b>。终端告诉你“8 月出口同比是多少”，本平台回答“9 月大概是多少、凭哪 5 条依据、如果兑现对出口链和人民币意味着什么”。</div>

  <h2 id="g2">二、十分钟上手</h2>
  <ol>
    <li><b>总览</b>：按「一级分类 → 二级分类」排好的全部指标卡片。每张卡片顶部写明本次预测的<b>是哪一期</b>、预计何时公布；中间五个方框是五种方法各自的答案，金色框是按回测择优推荐的那个。</li>
    <li><b>预测中心 ①</b>：选一个指标，切换<b>月度 / 季度 / 年度</b>，直接看到「结论 → ≥5 条量化支撑 → 风险情景 → 股债含义 → 机构方法论」。</li>
    <li><b>一键更新</b>（右上角金色按钮）：重新抓数据 → 重算 SARIMAX / 多因子 / 桥方程 → 刷新市场库。<b>看板、预测中心、数据库、回测、档案会自动同步</b>，不需要逐页刷新。</li>
    <li><b>报告生成</b>：任选指标或全库，一键导出 Word / PPT / Excel / Markdown；也可以把你的写作要求交给 AI，让它基于<b>平台数据库</b>（而不是它的记忆）写研报。</li>
    <li><b>搜索</b>：右上角搜索框或左侧「搜索」页，输入指标名、公式名、机构名、因子名都能查到。</li>
  </ol>

  <h2 id="g3">三、逐个功能怎么用（每个功能配一个场景）</h2>

  <h3>1. 总览</h3>
  <p>按一级分类（增长 / 通胀 / 就业 / 外贸与外部 / 金融 / 财政 / 地产 / 景气）与二级分类分组展示。卡片上：最新公布值与环比方向、24 期迷你走势、本次预测对象与预计公布日、五种方法的预测值、推荐方法与理由。展开「预测依据」可看五种方法的完整推导；点「完整依据」打开抽屉，里面是曲线、多频率口径、结论与 5+ 条支撑、传导表、AI 研判全文与研报链接。</p>
  ${scene("月中数据周之前，我要快速判断本月哪几个指标会超预期", "打开总览 → 看金色推荐框与「较上期」箭头 → 对分歧大的指标（五种方法极差大）点开「完整依据」，重点看第 3 条（因子贡献）和第 4 条（领先信号）。极差大说明模型之间打架，这类指标最值得你亲自下判断，也最容易产生预期差。")}

  <h3>2. 实时看板</h3>
  <p>深色终端页：顶部走马灯与行情瀑布（股指、汇率、商品、国债收益率，5 秒刷新）；中部<b>宏观数据总表</b>按国家 + 一级/二级分类列出全部指标的最新值、变动、待发布期、推荐预测、方法与传导方向；右侧是预测脉搏、未来 45 天发布日历、实时研报流。</p>
  ${scene("早晨开盘前，我要用 3 分钟扫完全局", "看板 → 先看走马灯确认隔夜市场 → 看「发布日历」今天有什么数据 → 在总表里找出「待发布」列临近的行，看推荐预测与上期值的差 → 传导列的 ▲▼ 直接告诉你这个数据如果超预期，对本国股与债是利多还是利空。")}

  <h3>3. 预测中心</h3>
  <p>分三步：①<b>选择预测对象</b>——选指标 + 频率（月/季/年），立即得到结论与全部依据；②<b>运行 AI 研判</b>——选模型、输入方式（研报标题 / 正文片段 / 标题+AR / 纯数据）、预测期（当期或历史回测期），可勾选多个指标批量跑；③<b>最新研判</b>——所有当期结果列表，可展开看驱动因素、传导机制、引用研报。</p>
  ${scene("我要写一篇 CPI 点评，但数据还没公布", "预测中心 ① 选「CPI当月同比」→ 读结论与 5 条支撑（其中第 5 条会给出翘尾因素与近 5 年同月均值）→ 切到「季度」看本季均值 → ② 勾选 CPI 跑一次 AI 研判，拿到研报里的猪价与油价线索 → 报告生成页导出 Word，直接作为底稿。")}

  <h3>4. 数据库</h3>
  <p>三个频率页签：<b>月度 / 季度 / 年度</b>。月度指标聚合到季/年时，同比与指数取<b>期内均值</b>、流量取<b>期内合计</b>、存量取<b>期末值</b>；季度指标（如 GDP）的月度列是<b>桥方程追踪值</b>。带 * 号的列表示由聚合或桥方程派生。可按一级分类筛选，点任意行打开该指标详情。支持 CSV 与 Excel（6 张表）导出。</p>
  ${scene("领导要一份“过去三年月度+季度+年度”的中国宏观数据包", "数据库 → 导出 Excel（全库）→ 得到「预测总览 / 月度数据 / 季度数据 / 年度数据 / 回测评分 / 市场月度库」六张表，直接发出去。")}

  <h3>5. 搜索</h3>
  <p>一个入口搜四类内容：指标（含别名、关键词、理论驱动因素）、市场标的、机构方法论、计算方法与预测因子。搜索结果里的指标可直接点开详情。</p>
  ${scene("我想知道“翘尾”到底怎么算、平台在哪里用了它", "搜索「翘尾」→ 会同时返回「计算方法·翘尾因素」（含公式）与用到它的指标；点进 CPI 的依据第 5 条即可看到本期翘尾的具体数值。")}

  <h3>6. 报告生成</h3>
  <p>两块：<b>一键导出</b>（单指标 Word / PPT / Excel / Markdown；整站总览 Word、看板 PPT、全库 Excel）与 <b>AI 写作</b>（选范围 + 体裁 + 写你的 prompt，AI 基于平台数据库写作，再导出为 Word / PPT / Markdown）。AI 被强制要求“只用数据库里的数字、结论先行、不少于 5 条量化依据”。</p>
  ${scene("投委会明早要一页纸", "报告生成 → AI 写作 → 体裁选「投资委员会简报」→ prompt 写“800 字以内，先给结论，再给 5 条依据，最后给债券久期建议”→ 生成后导出 Word。")}

  <h3>7. 研报</h3>
  <p>按指标关键词召回当月宏观 + 策略研报，展示标题、机构、日期与直达链接；可切换“标题 / 标题+正文片段”。下方「召回规则」可加关键词、限定机构、排除日报周报——规则会同时作用于 AI 预测的输入。</p>
  ${scene("我只信几家机构的观点", "研报 → 召回规则 → 「只看这些机构」填“中金, 中信, 华泰, 国信” → 保存。之后所有 AI 研判读到的研报都只来自这几家。")}

  <h3>8. 回测</h3>
  <p>逐指标对照五种方法的历史表现，可切换口径（相关系数 / RMSE / 方向命中率）。高亮单元格是该指标的最优方法。下方可跑 AI 历史回测（真实调用模型，逐期只用当时信息），以及泄漏检验。</p>
  ${scene("有人质疑“你这模型到底准不准”", "回测 → 口径切到 RMSE → 指着该指标那一行说：沿用上期 RMSE 是 X，我们推荐的方法是 Y，样本 N 期，扩展窗口、无未来信息；再切到方向命中率说明对交易更重要的是方向。")}

  <h3>9. 预测档案</h3>
  <p>每一次预测都留档：目标期、信息截止日、完整 Prompt、模型原始输出、思考过程、引用研报清单、耗时与 token。可按指标 / 类型筛选并导出 CSV。</p>
  ${scene("上个月预测错了，要复盘", "档案 → 选该指标 → 找到当时那条 → 点「详情」看当时读了哪些研报、AI 给的驱动因素是什么 → 判断是信息缺失还是判断偏差，据此调整「设置 → 预测要求」或研报召回规则。")}

  <h3>10. 问 AI</h3>
  <p>对话式问答，已注入中美全部指标最新值、五种方法的当期预测与回测表现。适合快速核对与追问。</p>
  ${scene("客户电话里突然问“中美利差现在多少、对人民币什么含义”", "问 AI 直接问，它会引用平台里的中债 10Y、美债 10Y 最新值与利差，并结合传导框架回答。")}

  <h3>11. 设置</h3>
  <p>「预测要求」是写给 AI 的长期指令，作用于<b>所有</b>预测、问答与报告生成；下方有一排常用要求，点一下即可加入。AI 的信息来源有两类：<b>外部网站</b>（东方财富研报中心）与<b>本平台内嵌数据库</b>（全部序列、五法预测、回测、桥方程、传导回归）。</p>
  ${scene("我希望每次输出都符合我们内部的写作规范", "设置 → 预测要求里写死规范（例如“每条依据必须带数字”“必须给出对 10Y 国债的操作含义”）→ 保存。之后无需重复交代。")}

  <h2 id="g4">四、五种预测方法与数学公式</h2>
  <p>对每个待测指标，平台<b>同时</b>跑五种方法，并按历史回测表现推荐其一。五种方法的信息集是递进的：从只用自身上期 → 自身全部历史 → 全体关联指标 → 季内已公布的月度数据 → 文本信息。</p>
  <h3>方法一：沿用上期（随机游走基准）</h3>
  <div class="formula">ŷ<sub>t</sub> = y<sub>t−1</sub></div>
  <p>所有预测研究的基准线。对高持续性序列，随机游走极难被战胜；跑不赢它的方法说明没有提取到额外信息。规则：当 corr(y<sub>t</sub>, y<sub>t−1</sub>) ≥ 0.8 时直接采用，除非其他方法显著超越。</p>
  <h3>方法二：SARIMAX（季节性 + 外生变量）</h3>
  <div class="formula">φ(L)Φ(L<sup>s</sup>)(1−L)<sup>d</sup> y<sub>t</sub> = c + β′x<sub>t</sub> + θ(L)Θ(L<sup>s</sup>)ε<sub>t</sub>，月度 s=12，季度 s=4</div>
  <p>差分阶数 d 由 ADF 单位根检验决定（p &lt; 0.05 → d=0）；(p,q) 在 p≤3、q≤2 网格上按 AIC = n·ln(SSE/n) + 2k 选择，<b>每年 1 月（季度指标每年 Q1）重选一次</b>；外生变量 x<sub>t</sub> 为春节假期占比（中国 1–2 月错位）；参数用条件平方和估计，AR 部分经 PACF 变换保证平稳；残差用 Ljung–Box 检验；80% 区间取 ŷ ± 1.28σ，σ 用<b>稳健标准差 1.4826×MAD</b>（弱化 2020 年异常）。</p>
  <h3>方法三：多因子岭回归（横截面信息）</h3>
  <div class="formula">ŷ = ȳ + Σ<sub>j</sub> β<sub>j</sub> z<sub>j</sub>，β̂ = (Z′Z + λI)<sup>−1</sup>Z′(y − ȳ)，λ = 1</div>
  <p>特征 = 自身滞后 1/2/12 期 + 同国关联指标滞后 1 期（领先指标 PMI/ISM/信心取当期，因其当月即公布）。特征筛选<b>只用回测起点之前</b>的样本按 |corr| 取前 8，避免前视偏差；训练样本按 2%/98% 分位缩尾（winsorize），预测时 z 值截断在 ±3σ，防止极端输入外推。输出直接给出<b>每个因子的贡献 β<sub>j</sub>·z<sub>j</sub></b>——这就是依据第 3 条的来源。</p>
  <h3>方法四：桥方程（季度指标 ← 月度数据）</h3>
  <div class="formula">y<sub>q</sub> = α + Σ<sub>j</sub> β<sub>j</sub> z̄<sub>j,q</sub>，月度追踪值 = α + Σ<sub>j</sub> β<sub>j</sub> z<sub>j</sub>(季度至今均值)</div>
  <p>这是亚特兰大联储 GDPNow 的单方程简化版：用工业增加值、社零、出口、固投、PMI、PPI、贷款等月度指标的<b>季内均值</b>预测当季 GDP，并随每月数据公布逐月更新。扩展窗口逐季重估，给出样本外 RMSE。</p>
  <h3>方法五：AI 研判（文本 + 数据 + 模型）</h3>
  <p>前四种方法读不了文字。研报里有高频跟踪数据（港口吞吐、开工率、票据利率、乘用车批发）、政策解读与拐点判断。流程：召回目标期内全部宏观 + 策略研报 → <b>严格时点截断</b>（只取目标期最后一天及之前发布的）→ 组装 Prompt（历史序列、关联指标、四种模型的参考值、理论驱动、研报标题、你的要求）→ 强制返回结构化 JSON（数值、区间、方向、置信、驱动因素、传导机制、证据、风险、与模型的差异）。</p>
  <h3>组合与择优</h3>
  <div class="formula">组合：ŷ<sub>c</sub> = Σ w<sub>i</sub>ŷ<sub>i</sub>，w<sub>i</sub> ∝ 1/RMSE<sub>i</sub><sup>2</sup>（Bates–Granger 1969）</div>
  <p>推荐哪一种由固定规则从回测推出（桥方程显著更优 → 桥方程；惯性极强 → 沿用上期；AI 有足够回测样本 → 同窗口最优者；统计模型显著超越 → 该模型；否则 → AI）。组合值作为稳健性核对，权重使用<b>剔除 2020 年</b>的 RMSE。</p>

  <h2 id="g5">五、依据引擎：结论先行 + 不少于 5 条量化支撑</h2>
  <p>每个指标的依据按固定结构自动生成，顺序与卖方研报的论证顺序一致：</p>
  <table><tr><th>条目</th><th>回答什么问题</th><th>用到的统计量</th></tr>
    <tr><td>① 基准与惯性</td><td>不做任何模型时应该是多少</td><td>近 4 期实际值、基准相关系数与 RMSE</td></tr>
    <tr><td>② 时序模型与季节性</td><td>自身历史规律指向哪里</td><td>SARIMAX 阶数、ADF p、Ljung–Box p、回测 corr/RMSE/命中率、当月季节偏离</td></tr>
    <tr><td>③ 因子贡献分解</td><td>本期主要被谁拉动、被谁拖累</td><td>β<sub>j</sub>·z<sub>j</sub> 前五、截距、回测表现</td></tr>
    <tr><td>④ 领先/同步信号</td><td>已公布的其他数据说了什么</td><td>交叉相关扫描（0–3 期领先）、最新值与变动、合力方向</td></tr>
    <tr><td>⑤ 基数效应与同期比较</td><td>去年同期高低对今年同比的影响</td><td>去年同期值与动量、两年变动、翘尾因素、近 5 年同期均值与区间</td></tr>
    <tr><td>⑥ 历史相似期</td><td>形态类似的历史时点后来怎么走</td><td>标准化形状匹配的 5 段、其后平均变动与上行概率</td></tr>
    <tr><td>⑦ 桥方程追踪（季度指标）</td><td>季内已公布月份把当季推到哪</td><td>R²、样本外 RMSE、逐月追踪值</td></tr>
    <tr><td>⑧ 组合与不确定性</td><td>各方法分歧多大、区间多宽</td><td>组合权重、80% 区间、方法极差</td></tr>
    <tr><td>⑨ 跨频率含义</td><td>这一期对当季 / 当年意味着什么</td><td>已实现占比、聚合口径、剩余期外推方法</td></tr>
  </table>
  <p>此外还有<b>风险情景</b>（乐观 / 基准 / 悲观 / 95% 区间，基于稳健残差 σ）与<b>市场含义</b>（预期差 z 值 × 事件回归 β，逐资产给出隐含变动）。</p>
  ${scene("有人追问“你凭什么说 9 月出口会回落”", "打开该指标依据 → 逐条念：基准是多少、SARIMAX 给多少且回测 RMSE 多少、哪几个因子在拖累且各贡献多少、领先信号几比几、去年基数抬升多少、历史相似期后来平均跌多少、五种方法极差多大。每一句都有数字，这就是可追问的论证。")}

  <h2 id="g6">六、频率体系：月度 / 季度 / 年度</h2>
  <p>任何指标都可以在三个频率上查看与预测：</p>
  <ul>
    <li><b>原生频率</b>：指标本身的发布频率（多数月度，GDP / 税收等季度，FDI 年度）。</li>
    <li><b>向上聚合</b>：月度 → 季度 / 年度。同比与指数取<b>期内均值</b>，流量（新增贷款、非农、贸易差额）取<b>期内合计</b>，存量（外储）取<b>期末值</b>。1–2 月合并发布的指标自动按 2 期计算，不会误判为缺失。</li>
    <li><b>向下分解</b>：季度 GDP → 月度<b>桥方程追踪值</b>。</li>
    <li><b>当期追踪</b>：当季 / 当年 = 已公布期的实际值 + 待公布期的模型预测 + 更远期的外推（同比用季节漂移、环比用近 5 年同月均值、流量用同比比例法），并显示<b>已实现占比</b>——这正是 IMF / OECD 做年度预测时的 carry-over 口径。</li>
  </ul>
  ${scene("我要回答“今年全年 GDP 大概多少”", "预测中心选 GDP当季同比 → 切到「年度」→ 页面显示：已公布 2/4 季（已实现 4.71%），本季桥方程预测 X，第四季按季节漂移外推 Y，全年 Z；同时告诉你已实现占比 50%，也就是说这个数字还有一半来自模型。")}

  <h2 id="g7">七、权威机构的方法论（已内嵌）</h2>
  <p>下列方法均来自各机构公开文档与论文，平台按其思想构建对应模块；每条都注明了公开披露的精度与本平台的具体应用方式。</p>
  ${inst}

  <h2 id="g8">八、回测与检验</h2>
  <h3>扩展窗口回测</h3>
  <p>预测第 t 期时只用 1…t−1 期信息重新拟合，逐期推进，绝不使用未来数据。这与“全样本拟合一次再看拟合优度”有本质区别。</p>
  ${forms}
  <h3>泄漏检验</h3>
  <p>大模型训练数据可能已包含历史宏观数据。以模型知识截止日为界把回测样本切成两段，比较 corr<sub>截止前</sub> 与 corr<sub>截止后</sub>。若差距很大，说明历史段的优异表现来自记忆而非推理，应以<b>截止后</b>那一段为准。平台同时给出同窗口的沿用上期基准，排除“某段时期本身就好预测”的干扰。</p>
  ${scene("我要确认 AI 那一列是不是作弊", "回测 → 泄漏检验 → 选指标、设切分月（默认 2025-01）→ 看两段的 AI 相关性差异，并与同窗口的沿用上期对比。")}

  <h2 id="g9">九、传导：预测出来能干什么</h2>
  <h3>惊喜的构造</h3>
  <p>市场对<b>预期差</b>定价，不对水平定价。缺乏一致预期数据时，标准学术做法是用时序模型的事前预测作为预期代理：</p>
  <div class="formula">s<sub>t</sub> = y<sub>t</sub> − ŷ<sub>t|t−1</sub>（SARIMAX 扩展窗口事前预测），z<sub>t</sub> = s<sub>t</sub> / σ<sub>s</sub></div>
  <h3>事件回归</h3>
  <div class="formula">r<sub>t+k</sub> = α + β·s<sub>t</sub> + ε，股指 r = 100·ln(P<sub>t</sub>/P<sub>t−1</sub>)（%），收益率 r = ΔY（bp），k = 发布滞后</div>
  <p>平台给出全样本 β、两个月累计 β、近 5 年 β 三组估计，以及 t 值、R²、方向一致率、正/负惊喜的均值反应，并与理论方向对照（✓ 一致 / ✗ 相反）。最右列「本次隐含」= β<sub>std</sub> × z<sub>本次</sub>，即“若本次预测兑现，按历史关系该资产当月的隐含反应”。</p>
  <h3>五条传导渠道</h3>
  ${chan}
  <h3>使用纪律</h3>
  <ul>${cav}</ul>
  ${scene("预测到 CPI 超预期，我要落到持仓上", "打开 CPI 的依据 → 「对股市/债市的含义」表 → 看中债 2Y 与 10Y 的隐含变动（通胀惊喜主要冲击短端）、创业板与沪深300 的差异（成长股久期长、对通胀更敏感）→ 再看 t 值与近 5 年 β 是否稳定，不稳定就只用方向不用幅度。")}

  <h2 id="g10">十、分析师工作流建议</h2>
  <ol>
    <li><b>月初</b>：看板 → 发布日历确认本月日程；对 PMI / ISM 等当月公布的景气指标先跑一轮预测。</li>
    <li><b>数据周前 2–3 天</b>：点「一键更新」（此时当月研报已积累，AI 信息量最充分），再对重点指标跑 AI 研判。</li>
    <li><b>写观点</b>：打开指标依据，把 9 条支撑直接作为逻辑框架；传导表给资产含义；研报链接进底稿；报告生成页导出 Word / PPT。</li>
    <li><b>数据公布后</b>：档案页对照预测与真实值，记录偏差原因。系统会自动并入新数据、重算模型。</li>
    <li><b>季度复盘</b>：回测页把区间设为最近一年，检查各方法表现是否发生结构性变化；必要时调整预测要求与召回规则。</li>
  </ol>
  <h3>把预测转化为投资观点的三个层次</h3>
  <p><b>宏观层</b>：多个指标的预测合在一起就是对当前经济动能的判断。例如同时预测到出口走弱、信贷不及预期、PPI 继续负增长 → 总需求不足 + 通缩压力 → 政策预期指向降准降息与财政加码。</p>
  <p><b>债市</b>：增长与通胀预测直接对应收益率方向。通胀低于预期 + 信贷收缩 → 降息空间打开 → 做多利率债；曲线形态上，通胀惊喜主要冲击短端（2Y，政策预期），增长惊喜主要冲击长端（10Y，期限溢价与名义增速）。</p>
  <p><b>股市</b>：分子看增长（工业、社零、出口），分母看通胀与利率。传导表给出对沪深300 / 创业板 / 恒生 / 标普 / 纳指的差异化 β——创业板与纳指久期长，对利率与通胀惊喜更敏感；沪深300 与道指偏价值，对增长惊喜更敏感。板块映射：出口 → 电子/机械/纺服；信贷 → 银行/建材/地产链；PPI → 煤炭/有色/化工；社零 → 食饮/家电/汽车。</p>

  <h2 id="g11">十一、数据字典与预测因子</h2>
  <table><tr><th>数据类别</th><th>来源</th><th>历史</th><th>更新</th></tr>
    <tr><td>中国宏观（增长/通胀/外贸/金融/财政/地产/景气，含月、季、年）</td><td>国家统计局 / 海关总署 / 中国人民银行口径，经东方财富数据中心</td><td>2005–2008 年起</td><td>每小时轮询；一键更新可立即重算</td></tr>
    <tr><td>美国宏观（增长/通胀/就业/外贸/金融/地产）</td><td>东方财富·全球宏观（BLS / BEA / Census / ISM / 美联储官方发布值转载）；FRED 为备源</td><td>2008 年起</td><td>同上</td></tr>
    <tr><td>市场月度库</td><td>东方财富 K 线与国债收益率表：A股宽基（沪深300/上证/创业板/中证500/中证1000/科创50）、恒生、美股三大、日经、美元指数、USDCNH、黄金、原油；中美 2Y/10Y/30Y 收益率</td><td>2005 年起</td><td>每 6 小时 + 当月用实时价刷新</td></tr>
    <tr><td>研报</td><td>东方财富研报中心（宏观研究 + 策略报告）</td><td>2017 年起</td><td>按月抓取并缓存</td></tr>
    <tr><td>实时行情</td><td>东方财富 push2（备源：腾讯行情、东财数据中心）</td><td>日内</td><td>5 秒</td></tr>
  </table>
  <p><b>三级回退</b>：实时抓取失败 → 本地缓存 → 内置快照。任何时候平台都能启动并给出数据，侧栏会标注当前数据源，绝不静默使用过期数据。</p>
  <h3>各类指标的常用预测因子（分析师口径）</h3>
  <table><tr><th>分类</th><th>预测因子</th></tr>${facs}</table>

  <h2 id="g12">十二、局限与使用纪律</h2>
  <p><b>① 预测精度存在天花板。</b>M2、美国 CPI 同比等高惯性指标相关系数可达 0.9+，但主要来自惯性；出口、信贷、非农等真正有信息量的指标，0.5–0.7 已是优秀水平。声称能把非农预测到 0.9 相关性的方法，应先怀疑数据泄漏。</p>
  <p><b>② AI 回测需要你亲自跑。</b>统计模型回测是实时计算的，AI 那几列默认为空——每个数据点都是一次真实调用。在跑过之前，「AI 研判」的推荐仅基于决策规则而非该指标的实证表现。</p>
  <p><b>③ 传导关系不稳定。</b>样本期跨越去杠杆、疫情、通胀冲击等多个政策环境，全样本 β 是加权平均，未必代表当下。务必对照「近 5 年 β」与「两个月累计 β」。</p>
  <p><b>④ 月度频率稀释事件效应。</b>真实的数据日冲击集中在公布后数小时内，月度收益会被其他事件淹没。本平台给的是月度层面的统计关系，方向价值大于幅度价值。</p>
  <p><b>⑤ 这是研究工具，不是投资建议。</b>所有预测均为模型输出，不构成任何证券的买卖建议。</p>`;
}
