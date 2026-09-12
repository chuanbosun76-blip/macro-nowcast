/* 观数 · 宏观预测平台 v2（原生 JS） */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const S = { meta: null, country: "CN", view: "overview", status: null, ov: {}, seriesCache: {}, chat: [], settings: null };
const VIEW_TITLE = { overview: "总览", predict: "预测中心", data: "数据库", reports: "研报", backtest: "回测", archive: "预测档案", ask: "问 AI", settings: "设置" };
const REC_NAME = { persist: "沿用上期", ar: "SARIMAX", ai: "AI 研判", ref: "参考" };
const MODE_SHORT = { title: "AI·标题", chunk: "AI·正文", title_ar: "AI·标题+AR", data: "AI·纯数据" };
const MODES_ORDER = ["title", "chunk", "title_ar", "data"];
const COUNTRY_NAME = { CN: "中国", US: "美国" };

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
function ind(id) { return S.meta.indicators.find(x => x.id === id); }
function fmtV(v, unit, sign) {
  if (v == null || !isFinite(v)) return "—";
  let s;
  if (["亿元", "千人", "千套"].includes(unit)) s = Math.round(v).toLocaleString("zh-CN");
  else if (unit === "亿美元") s = (Math.round(v * 10) / 10).toLocaleString("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  else s = (Math.round(v * 100) / 100).toFixed(unit === "%" ? 1 : 1);
  if (sign && v > 0) s = "+" + s;
  return s;
}
function fmtC(v) { return v == null || !isFinite(v) ? "—" : v.toFixed(2); }
function monthLabel(m, freq) { if (!m) return "—"; if (freq === "Q") return `${m.slice(0, 4)}年Q${Math.ceil(+m.slice(5, 7) / 3)}`; return `${m.slice(0, 4)}年${+m.slice(5, 7)}月`; }
function openModal(html) { $("#modalBody").innerHTML = html; $("#modal").hidden = false; }
function openDrawer(html) { $("#drawerBody").innerHTML = html; $("#drawer").hidden = false; }
$("#modalX").onclick = () => { $("#modal").hidden = true; };
$("#drawerX").onclick = () => { $("#drawer").hidden = true; };
$("#modal").onclick = ev => { if (ev.target.id === "modal") $("#modal").hidden = true; };
$("#drawer").onclick = ev => { if (ev.target.id === "drawer") $("#drawer").hidden = true; };
document.addEventListener("keydown", ev => { if (ev.key === "Escape") { $("#modal").hidden = true; $("#drawer").hidden = true; } });
function mdLite(t) { return esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/^#{1,4}\s*(.+)$/gm, "<b>$1</b>").replace(/^\s*[-•]\s+/gm, "· "); }
function fillSelect(sel, opts, val) { sel.innerHTML = opts.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join(""); if (val != null) sel.value = val; }
function modelOpts() { return (S.status && S.status.models || []).map(m => [m.id, m.label]); }
function countryInds(role) { return S.meta.indicators.filter(i => i.country === S.country && (!role || role.includes(i.role))); }

/* ---------------- 图表（SVG） ---------------- */
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
  ticks.forEach(t => { svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}" stroke="#eeeae2"/><text x="${pad.l - 8}" y="${y(t) + 4}" font-size="11" text-anchor="end" fill="#7b8591">${fmtTick(t)}</text>`; });
  if (lo < 0 && hi > 0) svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(0)}" y2="${y(0)}" stroke="#b9b2a4" stroke-dasharray="3 3"/>`;
  const step = Math.max(1, Math.ceil(months.length / Math.floor((W - pad.l) / 70)));
  months.forEach((m, i) => { if (i % step === 0) svg += `<text x="${x(i)}" y="${H - 8}" font-size="11" text-anchor="middle" fill="#7b8591">${m.slice(2).replace("-", "/")}</text>`; });
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
    tip.innerHTML = `<b>${monthLabel(m)}</b><br>` + cfg.series.map(s => `<span style="color:${s.color === "#14202e" ? "#fff" : s.color}">■</span> ${esc(s.name)}：${fmtV(s.data[m], cfg.unit)}`).join("<br>");
    tip.hidden = false; tip.style.left = Math.min(ev.clientX + 14, innerWidth - 270) + "px"; tip.style.top = (ev.clientY + 14) + "px";
  });
  rect.addEventListener("mouseleave", () => { tip.hidden = true; hx.setAttribute("opacity", 0); });
}
function niceTicks(lo, hi, n) { const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag; const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag; const out = []; for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(+t.toFixed(10)); return out; }
function fmtTick(t) { return Math.abs(t) >= 10000 ? (t / 10000).toFixed(1) + "万" : (+t.toFixed(2)).toString(); }
function spark(values) {
  const v = values.filter(x => x != null).slice(-24); if (v.length < 2) return "";
  const W = 110, H = 30, lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
  const d = v.map((a, i) => (i ? "L" : "M") + (i / (v.length - 1) * W).toFixed(1) + " " + (H - 3 - (a - lo) / r * (H - 6)).toFixed(1)).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><path d="${d}" fill="none" stroke="#44505e" stroke-width="1.3"/></svg>`;
}

/* ---------------- 状态 ---------------- */
async function refreshStatus() {
  try {
    const st = await api("/api/status"); S.status = st;
    const dot = st.error ? "bad" : (st.ready ? "ok" : "warn");
    const d = st.data || {}, src = d.source || {};
    const phase = st.ready ? (st.loading ? `就绪 · 后台${d.stage || "更新中"}` : "模型就绪") : st.loading ? (d.stage ? `${d.stage}…` : `模型计算中 ${Math.round((st.ar_progress || 0) * 100)}%`) : "等待加载";
    $("#sideStatus").innerHTML = `<div><span class="dot ${dot}"></span>${esc(phase)}</div>
      <div>中国：${esc(src.cn || "—")}</div><div>美国：${esc(src.us || "—")}</div><div>更新：${esc(d.fetched_at || "—")} · 每 ${st.refresh_hours} 小时</div>
      <div><span class="dot ${st.has_key ? "ok" : "bad"}"></span>模型：${(st.models || []).length} 个可用</div>
      ${d.ifind && d.ifind.enabled ? `<div><span class="dot ${d.ifind.last_error ? "warn" : "ok"}"></span>iFinD ${d.ifind.loaded}/${d.ifind.mapped}</div>` : ""}
      <div>预测记录：${(st.runs || {}).ok || 0} 条</div>`;
    $("#topMeta").innerHTML = `指标 ${(st.n_indicators || {}).CN || 0} + ${(st.n_indicators || {}).US || 0} · 默认模型 <b>${esc(st.model)}</b>${st.auth_required ? " · 需口令" : ""}`;
    return st;
  } catch (e) { $("#sideStatus").innerHTML = `<span class="dot bad"></span>服务不可达`; return null; }
}

/* ---------------- 总览 ---------------- */
async function loadOverview() {
  let rows;
  try { rows = (await api(`/api/overview?country=${S.country}`)).rows; }
  catch (e) {
    if (e.status === 503) { $("#ovGroups").innerHTML = `<div class="skel">数据加载与模型计算中…</div>`; setTimeout(() => { if (S.view === "overview") loadOverview(); }, 3000); return; }
    $("#ovGroups").innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; return;
  }
  S.ov[S.country] = rows;
  const st = S.status || {};
  const now = rows.filter(r => r.role === "nowcast"), withAI = now.filter(r => r.ai), missing = rows.filter(r => r.missing);
  $("#kpis").innerHTML = [
    ["指标数", rows.length, `${COUNTRY_NAME[S.country]} · ${missing.length ? missing.length + " 项待数据源" : "全部有数据"}`],
    ["待发布 · 实时预测中", now.length, "沿用上期 / SARIMAX / AI 三法并行"],
    ["AI 已覆盖", `${withAI.length}/${now.length}`, withAI.length ? "最近一次：" + (withAI[0].ai.created_at || "").slice(5, 16) : "去预测中心一键运行"],
    ["数据更新", (st.data || {}).fetched_at || "—", (st.data || {}).source ? esc((st.data.source[S.country.toLowerCase()] || "")) : ""],
  ].map(([k, v, s]) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  let html = "";
  for (const g of S.meta.groups) {
    const rs = rows.filter(r => r.group === g); if (!rs.length) continue;
    const main = rs.filter(r => r.role !== "ref" && !r.missing), ref = rs.filter(r => r.role === "ref" || r.missing);
    html += `<div class="grp-h">${g}<small>${rs.length} 项</small></div>`;
    if (main.length) html += `<div class="cards">${main.map(cardHTML).join("")}</div>`;
    if (ref.length) html += `<div class="cards ref" style="margin-top:10px">${ref.map(refCardHTML).join("")}</div>`;
  }
  $("#ovGroups").innerHTML = html;
  $$("[data-detail]").forEach(b => b.onclick = () => showDetail(b.dataset.detail));
  $$("[data-run]").forEach(b => b.onclick = () => runOne(b.dataset.run, b));
}
function cardHTML(r) {
  const chg = r.prev_value != null ? r.last_value - r.prev_value : null;
  const ai = r.ai, best = r.recommend;
  const pred = (key, label, v, sub) => `<div class="pred ${best === key ? "best" : ""}"><span class="k">${label}</span><span class="x">${fmtV(v, r.unit)}</span><div class="s">${sub}</div></div>`;
  return `<article class="card rec-${best}">
    <div class="card-h"><div><div class="nm">${esc(r.name)}</div><div class="grp">${esc(r.unit || "指数")} · ${esc(r.release)}</div></div><span class="tag ${best}">推荐：${REC_NAME[best]}</span></div>
    <div class="last"><span class="v">${fmtV(r.last_value, r.unit)}</span><span class="u">${esc(r.unit)} · ${monthLabel(r.last_month, r.freq)}已公布</span>
      ${chg != null ? `<span class="chg ${chg > 0 ? "up" : chg < 0 ? "down" : ""}">${chg > 0 ? "▲" : chg < 0 ? "▼" : "—"} ${fmtV(Math.abs(chg), r.unit)}</span>` : ""}${spark(r.history.map(h => h[1]))}</div>
    <div class="pend">待发布：<b>${monthLabel(r.pending_month, r.freq)}</b></div>
    <div class="preds">
      ${pred("persist", "沿用上期", r.persist_pred, `回测相关 ${fmtC(r.persist_corr)}`)}
      ${pred("ar", "SARIMAX", r.ar_pred, `${esc(r.ar_order || "")} · ${fmtC(r.ar_corr)}`)}
      ${pred("ai", "AI 研判", ai ? ai.value : null, ai ? `${ai.low != null ? fmtV(ai.low, r.unit) + "~" + fmtV(ai.high, r.unit) : ""}<span class="conf ${esc(ai.confidence || "")}">${esc(ai.confidence || "")}</span>` : "待运行")}
    </div>
    ${ai && ai.reason ? `<div class="ai-sum"><b>AI：</b>${esc(ai.reason)}</div>` : `<div class="why">${esc(r.why || "")}</div>`}
    <div class="card-f"><span class="hint">${ai ? esc(r.why || "") : ""}</span><span><button class="btn sm ghost" data-detail="${r.id}">详情</button> <button class="btn sm" data-run="${r.id}">AI 预测</button></span></div>
  </article>`;
}
function refCardHTML(r) {
  if (r.missing) return `<article class="card missing"><div class="card-h"><div class="nm">${esc(r.name)}</div><span class="tag ref">数据源</span></div><div class="hint">${esc((r.notes || []).join("；") || "暂无数据")}</div></article>`;
  const chg = r.prev_value != null ? r.last_value - r.prev_value : null;
  return `<article class="card"><div class="card-h"><div><div class="nm">${esc(r.name)}</div><div class="grp">${esc(r.release)}</div></div><span class="tag ref">参考</span></div>
    <div class="last"><span class="v">${fmtV(r.last_value, r.unit)}</span><span class="u">${esc(r.unit)} · ${monthLabel(r.last_month, r.freq)}</span>${chg != null ? `<span class="chg ${chg > 0 ? "up" : chg < 0 ? "down" : ""}">${chg > 0 ? "▲" : chg < 0 ? "▼" : "—"} ${fmtV(Math.abs(chg), r.unit)}</span>` : ""}${spark(r.history.map(h => h[1]))}</div>
    <div class="card-f"><span class="hint">${esc(r.theory || "")}</span><button class="btn sm ghost" data-detail="${r.id}">详情</button></div></article>`;
}
async function getSeries(id, force) {
  if (!force && S.seriesCache[id] && Date.now() - S.seriesCache[id]._t < 30000) return S.seriesCache[id];
  const d = await api(`/api/series/${id}`); d._t = Date.now(); S.seriesCache[id] = d; return d;
}
function analysisHTML(r, unit) {
  const a = r.analysis || {};
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
    <p class="hint" style="margin-top:8px"><a href="#" data-run-id="${r.id}">查看完整 Prompt 与原始输出</a></p></div>`;
}
async function showDetail(id) {
  const m = ind(id);
  openDrawer(`<h2>${esc(m.name)}</h2><div class="hint">${esc(m.release)} · ${esc(m.theory || "")}</div><div class="legend" id="dLegend" style="margin:10px 0"></div><div class="chart" id="dChart"></div><div class="stat-row" id="dStat"></div><div id="dAI" class="skel">加载中…</div>`);
  const ser = await getSeries(id, true);
  const from = ser.months[Math.max(0, ser.months.length - 72)], months = ser.months.filter(x => x >= from).concat(ser.pending_month ? [ser.pending_month] : []);
  const act = Object.fromEntries(ser.months.map((x, i) => [x, ser.values[i]]));
  const series = [{ name: "真实值", color: "#14202e", data: act, width: 2.2 }];
  if (Object.keys(ser.persist).length) series.push({ name: "沿用上期", color: "#9aa3ad", data: ser.persist, dash: "4 3" });
  if (Object.keys(ser.ar).length) series.push({ name: "SARIMAX", color: "#1d6b73", data: Object.assign({}, ser.ar, ser.ar_nowcast != null ? { [ser.pending_month]: ser.ar_nowcast } : {}) });
  if (ser.llm.title) series.push({ name: "AI 回测", color: "#a8832f", data: ser.llm.title, dots: true });
  const live = (ser.live || [])[0];
  if (live) series.push({ name: "AI 当期", color: "#a8322a", data: { [ser.pending_month]: live.value }, dots: true, band: live.low != null ? { [ser.pending_month]: [live.low, live.high] } : null });
  $("#dLegend").innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
  lineChart($("#dChart"), { months, series, unit: m.unit, shadeFrom: ser.pending_month, clip: true, height: 300 });
  const d = ser.diag || {};
  $("#dStat").innerHTML = `<span>最新 <b>${monthLabel(ser.months[ser.months.length - 1], m.freq)} ${fmtV(ser.values[ser.values.length - 1], m.unit)}</b></span>
    ${d.final_order ? `<span>SARIMAX <b>${esc(d.final_order)}</b></span><span>ADF p <b>${d.adf_p != null ? d.adf_p.toFixed(3) : "—"}</b></span>` : ""}
    <span>${esc((ser.notes || []).join("；"))}</span>`;
  const runs = await api(`/api/runs?indicator=${id}&limit=20&ok=1`);
  $("#dAI").className = "";
  $("#dAI").innerHTML = (live ? `<h3 style="margin-top:14px">AI 当期研判 · ${monthLabel(live.target_month, m.freq)} → <span class="up">${fmtV(live.value, m.unit)} ${esc(m.unit)}</span></h3><div class="sum">${esc(live.reason || "")}</div>${analysisHTML(live, m.unit)}` : `<p class="muted" style="margin-top:14px">尚无 AI 当期研判。</p>`) +
    `<div class="ctl-row" style="margin-top:10px"><button class="btn primary sm" data-run="${id}">运行 AI 预测</button><span class="hint">用当月研报 + 最新数据重新研判</span></div>` +
    (runs.length > 1 ? `<h3 style="margin-top:14px">历史记录</h3><div class="tbl-wrap"><table class="arc"><tr><th>时间</th><th>目标月</th><th>预测</th><th>真实</th><th>模型</th><th>结论</th></tr>` +
      runs.map(x => `<tr><td>${esc((x.created_at || "").slice(0, 16))}</td><td>${x.target_month}</td><td><b>${fmtV(x.value, m.unit)}</b></td><td>${fmtV(act[x.target_month], m.unit)}</td><td>${esc(x.model)}</td><td class="r">${esc((x.reason || "").slice(0, 80))} <a href="#" data-run-id="${x.id}">详情</a></td></tr>`).join("") + `</table></div>` : "");
  bindRunLinks($("#dAI")); $$("[data-run]", $("#dAI")).forEach(b => b.onclick = () => runOne(b.dataset.run, b, true));
}
function bindRunLinks(root) { $$("[data-run-id]", root).forEach(a => a.onclick = ev => { ev.preventDefault(); showRun(a.dataset.runId); }); }
async function runOne(id, btn, inDrawer) {
  if (btn) btn.disabled = true;
  try {
    const job = await api("/api/nowcast", { method: "POST", json: { indicators: [id], mode: $("#pMode").value || "title", model: $("#pModel").value || S.status.model } });
    const box = document.createElement("div"); (btn ? btn.closest(".card, #dAI, .res") || $("#pJob") : $("#pJob")).appendChild(box);
    trackJob(job.id, box, () => { if (btn) btn.disabled = false; loadOverview(); if (inDrawer) showDetail(id); if (S.view === "predict") renderPredictResults(); });
  } catch (e) { if (btn) btn.disabled = false; alertBox(e); }
}
function alertBox(e) { openModal(`<h2>操作失败</h2><p>${esc(e.message)}${e.status === 401 ? "（请先输入访问口令）" : ""}</p>`); }
function trackJob(id, box, onDone) {
  const tick = async () => {
    let j; try { j = await api(`/api/jobs/${id}`); } catch (e) { return; }
    const pct = j.total ? Math.round(j.done / j.total * 100) : 100;
    let html = `<div class="job"><b>${esc(j.label)}</b> · ${esc(j.model)} · ${j.done}/${j.total}（成功 ${j.ok}，失败 ${j.failed}${j.skipped ? `，跳过 ${j.skipped}` : ""}）${j.status === "done" ? " · 已完成" : " · 运行中…"}<div class="bar"><i style="width:${pct}%"></i></div>`;
    const res = (j.results || []).slice(-5).reverse();
    if (res.length) html += res.map(r => { const m = ind(r.indicator); return `<div>${esc(m.short)} ${monthLabel(r.target_month, m.freq)}：<b>${r.value != null ? fmtV(r.value, m.unit) : "—"}</b> <span class="muted">${esc((r.reason || r.error || "").slice(0, 90))}</span></div>`; }).join("");
    if (j.errors && j.errors.length) html += `<div class="err">${j.errors.slice(-3).map(esc).join("<br>")}</div>`;
    box.innerHTML = html + "</div>";
    if (j.status !== "done") setTimeout(tick, 2500); else onDone && onDone(j);
  };
  tick();
}
async function showRun(id) {
  const r = await api(`/api/runs/${id}`), m = ind(r.indicator);
  openModal(`<h2>预测记录 #${r.id} · ${esc(m.name)}</h2><div class="kv">
    <div>目标月</div><div>${monthLabel(r.target_month, m.freq)}（信息截至 ${esc(r.cutoff)}）</div>
    <div>预测值</div><div><b>${fmtV(r.value, m.unit)} ${esc(m.unit)}</b>　区间 ${fmtV(r.low, m.unit)} ~ ${fmtV(r.high, m.unit)}　置信 ${esc(r.confidence || "—")}</div>
    <div>模型</div><div>${esc(r.model)} · ${MODE_SHORT[r.mode] || r.mode} · ${r.latency ? r.latency.toFixed(1) + " 秒" : ""} · ${r.tokens || "—"} tokens · 研报 ${r.n_titles || 0} 篇</div>
    <div>结论</div><div>${esc(r.reason || "—")}</div>${r.error ? `<div>错误</div><div class="up">${esc(r.error)}</div>` : ""}</div>
    ${analysisHTML(r, m.unit).replace(/<p class="hint"[\s\S]*?<\/p>/, "")}
    <h3>Prompt</h3><pre>${esc(r.prompt || "—")}</pre><h3>模型原始输出</h3><pre>${esc(r.answer_raw || "—")}</pre>${r.thinking ? `<h3>思考过程</h3><pre>${esc(r.thinking)}</pre>` : ""}`);
}

/* ---------------- 预测中心 ---------------- */
function renderPredictControls() {
  fillSelect($("#pModel"), modelOpts(), (S.settings || {}).default_model || (S.status || {}).model);
  fillSelect($("#pMode"), MODES_ORDER.map(k => [k, S.meta.modes[k]]), "title");
  const inds = countryInds(["nowcast", "persist"]);
  $("#pInds").innerHTML = `<span class="chip grp">${COUNTRY_NAME[S.country]}</span>` + inds.map(i => `<span class="chip ${i.role === "nowcast" ? "on" : ""}" data-id="${i.id}">${esc(i.short)}</span>`).join("") +
    `<span class="chip" id="pAll">全选</span><span class="chip" id="pNone">清空</span>`;
  $$("#pInds .chip[data-id]").forEach(c => c.onclick = () => c.classList.toggle("on"));
  $("#pAll").onclick = () => $$("#pInds .chip[data-id]").forEach(c => c.classList.add("on"));
  $("#pNone").onclick = () => $$("#pInds .chip[data-id]").forEach(c => c.classList.remove("on"));
}
async function runSelected() {
  const ids = $$("#pInds .chip.on[data-id]").map(c => c.dataset.id); if (!ids.length) return;
  $("#pRun").disabled = true;
  try { const job = await api("/api/nowcast", { method: "POST", json: { indicators: ids, mode: $("#pMode").value, model: $("#pModel").value } }); trackJob(job.id, $("#pJob"), () => { $("#pRun").disabled = false; renderPredictResults(); loadOverview(); }); }
  catch (e) { $("#pRun").disabled = false; alertBox(e); }
}
async function updateAndPredict() {
  const btn = $("#pUpdate"); btn.disabled = true; const box = $("#pJob");
  box.innerHTML = `<div class="job">正在从数据源拉取最新数据并增量重算模型…<div class="bar"><i style="width:10%"></i></div></div>`;
  try { await api("/api/update_and_predict", { method: "POST", json: { mode: $("#pMode").value, model: $("#pModel").value, country: S.country } }); }
  catch (e) { btn.disabled = false; box.innerHTML = ""; alertBox(e); return; }
  let n = 0;
  const poll = async () => {
    let u; try { u = await api("/api/update_status"); } catch (e) { setTimeout(poll, 3000); return; } n++;
    if (u.error) { box.innerHTML = `<div class="job"><span class="err">更新失败：${esc(u.error)}</span></div>`; btn.disabled = false; return; }
    if (u.running || !u.job_id) { box.innerHTML = `<div class="job">${esc(u.stage)}（已用 ${n * 3} 秒）<div class="bar"><i style="width:${Math.round(5 + ((u.status || {}).ar_progress || 0) * 45)}%"></i></div></div>`; setTimeout(poll, 3000); return; }
    S.seriesCache = {}; await refreshStatus(); trackJob(u.job_id, box, () => { btn.disabled = false; renderPredictResults(); loadOverview(); });
  };
  setTimeout(poll, 2000);
}
async function renderPredictResults() {
  const rows = await api(`/api/runs?source=live&country=${S.country}&limit=200&ok=1`);
  const seen = new Set(), latest = [];
  for (const r of rows) { const k = r.indicator + r.target_month; if (seen.has(k)) continue; seen.add(k); latest.push(r); }
  $("#pResults").innerHTML = latest.length ? latest.map(r => { const m = ind(r.indicator); return `<div class="res"><div class="res-h"><span class="nm">${esc(m.name)} · ${monthLabel(r.target_month, m.freq)}</span><span class="val">${fmtV(r.value, m.unit)} <small>${esc(m.unit)}</small></span></div>
    <div class="sum">${esc(r.reason || "")}</div><details><summary>原理与支撑 · ${esc((r.created_at || "").slice(0, 16))} · ${esc(r.model)}</summary>${analysisHTML(r, m.unit)}</details></div>`; }).join("") : `<div class="skel">暂无当期研判，点击上方按钮运行。</div>`;
  bindRunLinks($("#pResults"));
}

/* ---------------- 数据库 ---------------- */
async function renderTable() {
  const n = $("#tblMonths").value, freq = $("#tblFreq").value;
  let t; try { t = await api(`/api/table?country=${S.country}&months=${n}&freq=${freq}`); } catch (e) { $("#dataTable").innerHTML = `<tr><td>${esc(e.message)}</td></tr>`; return; }
  const st = S.status || {}; $("#tblMeta").textContent = `· ${COUNTRY_NAME[S.country]} · 数据版本 ${st.loaded_at || ""}`;
  $("#tblSrc").textContent = `来源：${((st.data || {}).source || {})[S.country.toLowerCase()] || ""}`; $("#csvAll").href = `/api/data.csv?country=${S.country}`;
  const months = t.months;
  let h = `<tr><th>指标（单位）</th>${months.map(m => `<th>${freq === "Q" ? m.slice(2, 4) + "Q" + Math.ceil(+m.slice(5, 7) / 3) : m.slice(2).replace("-", "/")}</th>`).join("")}</tr>`;
  t.columns.forEach(c => { h += `<tr class="${c.role}"><td title="${esc(c.name)}">${esc(c.short)} <span class="lo">${esc(c.unit)}</span></td>` + c.values.map((v, i) => `<td class="${months[i] === c.latest_month ? "latest" : ""}">${v == null ? "" : fmtV(v, c.unit)}</td>`).join("") + "</tr>"; });
  $("#dataTable").innerHTML = h || `<tr><td class="skel">暂无数据</td></tr>`; const wrap = $("#dataTable").parentElement; wrap.scrollLeft = wrap.scrollWidth;
}
async function renderSeries() {
  const id = $("#serInd").value; if (!id) return; const m = ind(id), from = $("#serFrom").value || "2010-01";
  const ser = await getSeries(id); const months = ser.months.filter(x => x >= from);
  const act = Object.fromEntries(ser.months.map((x, i) => [x, ser.values[i]]));
  lineChart($("#serChart"), { months, series: [{ name: m.short, color: "#14202e", data: act, width: 2 }], unit: m.unit, clip: false });
  const d = ser.diag || {};
  $("#serDiag").innerHTML = `<span>最新 <b>${monthLabel(ser.months[ser.months.length - 1], m.freq)} ${fmtV(ser.values[ser.values.length - 1], m.unit)} ${esc(m.unit)}</b></span><span>样本 <b>${ser.months.length}</b> 期（${ser.months[0]} 起）</span>
    ${d.adf_p != null ? `<span>ADF p = <b>${d.adf_p.toFixed(3)}</b>${d.adf_p < 0.05 ? "（平稳）" : "（非平稳）"}</span><span>SARIMAX <b>${esc(d.final_order || "")}</b></span>` : ""}<span>${esc(m.release)}</span>`;
  $("#serNotes").textContent = (ser.notes || []).join("；");
}

/* ---------------- 研报 ---------------- */
async function renderReports() {
  const id = $("#repInd").value, month = $("#repMonth").value, mode = $("#repMode").value; if (!month || !id) return;
  $("#repOut").innerHTML = `<div class="skel">正在召回 ${monthLabel(month)} 研报…</div>`;
  try {
    const d = await api(`/api/reports?indicator=${id}&month=${month}&mode=${mode}`); const info = d.info;
    let html = `<p class="muted">当月宏观 + 策略研报共 <b>${info.n_all}</b> 篇；按「${esc(ind(id).keywords.join("、"))}${(d.rules.include || []).length ? "、" + esc(d.rules.include.join("、")) : ""}」召回并去重后 <b>${info.n_titles}</b> 条${info.supplemented ? `（命中不足，补充 ${info.supplemented} 条）` : ""}。</p>`;
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
  const modes = MODES_ORDER;
  let h = `<tr><th>指标</th><th>沿用上期</th><th>SARIMAX</th>${modes.map(m => `<th>${MODE_SHORT[m]}</th>`).join("")}<th>阶数</th><th>推荐</th></tr>`;
  rows.forEach(r => {
    const vals = [r.persist && r.persist.corr, r.ar && r.ar.corr, ...modes.map(m => r.llm[m] && r.llm[m].corr)]; const mx = Math.max(...vals.filter(v => v != null));
    const cell = (v, n) => `<td class="${v != null && v === mx ? "hi" : v == null ? "lo" : ""}">${fmtC(v)}${n ? `<span class="pp">n=${n}</span>` : ""}</td>`;
    h += `<tr class="${r.role === "persist" ? "persist-row" : ""}"><td>${esc(r.name)}${r.spring ? ' <span class="tag llm">春节</span>' : ""}</td>${cell(r.persist.corr)}${cell(r.ar && r.ar.corr)}${modes.map(m => cell(r.llm[m] && r.llm[m].corr, r.llm[m] && r.llm[m].n)).join("")}<td>${esc(r.order || "")}</td><td title="${esc(r.why)}"><span class="tag ${r.recommend}">${REC_NAME[r.recommend]}</span></td></tr>`;
  });
  $("#btTable").innerHTML = h; renderBtChart();
}
async function renderBtChart() {
  const id = $("#btInd").value; if (!id) return; const m = ind(id); const ser = await getSeries(id, true);
  const from = $("#btFrom").value || "2014-01", to = $("#btTo").value || "9999"; const months = ser.months.filter(x => x >= from && x <= to);
  const act = Object.fromEntries(ser.months.map((x, i) => [x, ser.values[i]])); const colors = { title: "#a8322a", chunk: "#a8832f", title_ar: "#5a4a9c", data: "#2f7d4f" };
  const series = [{ name: "真实值", color: "#14202e", data: act, width: 2.2 }, { name: "沿用上期", color: "#9aa3ad", data: ser.persist, dash: "4 3" }, { name: "SARIMAX", color: "#1d6b73", data: ser.ar }];
  Object.keys(ser.llm).forEach(k => series.push({ name: MODE_SHORT[k], color: colors[k], data: ser.llm[k], dots: true }));
  $("#btLegend").innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
  lineChart($("#btChart"), { months, series, unit: m.unit, clip: true, height: 340 });
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
  $("#leakOut").innerHTML = `<div class="tbl-wrap"><table><tr><th>区间</th><th>月数</th><th>AI 相关性</th><th>AI 平均绝对误差</th><th>沿用上期相关性</th></tr>${row(`${d.split} 之前`, d.before, d.persist_before)}${row(`${d.split} 及之后`, d.after, d.persist_after)}</table></div>`;
}

/* ---------------- 档案 ---------------- */
async function renderArchive() {
  const q = new URLSearchParams({ indicator: $("#arcInd").value, source: $("#arcSrc").value, limit: 500, ok: $("#arcOk").checked ? "1" : "0" });
  const rows = await api("/api/runs?" + q); $("#arcCsv").href = "/api/runs.csv?indicator=" + $("#arcInd").value; $("#arcMeta").textContent = `· ${rows.length} 条`;
  $("#arcTable").innerHTML = `<tr><th>#</th><th>时间</th><th>类型</th><th>指标</th><th>目标月</th><th>预测</th><th>区间</th><th>置信</th><th>模型</th><th>结论</th></tr>` +
    (rows.length ? rows.map(r => { const m = ind(r.indicator); return `<tr><td>${r.id}</td><td>${esc((r.created_at || "").slice(0, 16))}</td><td>${r.source === "live" ? "实时" : "回测"}</td><td>${esc(m.short)}</td><td>${r.target_month}</td><td><b>${fmtV(r.value, m.unit)}</b></td><td>${r.low != null ? fmtV(r.low, m.unit) + "~" + fmtV(r.high, m.unit) : ""}</td><td>${esc(r.confidence || "")}</td><td>${esc(r.model)}</td><td class="r">${esc((r.reason || r.error || "").slice(0, 120))} <a href="#" data-run-id="${r.id}">详情</a></td></tr>`; }).join("") : `<tr><td colspan="10" class="skel">暂无记录</td></tr>`);
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
async function loadSettings() { try { S.settings = await api("/api/settings"); } catch (e) { S.settings = {}; } }
function renderSettings() {
  const s = S.settings || {}, st = S.status || {}, d = st.data || {}, src = d.source || {};
  $("#sReq").value = s.predict_requirements || ""; fillSelect($("#sModel"), modelOpts(), s.default_model || st.model); $("#sAuto").checked = !!s.auto_predict; $("#pwd").value = pwd();
  $("#srcInfo").innerHTML = `
    <div class="src-card"><h3>大模型</h3>${(st.models || []).map(m => `<div>● ${esc(m.label)}</div>`).join("") || "<div class='up'>未配置任何模型密钥</div>"}<div class="hint">DeepSeek：DEEPSEEK_API_KEY；Claude：ANTHROPIC_API_KEY（自动发现 Opus/Sonnet 型号）</div></div>
    <div class="src-card"><h3>中国数据</h3><div>${esc(src.cn || "—")}</div><div class="hint">国家统计局 / 海关总署 / 央行口径，经东方财富数据中心；每 ${st.refresh_hours} 小时轮询</div>${d.ifind ? `<div>iFinD EDB：${d.ifind.enabled ? `${d.ifind.loaded}/${d.ifind.mapped} 项${d.ifind.token_expires ? "，token 至 " + esc(d.ifind.token_expires.slice(0, 10)) : ""}${d.ifind.last_error ? "，异常：" + esc(d.ifind.last_error.slice(0, 80)) : ""}` : "未配置（IFIND_REFRESH_TOKEN + IFIND_EDB_MAP）"}</div>` : ""}</div>
    <div class="src-card"><h3>美国数据</h3><div>${esc(src.us || "—")}</div><div class="hint">FRED（美联储圣路易斯分行）为主，东方财富·美国宏观（官方口径转载，2008 年起）为备源；CPI/PCE/非农/失业率/零售/ISM/地产/利率等 25 项</div></div>
    <div class="src-card"><h3>研报</h3><div>东方财富研报中心（宏观研究 + 策略报告），按指标关键词 + 自定义规则召回</div></div>
    ${(d.errors || []).length ? `<div class="src-card"><h3>最近抓取异常</h3>${d.errors.slice(0, 6).map(e => `<div class="up">${esc(e)}</div>`).join("")}</div>` : ""}`;
}
async function saveSettings() {
  try { S.settings = await api("/api/settings", { method: "POST", json: { predict_requirements: $("#sReq").value, default_model: $("#sModel").value, auto_predict: $("#sAuto").checked } }); $("#sMsg").textContent = "✓ 已保存"; }
  catch (e) { $("#sMsg").textContent = "✗ " + e.message; }
}
async function savePwd() { try { localStorage.setItem("nowcast_pwd", $("#pwd").value); } catch (e) { } try { await api("/api/auth/check", { method: "POST", json: {} }); $("#pwdMsg").textContent = "✓ 口令有效"; } catch (e) { $("#pwdMsg").textContent = "✗ " + e.message; } }
async function doRefresh() { try { await api("/api/refresh", { method: "POST", json: {} }); $("#tblSrc").textContent = "已开始重新抓取，约 1 分钟后自动更新…"; S.seriesCache = {}; setTimeout(() => { refreshStatus(); if (S.view === "data") { renderTable(); renderSeries(); } if (S.view === "overview") loadOverview(); }, 20000); } catch (e) { alertBox(e); } }
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
  fillSelect($("#serInd"), all.map(i => [i.id, i.short])); fillSelect($("#repInd"), modeled.map(i => [i.id, i.short])); fillSelect($("#btInd"), modeled.map(i => [i.id, i.short])); fillSelect($("#leakInd"), modeled.map(i => [i.id, i.short]));
  fillSelect($("#ovInd"), all.map(i => [i.id, i.short]));
  $("#arcInd").innerHTML = `<option value="">全部</option>` + S.meta.indicators.map(i => `<option value="${i.id}">${esc(COUNTRY_NAME[i.country])} · ${esc(i.short)}</option>`).join("");
  $("#llmInds").innerHTML = modeled.map(i => `<span class="chip ${i.role === "nowcast" ? "on" : ""}" data-id="${i.id}">${esc(i.short)}</span>`).join("");
  $$("#llmInds .chip").forEach(c => c.onclick = () => c.classList.toggle("on"));
  renderPredictControls();
}
function show(v) {
  if (!VIEW_TITLE[v]) v = "overview"; S.view = v;
  $$(".view").forEach(s => s.hidden = s.id !== "v-" + v); $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.v === v)); $("#viewTitle").textContent = VIEW_TITLE[v];
  $("#countrySeg").style.visibility = ["ask", "settings", "archive"].includes(v) ? "hidden" : "visible";
  if (!S.meta) return;
  if (v === "overview") loadOverview();
  if (v === "predict") renderPredictResults();
  if (v === "data") { renderTable(); renderSeries(); }
  if (v === "reports") { fillRules(); renderReports(); }
  if (v === "backtest") renderBacktest();
  if (v === "archive") renderArchive();
  if (v === "ask") { fillSelect($("#askModel"), modelOpts(), (S.settings || {}).default_model || S.status.model); setTimeout(() => $("#askInput").focus(), 50); }
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
  fillCountrySelects();
  $("#pUpdate").onclick = updateAndPredict; $("#pRun").onclick = runSelected;
  $("#tblMonths").onchange = renderTable; $("#tblFreq").onchange = renderTable; $("#refreshData").onclick = doRefresh; $("#serInd").onchange = renderSeries; $("#serFrom").onchange = renderSeries;
  $("#repGo").onclick = renderReports; $("#rSave").onclick = saveRules;
  $("#btGo").onclick = renderBacktest; $("#btInd").onchange = renderBtChart; $("#llmGo").onclick = runLlmBacktest; $("#leakGo").onclick = runLeak;
  $("#arcGo").onclick = renderArchive; $("#arcInd").onchange = renderArchive; $("#arcSrc").onchange = renderArchive; $("#arcOk").onchange = renderArchive;
  $("#askSend").onclick = askSend; $("#askClear").onclick = () => { S.chat = []; $("#chatBox").innerHTML = ""; }; $("#askInput").addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); askSend(); } });
  $("#sSave").onclick = saveSettings; $("#pwdSave").onclick = savePwd; $("#ovUp").onclick = () => doOverride(false); $("#ovClear").onclick = () => doOverride(true);
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (S.view === "data") renderSeries(); if (S.view === "backtest") renderBtChart(); }, 200); });
  setInterval(refreshStatus, 20000);
  show(location.hash.slice(1) || "overview");
}
addEventListener("hashchange", () => show(location.hash.slice(1)));
init();
