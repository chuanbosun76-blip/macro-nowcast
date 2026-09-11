/* 观数 · 宏观实时预测研究台 前端（原生 JS，无外部依赖） */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const S = { meta: null, overview: null, view: "workbench", jobs: {}, seriesCache: {} };
const MODE_NAMES = { title: "仅当月研报标题", chunk: "仅当月研报正文片段", title_ar: "标题 + 自回归参考", chunk_ar: "正文片段 + 自回归参考" };
const MODE_SHORT = { title: "LLM标题", chunk: "LLM正文", title_ar: "标题+自回归", chunk_ar: "正文+自回归" };
const REC_NAME = { persist: "沿用上期", ar: "SARIMAX", llm: "DeepSeek" };
const VIEW_TITLE = { workbench: "预测工作台", reports: "数据与研报", backtest: "滚动回测", archive: "预测档案", ask: "问 AI", method: "方法与设置" };

function pwd() { try { return localStorage.getItem("nowcast_pwd") || ""; } catch (e) { return ""; } }
async function api(path, opts = {}) {
  const headers = Object.assign({ "X-Access-Password": pwd() }, opts.headers || {});
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  let j = null;
  try { j = await r.json(); } catch (e) { j = { error: `HTTP ${r.status}` }; }
  if (r.status === 401) promptPwd();
  if (!r.ok) { const err = new Error((j && j.error) || `HTTP ${r.status}`); err.status = r.status; err.body = j; throw err; }
  return j;
}
function promptPwd() {
  openModal(`<h2>需要访问口令</h2><p class="muted">运行 DeepSeek、刷新数据等会产生费用的操作需要站点口令（部署时设置的 ACCESS_PASSWORD）。口令只保存在本浏览器。</p>
    <div class="ctl-row"><input type="password" id="pwdModal" placeholder="输入访问口令" autofocus><button class="btn primary" id="pwdModalSave">保存并重试</button></div>`);
  const save = () => { try { localStorage.setItem("nowcast_pwd", $("#pwdModal").value); } catch (e) { } $("#modal").hidden = true; };
  $("#pwdModalSave").onclick = save; $("#pwdModal").addEventListener("keydown", ev => { if (ev.key === "Enter") save(); });
  setTimeout(() => $("#pwdModal").focus(), 50);
}
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function ind(id) { return S.meta.indicators.find(x => x.id === id); }
function fmtV(v, unit, sign) {
  if (v == null || !isFinite(v)) return "—";
  let s;
  if (unit === "亿元") s = Math.round(v).toLocaleString("zh-CN");
  else if (unit === "亿美元") s = (Math.round(v * 10) / 10).toLocaleString("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  else s = (Math.round(v * 100) / 100).toFixed(unit === "%" ? 1 : 2);
  if (sign && v > 0) s = "+" + s;
  return s;
}
function fmtC(v) { return v == null || !isFinite(v) ? "—" : v.toFixed(2); }
function monthLabel(m) { return m ? `${m.slice(0, 4)}年${+m.slice(5, 7)}月` : "—"; }
function toast(msg, el) { (el || $("#runHint")).textContent = msg; }

/* ------------------------------------------------------------------ 图表（SVG） */
function lineChart(el, cfg) {
  const W = Math.max(el.clientWidth || 800, 320), H = cfg.height || 320;
  const pad = { l: 58, r: 16, t: 14, b: 30 };
  const months = cfg.months;
  if (!months.length) { el.innerHTML = '<div class="skel">暂无数据</div>'; return; }
  const all = [];
  cfg.series.forEach(s => months.forEach(m => { const v = s.data[m]; if (v != null && isFinite(v)) all.push(v); }));
  let lo = Math.min(...all), hi = Math.max(...all);
  if (cfg.clip) { // 截尾极端值，避免 2021 年基数效应压扁曲线
    const srt = [...all].sort((a, b) => a - b); lo = srt[Math.floor(srt.length * 0.01)]; hi = srt[Math.ceil(srt.length * 0.99) - 1];
  }
  if (lo === hi) { lo -= 1; hi += 1; }
  const span = hi - lo; lo -= span * 0.06; hi += span * 0.06;
  const x = i => pad.l + (W - pad.l - pad.r) * (months.length === 1 ? 0.5 : i / (months.length - 1));
  const y = v => pad.t + (H - pad.t - pad.b) * (1 - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo));
  const ticks = niceTicks(lo, hi, 5);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(cfg.title || "")}">`;
  ticks.forEach(t => { svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}" stroke="#eeeae2"/><text x="${pad.l - 8}" y="${y(t) + 4}" font-size="11" text-anchor="end" fill="#7b8591">${fmtTick(t, cfg.unit)}</text>`; });
  if (lo < 0 && hi > 0) svg += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(0)}" y2="${y(0)}" stroke="#b9b2a4" stroke-dasharray="3 3"/>`;
  const step = Math.max(1, Math.ceil(months.length / Math.floor((W - pad.l) / 70)));
  months.forEach((m, i) => { if (i % step === 0) svg += `<text x="${x(i)}" y="${H - 8}" font-size="11" text-anchor="middle" fill="#7b8591">${m.slice(2).replace("-", "/")}</text>`; });
  if (cfg.shadeFrom) { const i0 = months.indexOf(cfg.shadeFrom); if (i0 >= 0) svg += `<rect x="${x(i0)}" y="${pad.t}" width="${W - pad.r - x(i0)}" height="${H - pad.t - pad.b}" fill="#a8322a" opacity=".05"/>`; }
  cfg.series.forEach(s => {
    let d = "", pen = false;
    months.forEach((m, i) => { const v = s.data[m]; if (v == null || !isFinite(v)) { pen = false; return; } d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); pen = true; });
    svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 1.6}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round"/>`;
    if (s.dots) months.forEach((m, i) => { const v = s.data[m]; if (v != null && isFinite(v)) svg += `<circle cx="${x(i)}" cy="${y(v)}" r="2.6" fill="${s.color}"/>`; });
  });
  svg += `<line id="hx" x1="0" x2="0" y1="${pad.t}" y2="${H - pad.b}" stroke="#14202e" stroke-width=".6" opacity="0"/>`;
  svg += `<rect x="${pad.l}" y="${pad.t}" width="${W - pad.l - pad.r}" height="${H - pad.t - pad.b}" fill="transparent" class="hov"/></svg>`;
  el.innerHTML = svg;
  const rect = $(".hov", el), hx = $("#hx", el), tip = $("#tip");
  rect.addEventListener("mousemove", ev => {
    const bb = el.querySelector("svg").getBoundingClientRect();
    const px = (ev.clientX - bb.left) * (W / bb.width);
    const i = Math.round((px - pad.l) / (W - pad.l - pad.r) * (months.length - 1));
    if (i < 0 || i >= months.length) return;
    hx.setAttribute("x1", x(i)); hx.setAttribute("x2", x(i)); hx.setAttribute("opacity", 1);
    const m = months[i];
    tip.innerHTML = `<b>${monthLabel(m)}</b><br>` + cfg.series.map(s => `<span style="color:${s.color === "#14202e" ? "#fff" : s.color}">■</span> ${esc(s.name)}：${fmtV(s.data[m], cfg.unit)}`).join("<br>");
    tip.hidden = false; tip.style.left = Math.min(ev.clientX + 14, innerWidth - 270) + "px"; tip.style.top = (ev.clientY + 14) + "px";
  });
  rect.addEventListener("mouseleave", () => { tip.hidden = true; hx.setAttribute("opacity", 0); });
}
function niceTicks(lo, hi, n) {
  const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
  const out = []; for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(+t.toFixed(10));
  return out;
}
function fmtTick(t, unit) { if (unit === "亿元" || unit === "亿美元") return Math.abs(t) >= 10000 ? (t / 10000).toFixed(1) + "万" : Math.round(t).toString(); return (+t.toFixed(2)).toString(); }
function spark(values) {
  const v = values.slice(-24), W = 120, H = 34, lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
  const d = v.map((a, i) => (i ? "L" : "M") + (i / (v.length - 1) * W).toFixed(1) + " " + (H - 3 - (a - lo) / r * (H - 6)).toFixed(1)).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><path d="${d}" fill="none" stroke="#44505e" stroke-width="1.3"/></svg>`;
}

/* ------------------------------------------------------------------ 状态栏 */
async function refreshStatus() {
  try {
    const st = await api("/api/status");
    const prevVer = S.status && S.status.version;
    S.status = st;
    if (st.ready && prevVer && st.version && st.version !== prevVer) { // 数据源有新数据：自动刷新页面内容
      S.seriesCache = {}; S.overview = null;
      show(S.view);
      $("#topMeta").insertAdjacentHTML("afterbegin", `<span class="up">● 数据已更新（${esc(st.loaded_at)}）</span><br>`);
    }
    const prog = Object.values(st.ar_progress || {});
    const arDone = prog.length ? prog.reduce((a, b) => a + b, 0) / (S.meta ? S.meta.indicators.length : 10) : 0;
    const dot = st.error ? "bad" : (st.ready ? "ok" : "warn");
    $("#sideStatus").innerHTML = `<div><span class="dot ${dot}"></span>${st.ready ? "模型就绪" : st.loading ? `自回归计算中 ${Math.round(arDone * 100)}%` : "等待加载"}</div>
      <div>数据：${esc((st.data || {}).source || "—")}</div><div>数据版本：${esc(st.loaded_at || "—")}</div><div>上次检查：${esc(st.last_check || "—")} · 每 ${st.refresh_hours} 小时</div>
      <div><span class="dot ${st.has_key ? "ok" : "bad"}"></span>DeepSeek：${st.has_key ? esc(st.model) : "未配置密钥"}</div>`;
    $("#topMeta").innerHTML = `回测区间 <b>${st.backtest_start}</b> 起 · 扩展窗口<br>LLM：<b>${esc(st.model)}</b>${st.auth_required ? " · 需口令" : ""}`;
    if (st.data && st.data.errors && st.data.errors.length) $("#topMeta").innerHTML += `<br><span class="up">部分数据表抓取失败，已回退缓存</span>`;
    return st;
  } catch (e) { $("#sideStatus").innerHTML = `<span class="dot bad"></span>服务不可达`; return null; }
}

/* ------------------------------------------------------------------ 预测工作台 */
async function loadOverview() {
  try { S.overview = (await api("/api/overview")).rows; }
  catch (e) {
    if (e.status === 503) { $("#cardsNow").innerHTML = `<div class="skel">数据加载与自回归计算中（首次约 30–60 秒）…</div>`; setTimeout(loadOverview, 3000); return; }
    $("#cardsNow").innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; return;
  }
  renderCards();
}
function renderCards() {
  const rows = S.overview || [];
  const now = rows.filter(r => r.role === "nowcast"), per = rows.filter(r => r.role === "persist");
  $("#cardsNow").innerHTML = now.map(cardHTML).join("");
  $("#cardsPersist").innerHTML = per.map(cardHTML).join("");
  $$(".card [data-run]").forEach(b => b.onclick = () => runNowcast([b.dataset.run], b));
  $$(".card [data-detail]").forEach(b => b.onclick = () => showDetail(b.dataset.detail));
}
function cardHTML(r) {
  const s = S.seriesCache[r.id];
  const chg = r.prev_value != null ? r.last_value - r.prev_value : null;
  const llm = (r.llm_latest || [])[0];
  const best = r.recommend;
  const pc = r.persist_corr, ac = r.ar_corr, lc = r.llm_corr && r.llm_corr.title;
  const pred = (key, label, v, sub) => `<div class="pred ${best === key ? "best" : ""}"><span class="k">${label}</span><span class="x">${fmtV(v, r.unit)}</span><div class="s">${sub}</div></div>`;
  return `<article class="card rec-${best}">
    <div class="card-h"><div><div class="nm">${esc(r.name)}</div><div class="grp">${esc(r.group)} · ${esc(r.unit)} · ${esc(r.release)}</div></div><span class="tag ${best}">推荐：${REC_NAME[best] || "—"}</span></div>
    <div class="last"><span class="v">${fmtV(r.last_value, r.unit)}</span><span class="u">${esc(r.unit)} · ${monthLabel(r.last_month)}已公布</span>
      ${chg != null ? `<span class="chg ${chg > 0 ? "up" : chg < 0 ? "down" : ""}">${chg > 0 ? "▲" : chg < 0 ? "▼" : "—"} ${fmtV(Math.abs(chg), r.unit)}</span>` : ""}</div>
    <div class="pend">待发布：<b>${monthLabel(r.pending_month)}</b> · 当期实时预测</div>
    <div class="preds">
      ${pred("persist", "沿用上期", r.persist_pred, `回测相关 ${fmtC(pc)}`)}
      ${pred("ar", "SARIMAX", r.ar_pred, `${esc(r.ar_order || "")} · ${fmtC(ac)}`)}
      ${pred("llm", "DeepSeek", llm ? llm.value : null, llm ? `${MODE_SHORT[llm.mode]}${lc != null ? " · " + fmtC(lc) : ""}` : "待运行")}
    </div>
    <div class="why">${esc(r.why || "")}</div>
    ${llm && llm.reason ? `<div class="reason"><b>DeepSeek 理由</b>（${esc(llm.created_at)}，${llm.n_titles || 0} 条研报）：${esc(llm.reason)}</div>` : ""}
    <div class="card-f">
      <span class="hint">原文：沿用 ${r.paper ? fmtC(r.paper.persist) : "—"} · 自回归 ${r.paper ? fmtC(r.paper.ar) : "—"}${r.paper && r.paper.title != null ? " · LLM标题 " + fmtC(r.paper.title) : ""}</span>
      <span><button class="btn sm ghost" data-detail="${r.id}">走势与记录</button> <button class="btn sm" data-run="${r.id}">DeepSeek 预测</button></span>
    </div>
  </article>`;
}
async function runNowcast(ids, btn) {
  const mode = $("#modeSel").value, model = $("#modelSel").value;
  if (btn) btn.disabled = true;
  try {
    const job = await api("/api/nowcast", { method: "POST", json: { indicators: ids, mode, model } });
    trackJob(job.id, $("#jobBox"), () => { loadOverview(); if (btn) btn.disabled = false; });
  } catch (e) {
    if (btn) btn.disabled = false;
    $("#jobBox").innerHTML = `<div class="job"><span class="err">${esc(e.message)}${e.status === 401 ? " → 前往“方法与设置”输入口令" : ""}</span></div>`;
  }
}
async function updateAndPredict() {
  const btn = $("#updateAll"); btn.disabled = true;
  $("#jobBox").innerHTML = `<div class="job">正在从数据源拉取最新数据并重算 10 个指标的 SARIMAX 模型（约 30–60 秒）…<div class="bar"><i style="width:15%"></i></div></div>`;
  try {
    const job = await api("/api/update_and_predict", { method: "POST", json: { mode: $("#modeSel").value, model: $("#modelSel").value } });
    S.seriesCache = {}; await refreshStatus(); await loadOverview();
    const st = job.status_after || {};
    $("#topMeta").insertAdjacentHTML("afterbegin", `<span class="up">● 数据已更新至 ${esc((st.data || {}).fetched_at || "")}</span><br>`);
    trackJob(job.id, $("#jobBox"), () => { loadOverview(); btn.disabled = false; });
  } catch (e) {
    btn.disabled = false;
    $("#jobBox").innerHTML = `<div class="job"><span class="err">${esc(e.message)}${e.status === 401 ? " → 前往“方法与设置”输入口令" : ""}</span></div>`;
  }
}
function trackJob(id, box, onDone) {
  const tick = async () => {
    let j; try { j = await api(`/api/jobs/${id}`); } catch (e) { return; }
    const pct = j.total ? Math.round(j.done / j.total * 100) : 100;
    let html = `<div class="job"><b>${esc(j.label)}</b> · ${esc(j.model)} · ${j.done}/${j.total} 完成（成功 ${j.ok}，失败 ${j.failed}${j.skipped ? `，跳过已有 ${j.skipped}` : ""}）${j.status === "done" ? " · 已结束" : " · 运行中…"}
      <div class="bar"><i style="width:${pct}%"></i></div>`;
    const res = (j.results || []).slice(-6).reverse();
    if (res.length) html += res.map(r => `<div>${esc(ind(r.indicator).short)} ${monthLabel(r.target_month)} ${MODE_SHORT[r.mode]}：<b>${r.value != null ? fmtV(r.value, ind(r.indicator).unit) : "—"}</b> ${r.reason ? `<span class="muted">${esc(r.reason.slice(0, 80))}</span>` : ""}</div>`).join("");
    if (j.errors && j.errors.length) html += `<div class="err">${j.errors.slice(-3).map(esc).join("<br>")}</div>`;
    box.innerHTML = html + "</div>";
    if (j.status !== "done") setTimeout(tick, 2500); else onDone && onDone(j);
  };
  tick();
}
async function showDetail(id) {
  const r = S.overview.find(x => x.id === id), m = ind(id);
  openModal(`<h2>${esc(r.name)}</h2><div class="legend" id="dLegend"></div><div class="chart" id="dChart"></div><div id="dRuns" class="skel">加载中…</div>`);
  const [ser, runs] = await Promise.all([getSeries(id), api(`/api/runs?indicator=${id}&limit=30`)]);
  const from = "2021-01", months = ser.months.filter(x => x >= from).concat([ser.pending_month]);
  const act = Object.fromEntries(ser.months.map((x, i) => [x, ser.values[i]]));
  const series = [{ name: "真实值", color: "#14202e", data: act, width: 2.2 }, { name: "沿用上期", color: "#9aa3ad", data: ser.persist, dash: "4 3" },
    { name: "SARIMAX", color: "#1d6b73", data: Object.assign({}, ser.ar, { [ser.pending_month]: ser.ar_nowcast }) }];
  if (ser.llm.title) series.push({ name: "DeepSeek 标题", color: "#a8322a", data: ser.llm.title, dots: true });
  const live = runs.filter(x => x.target_month === ser.pending_month && x.value != null);
  if (live.length) series.push({ name: "DeepSeek 当期", color: "#a8832f", data: { [ser.pending_month]: live[0].value }, dots: true });
  $("#dLegend").innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
  lineChart($("#dChart"), { months, series, unit: m.unit, shadeFrom: ser.pending_month, clip: true });
  $("#dRuns").className = "";
  $("#dRuns").innerHTML = `<h3>DeepSeek 记录</h3>` + (runs.length ? `<div class="tbl-wrap"><table class="arc"><tr><th>时间</th><th>目标月</th><th>输入</th><th>预测</th><th>真实</th><th>理由</th></tr>` +
    runs.map(x => `<tr><td>${esc(x.created_at)}</td><td>${x.target_month}</td><td>${MODE_SHORT[x.mode]}</td><td>${fmtV(x.value, m.unit)}</td><td>${fmtV(act[x.target_month], m.unit)}</td><td class="r">${esc(x.reason || x.error || "")} <a href="#" data-run-id="${x.id}">详情</a></td></tr>`).join("") + `</table></div>` : `<p class="muted">暂无记录，点击卡片上的“DeepSeek 预测”。</p>`);
  $$("[data-run-id]", $("#dRuns")).forEach(a => a.onclick = ev => { ev.preventDefault(); showRun(a.dataset.runId); });
}
async function getSeries(id, force) {
  if (!force && S.seriesCache[id] && Date.now() - S.seriesCache[id]._t < 30000) return S.seriesCache[id];
  const d = await api(`/api/series/${id}`); d._t = Date.now(); S.seriesCache[id] = d; return d;
}

/* ------------------------------------------------------------------ 数据与研报 */
async function renderTable() {
  const n = $("#tblMonths").value;
  let t; try { t = await api(`/api/table?months=${n}`); } catch (e) { $("#dataTable").innerHTML = `<tr><td>${esc(e.message)}</td></tr>`; return; }
  const st = S.status || {};
  $("#tblMeta").textContent = `· ${(st.data || {}).source || ""} · 数据版本 ${st.loaded_at || ""}`;
  const months = t.months;
  let h = `<tr><th>指标（单位）</th>${months.map(m => `<th>${m.slice(2).replace("-", "/")}</th>`).join("")}</tr>`;
  t.columns.forEach(c => {
    h += `<tr class="${c.role}"><td title="${esc(c.name)}">${esc(c.short)} <span class="lo">${esc(c.unit)}</span></td>` +
      c.values.map((v, i) => `<td class="${months[i] === c.latest_month ? "latest" : ""}">${v == null ? "" : fmtV(v, c.unit)}</td>`).join("") + "</tr>";
  });
  $("#dataTable").innerHTML = h;
  const wrap = $("#dataTable").parentElement; wrap.scrollLeft = wrap.scrollWidth;
}
async function renderSeries() {
  const id = $("#serInd").value, m = ind(id), from = $("#serFrom").value || "2014-01";
  const ser = await getSeries(id);
  const months = ser.months.filter(x => x >= from);
  const act = Object.fromEntries(ser.months.map((x, i) => [x, ser.values[i]]));
  lineChart($("#serChart"), { months, series: [{ name: m.short, color: "#14202e", data: act, width: 2 }], unit: m.unit, clip: false });
  const d = ser.diag || {};
  $("#serDiag").innerHTML = `<span>最新：<b>${monthLabel(ser.months[ser.months.length - 1])} ${fmtV(ser.values[ser.values.length - 1], m.unit)} ${m.unit}</b></span>
    <span>ADF（原序列）p = <b>${d.adf_p != null ? d.adf_p.toFixed(3) : "—"}</b>${d.adf_p != null ? (d.adf_p < 0.05 ? "（平稳）" : "（非平稳）") : ""}</span>
    <span>Ljung-Box（原序列，12 阶）p = <b>${d.lb_raw_p != null ? d.lb_raw_p.toExponential(1) : "—"}</b></span>
    <span>SARIMAX 当前阶数 <b>${esc(d.final_order || "—")}</b></span>
    <span>残差 Ljung-Box p = <b>${d.lb_resid_p != null ? d.lb_resid_p.toFixed(3) : "—"}</b></span>
    <span>来源：东方财富数据中心 · ${esc(m.release)}</span>`;
  const o = (S.overview || []).find(x => x.id === id);
  $("#serNotes").textContent = o && o.notes && o.notes.length ? o.notes.join("；") : "";
}
async function renderReports() {
  const id = $("#repInd").value, month = $("#repMonth").value, mode = $("#repMode").value;
  if (!month) return;
  $("#repOut").innerHTML = `<div class="skel">正在从东方财富研报中心召回 ${monthLabel(month)} 研报…（首次抓取约 5–20 秒）</div>`;
  try {
    const d = await api(`/api/reports?indicator=${id}&month=${month}&mode=${mode}`);
    const info = d.info;
    let html = `<p class="muted">当月宏观+策略研报共 <b>${info.n_all}</b> 篇；按“${esc(ind(id).keywords.join("、"))}”召回并去重后 <b>${info.n_titles}</b> 条${info.supplemented ? `（命中不足，补充当月宏观标题 ${info.supplemented} 条）` : ""}。</p>`;
    if (mode.startsWith("chunk")) {
      html += `<h3>正文片段（${info.chunks.length} 段，过滤来源/表头/重复 ${info.dropped} 段）</h3>` + (info.chunks.length ? info.chunks.map(c => `<div class="chunk">${esc(c)}</div>`).join("") : `<p class="muted">未取得正文片段</p>`);
    }
    html += `<h3>召回标题</h3><ol>` + d.titles.map(t => `<li>${esc(t.title)} <span class="org">${esc(t.org)} · ${t.date}</span></li>`).join("") + "</ol>";
    $("#repOut").innerHTML = html;
  } catch (e) { $("#repOut").innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; }
}

/* ------------------------------------------------------------------ 回测 */
async function renderBacktest() {
  const q = new URLSearchParams({ start: $("#btFrom").value || "", end: $("#btTo").value || "", model: $("#btModel").value });
  $("#btTable").innerHTML = `<tr><td class="skel">计算中…</td></tr>`;
  let rows; try { rows = (await api("/api/backtest?" + q)).rows; } catch (e) { $("#btTable").innerHTML = `<tr><td>${esc(e.message)}</td></tr>`; return; }
  const modes = ["title", "chunk", "title_ar", "chunk_ar"];
  let h = `<tr><th>指标</th><th>沿用上期</th><th>自回归（SARIMAX）</th>${modes.map(m => `<th>${MODE_SHORT[m]}</th>`).join("")}<th>阶数</th><th>ADF p</th><th>推荐</th></tr>`;
  rows.forEach(r => {
    const vals = [r.persist && r.persist.corr, r.ar && r.ar.corr, ...modes.map(m => r.llm[m] && r.llm[m].corr)];
    const mx = Math.max(...vals.filter(v => v != null));
    const cell = (v, pp, n) => `<td class="${v != null && v === mx ? "hi" : v == null ? "lo" : ""}">${fmtC(v)}${n ? `<span class="pp">n=${n}</span>` : ""}${pp != null ? `<span class="pp">原文 ${fmtC(pp)}</span>` : ""}</td>`;
    const P = r.paper || {};
    h += `<tr class="${r.role === "persist" ? "persist-row" : ""}"><td>${esc(r.name)}${r.spring ? ' <span class="tag llm" title="春节调整">春节</span>' : ""}</td>
      ${cell(r.persist.corr, P.persist)}${cell(r.ar && r.ar.corr, P.ar)}
      ${modes.map(m => cell(r.llm[m] && r.llm[m].corr, P[m], r.llm[m] && r.llm[m].n)).join("")}
      <td>${esc(r.order || "")}</td><td>${r.adf_p != null ? r.adf_p.toFixed(3) : "—"}</td><td title="${esc(r.why)}"><span class="tag ${r.recommend}">${REC_NAME[r.recommend]}</span></td></tr>`;
  });
  $("#btTable").innerHTML = h;
  renderBtChart();
}
async function renderBtChart() {
  const id = $("#btInd").value, m = ind(id);
  const ser = await getSeries(id, true);
  const from = $("#btFrom").value || "2014-01", to = $("#btTo").value || "9999";
  const months = ser.months.filter(x => x >= from && x <= to);
  const act = Object.fromEntries(ser.months.map((x, i) => [x, ser.values[i]]));
  const colors = { title: "#a8322a", chunk: "#a8832f", title_ar: "#5a4a9c", chunk_ar: "#2f7d4f" };
  const series = [{ name: "真实值", color: "#14202e", data: act, width: 2.2 }, { name: "沿用上期", color: "#9aa3ad", data: ser.persist, dash: "4 3" }, { name: "SARIMAX", color: "#1d6b73", data: ser.ar }];
  Object.keys(ser.llm).forEach(k => series.push({ name: "DeepSeek·" + MODE_SHORT[k], color: colors[k], data: ser.llm[k], dots: true }));
  $("#btLegend").innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
  lineChart($("#btChart"), { months, series, unit: m.unit, clip: true, height: 340 });
}
async function runLlmBacktest() {
  const modes = $$("#llmModes input:checked").map(x => x.value);
  if (!modes.length) return;
  $("#llmGo").disabled = true;
  try {
    const job = await api("/api/backtest/llm", { method: "POST", json: { indicator: $("#llmInd").value, modes, start: $("#llmFrom").value, end: $("#llmTo").value || "9999-12", model: $("#llmModel").value } });
    trackJob(job.id, $("#llmJob"), () => { $("#llmGo").disabled = false; renderBacktest(); });
  } catch (e) { $("#llmGo").disabled = false; $("#llmJob").innerHTML = `<div class="job"><span class="err">${esc(e.message)}</span></div>`; }
}
async function runLeak() {
  const id = $("#leakInd").value, split = $("#leakSplit").value;
  const d = await api(`/api/leak/${id}?split=${split}&mode=title`);
  const row = (k, a, b) => `<tr><td>${k}</td><td>${a.n}</td><td>${fmtC(a.corr)}</td><td>${a.mae != null ? fmtV(a.mae, ind(id).unit) : "—"}</td><td>${fmtC(b.corr)}</td></tr>`;
  $("#leakOut").innerHTML = `<div class="tbl-wrap"><table><tr><th>区间</th><th>月数</th><th>LLM 标题相关性</th><th>LLM 平均绝对误差</th><th>沿用上期相关性</th></tr>
    ${row(`${d.split} 之前`, d.before, d.persist_before)}${row(`${d.split} 及之后`, d.after, d.persist_after)}</table></div>
    <p class="hint">若切分后表现与切分前无系统性下降，说明回测受预训练“记住未来”的影响有限（原文结论）。样本需先在“文本回测”中跑出。</p>`;
}

/* ------------------------------------------------------------------ 档案 */
async function renderArchive() {
  const q = new URLSearchParams({ indicator: $("#arcInd").value, source: $("#arcSrc").value, limit: 400 });
  const rows = await api("/api/runs?" + q);
  $("#arcCsv").href = "/api/runs.csv?indicator=" + $("#arcInd").value;
  $("#arcTable").innerHTML = `<tr><th>#</th><th>时间</th><th>类型</th><th>指标</th><th>目标月</th><th>输入</th><th>模型</th><th>预测</th><th>研报数</th><th>理由 / 错误</th></tr>` +
    (rows.length ? rows.map(r => `<tr><td>${r.id}</td><td>${esc(r.created_at)}</td><td>${r.source === "live" ? "实时" : "回测"}</td><td>${esc(ind(r.indicator).short)}</td><td>${r.target_month}</td><td>${MODE_SHORT[r.mode]}</td><td>${esc(r.model)}</td><td><b>${fmtV(r.value, ind(r.indicator).unit)}</b></td><td>${r.n_titles || 0}</td><td class="r">${esc((r.reason || r.error || "").slice(0, 140))} <a href="#" data-run-id="${r.id}">详情</a></td></tr>`).join("")
      : `<tr><td colspan="10" class="skel">暂无记录</td></tr>`);
  $$("[data-run-id]", $("#arcTable")).forEach(a => a.onclick = ev => { ev.preventDefault(); showRun(a.dataset.runId); });
}
async function showRun(id) {
  const r = await api(`/api/runs/${id}`), m = ind(r.indicator);
  openModal(`<h2>预测详情 #${r.id}</h2><div class="kv">
    <div>指标</div><div>${esc(m.name)}</div><div>目标月</div><div>${monthLabel(r.target_month)}（信息截至 ${esc(r.cutoff)}）</div>
    <div>输入</div><div>${MODE_NAMES[r.mode]} · ${r.n_titles || 0} 条标题${r.n_chunks ? ` · ${r.n_chunks} 段正文` : ""}</div>
    <div>模型</div><div>${esc(r.model)} · ${r.latency ? r.latency.toFixed(1) + " 秒" : ""} · ${r.tokens || "—"} tokens</div>
    <div>预测值</div><div><b>${fmtV(r.value, m.unit)} ${esc(m.unit)}</b>${r.ar_ref != null ? `（自回归参考 ${fmtV(r.ar_ref, m.unit)}）` : ""}</div>
    <div>理由</div><div>${esc(r.reason || "—")}</div>${r.error ? `<div>错误</div><div class="up">${esc(r.error)}</div>` : ""}</div>
    <h3>思考过程</h3><pre>${esc(r.thinking || "—")}</pre><h3>完整 Prompt</h3><pre>${esc(r.prompt || "—")}</pre>`);
}
function openModal(html) { $("#modalBody").innerHTML = html; $("#modal").hidden = false; }
$("#modalX").onclick = () => { $("#modal").hidden = true; };
$("#modal").onclick = ev => { if (ev.target.id === "modal") $("#modal").hidden = true; };
document.addEventListener("keydown", ev => { if (ev.key === "Escape") $("#modal").hidden = true; });

/* ------------------------------------------------------------------ 问 AI */
S.chat = [];
function mdLite(t) { return esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/^#{1,4}\s*(.+)$/gm, "<b>$1</b>").replace(/^\s*[-•]\s+/gm, "· "); }
function addMsg(role, text, meta) {
  const d = document.createElement("div"); d.className = "msg " + role;
  d.innerHTML = role === "ai" ? mdLite(text) + (meta ? `<span class="meta">${esc(meta)}</span>` : "") : esc(text);
  $("#chatBox").appendChild(d); $("#chatBox").scrollTop = 1e9; return d;
}
async function askSend() {
  const q = $("#askInput").value.trim(); if (!q) return;
  $("#askInput").value = ""; addMsg("user", q); S.chat.push({ role: "user", content: q });
  const wait = addMsg("ai think", "思考中…（推理模型约 10–40 秒）");
  $("#askSend").disabled = true;
  try {
    const r = await api("/api/ask", { method: "POST", json: { messages: S.chat, model: $("#askModel").value } });
    wait.remove(); addMsg("ai", r.content, `${r.model} · ${r.latency ? r.latency.toFixed(1) + " 秒" : ""} · ${r.tokens || "—"} tokens`);
    S.chat.push({ role: "assistant", content: r.content });
  } catch (e) { wait.remove(); addMsg("ai", "出错：" + e.message + (e.status === 401 ? "。已弹出口令输入框，保存后重新发送即可。" : "")); S.chat.pop(); }
  $("#askSend").disabled = false; $("#askInput").focus();
}

/* ------------------------------------------------------------------ 方法原文 */
function renderPaper() {
  const P = (id, k) => { const p = ind(id).paper; return p && p[k] != null ? p[k].toFixed(2) : "—"; };
  const llmIds = ["retail_yoy", "import_yoy", "ip_ytd", "trade_balance", "export_yoy", "cpi_mom", "new_loans"];
  $("#paper").innerHTML = `
  <h2>方法原文</h2>
  <p>本站复现中金公司研究部《量化配置系列（18）：如何利用大模型实时预测宏观经济指标？》（2025 年 7 月 9 日；陈宜筠、郑文才、周萧潇、刘均伟）的实时预测框架：<b>SARIMAX 自回归 + DeepSeek + 研报文本</b>，月频宏观指标，原文测试区间 2014/1/1–2025/5/30。</p>
  <h2>核心结论</h2>
  <ul>
    <li>宏观数据发布滞后；实时预测用于把决策窗口前移。</li>
    <li>自回归对“不作差分即平稳、弱趋势”指标有效（如 CPI 环比），对贷款、出口等提升有限。</li>
    <li>LLM 读研报<b>标题</b>效果最好：新增人民币贷款相关性由沿用上期 −0.10 升至 0.90，出口同比 0.37→0.72，贸易差额 0.55→0.76；社零、进口与上期高相关，提升不明显；CPI 环比仍偏弱。</li>
    <li>落地顺序：高相关沿用上期 → 平稳弱趋势用春节/季节调整 SARIMAX → 其余用 LLM 读研报标题。</li>
  </ul>
  <h2>滞后处理</h2>
  <table><tr><th>方法</th><th>做法</th><th>数据维护成本</th><th>状态适应能力</th><th>策略稳定性</th></tr>
    <tr><td>定期后移法</td><td>沿用上期已发布数据</td><td>低</td><td>依赖线性外推</td><td>完全可复现</td></tr>
    <tr><td>动态后移法</td><td>按历次发布日期后置数据</td><td>中</td><td>依赖线性外推</td><td>完全可复现</td></tr>
    <tr><td>实时预测法</td><td>对指标建模预测当期</td><td>高</td><td>强</td><td>存在模型随机性</td></tr></table>
  <h2>三种方法</h2>
  <table><tr><th>方法</th><th>优点</th><th>缺点</th></tr>
    <tr><td>高频拆分（GDPNow 式）</td><td>可解释、底层稳</td><td>费领域知识、难系统复用、高频噪声易过拟合</td></tr>
    <tr><td>SARIMAX 自回归</td><td>可系统测试、复杂度低</td><td>数据假设高，适合惯性强、外生冲击少的指标</td></tr>
    <tr><td>LLM 解读文本</td><td>处理各类文本，对预期变化与拐点敏锐</td><td>随机性、依赖输入质量、速度慢</td></tr></table>
  <h2>数据要求</h2>
  <p>自回归：①差分后平稳；②残差白噪声；③序列存在（偏）自相关；④覆盖 2–3 个完整季节周期；⑤变化由历史值线性组合驱动。本站对每个指标计算原序列 ADF 与 Ljung-Box 检验，扩展窗口每年 1 月按 AIC 重选 (p,d,q)，其余月份重估参数。</p>
  <h2>春节效应</h2>
  <p>SARIMAX 季节项只能处理固定周期，春节公历日期每年变化，故以“春节假期（除夕至初六）占当月天数比例”为外生变量；对社零同比、贸易差额、CPI 环比做春节调整。新增人民币贷款使用 (P,D,Q)=(1,0,0) 的 12 期季节参数。</p>
  <h2>判断流程</h2>
  <ol><li>与上期值相关性 ≥ 0.8 → 直接沿用上期，不建模；</li><li>符合平稳/自相关要求 → SARIMAX，有春节效应加外生变量；</li><li>不符合或自回归效果差 → LLM 结合当月研报文本预测。</li></ol>
  <h2>原文结果</h2>
  <div class="tbl-wrap"><table><tr><th>指标</th><th>沿用上期</th><th>自回归（含春节）</th><th>LLM标题</th><th>LLM chunk</th><th>标题+自回归</th><th>chunk+自回归</th></tr>
  ${llmIds.map(id => `<tr><td>${esc(ind(id).name)}</td><td>${P(id, "persist")}</td><td>${P(id, "ar2")}</td><td>${P(id, "title")}</td><td>${P(id, "chunk")}</td><td>${P(id, "title_ar")}</td><td>${P(id, "chunk_ar")}</td></tr>`).join("")}
  </table></div><p class="src">资料来源：Wind、朝阳永续、DeepSeek-R1、中金公司研究部。高相关组（贷款余额 0.98、PPI 0.98、社融存量 0.98、M2 0.96、CPI 同比 0.91、固投累计 0.80）直接沿用上期。</p>
  <ul>
    <li>正文 chunk 整体弱于标题：召回含重复引用、表头/资料来源、模糊匹配、关键词科普。</li>
    <li>加自回归参考大多变差：锚定历史外推，削弱文本对非趋势反转的信号。</li>
    <li>预训练泄漏检验：DeepSeek-R1 预训练截至 2025 年 1 月，前后除贸易差额外无系统差异，回测受“记住未来”影响有限。</li>
  </ul>
  <h2>原文提示词</h2>
  <pre>你的任务是根据{year}年{month}月内的宏观研究报告标题，预测{year}年{month}月的{target_var},并严格按照规定格式输出结果。以下是你需要遵循的步骤:
1、仔细阅读所有的研究报告标题(&lt;标题&gt;)，进行全量语义分析，注意分析标题内含的宏观观点对于目标预测指标的影响方向，以及观点的情感程度，不要有任何跳过。
2、在回答问题时，请先在&lt;思考&gt;标签内详细阐述你思考如何回答这个问题的过程，包括你考虑的要点、可能的推理方向等。然后在&lt;回答&gt;标签内给出针对问题的最终答案。
3、&lt;回答&gt;输出你预测的{year}年{month}月的{target_var},只要数值,格式是小数点一位的小数加百分号或数字本身，结束以&lt;/回答&gt;表示
4、&lt;理由&gt;输出你预测的{year}年{month}月的{target_var}的预测理由，只要文本，尽量精简，结束以&lt;/理由&gt;表示
&lt;标题&gt;
{combined_title}
&lt;/标题&gt;
请开始你的任务。</pre>
  <h2>本站实现</h2>
  <table><tr><th>环节</th><th>原文</th><th>本站</th></tr>
    <tr><td>宏观数据</td><td>Wind</td><td>东方财富数据中心（国家统计局/海关/央行口径），支持上传 Wind CSV 覆盖</td></tr>
    <tr><td>研报文本</td><td>朝阳永续向量库（标题 + 向量召回 chunk）</td><td>东方财富研报中心宏观/策略报告：关键词召回标题、标题去重；正文片段取研报摘要中含关键词段落，过滤资料来源/表头/重复</td></tr>
    <tr><td>大模型</td><td>DeepSeek-R1</td><td>DeepSeek API（默认 deepseek-v4-pro 推理模型，可切换 deepseek-flash），服务端调用，密钥不下发浏览器</td></tr>
    <tr><td>自回归</td><td>SARIMAX</td><td>回归 + SARIMA 误差，CSS 极大似然（numpy/scipy 实现），ADF 定差分阶，AIC 选阶；CPI 环比、新增贷款按原文取 d=0</td></tr>
    <tr><td>回测</td><td>2014/1–2025/5 扩展窗口</td><td>2014/1 起至最新公布月，扩展窗口；LLM 回测受研报库限制自 2017 年起</td></tr>
    <tr><td>工业增加值</td><td>规模以上累计同比</td><td>同口径；1–2 月合并发布的指标剔除 1 月</td></tr></table>
  <p class="src">本站内容仅用于方法研究，不构成投资建议。原文观点以中金研究网站 research.cicc.com 发布的完整报告为准。</p>`;
}

/* ------------------------------------------------------------------ 设置 */
async function savePwd() {
  try { localStorage.setItem("nowcast_pwd", $("#pwd").value); } catch (e) { }
  try { await api("/api/auth/check", { method: "POST", json: {} }); $("#pwdMsg").textContent = "✓ 口令有效"; }
  catch (e) { $("#pwdMsg").textContent = "✗ " + e.message; }
}
async function doRefresh() {
  try { await api("/api/refresh", { method: "POST", json: {} }); toast("已开始重新抓取数据源，约 1 分钟后自动更新", $("#dataInfo")); $("#tblMeta").textContent = "· 正在从东方财富重新抓取，约 1 分钟后自动更新…"; S.seriesCache = {}; setTimeout(() => { loadOverview(); refreshStatus(); if (S.view === "reports") { renderTable(); renderSeries(); } }, 15000); }
  catch (e) { const m = e.message + (e.status === 401 ? "（请先在“方法与设置”输入访问口令）" : ""); toast(m, $("#dataInfo")); $("#tblMeta").textContent = "· " + m; }
}
async function doOverride(clear) {
  const id = $("#ovInd").value;
  try {
    let body = "";
    if (!clear) { const f = $("#ovFile").files[0]; if (!f) { $("#ovMsg").textContent = "请选择 CSV 文件"; return; } body = await f.text(); }
    const r = await fetch(`/api/override/${id}${clear ? "?clear=1" : ""}`, { method: "POST", body, headers: { "X-Access-Password": pwd(), "Content-Type": "text/plain" } });
    const j = await r.json(); if (!r.ok) throw new Error(j.error);
    $("#ovMsg").textContent = clear ? "已清除覆盖，模型重算中" : `已导入 ${j.rows} 行，模型重算中`; S.seriesCache = {};
    setTimeout(loadOverview, 6000);
  } catch (e) { $("#ovMsg").textContent = e.message; }
}

/* ------------------------------------------------------------------ 路由与初始化 */
function show(v) {
  if (!VIEW_TITLE[v]) v = "workbench";
  S.view = v;
  $$(".view").forEach(s => s.hidden = s.id !== "v-" + v);
  $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.v === v));
  $("#viewTitle").textContent = VIEW_TITLE[v];
  if (!S.meta) return;
  if (v === "workbench") loadOverview();
  if (v === "reports") { renderTable(); renderSeries(); if (!S.repLoaded) { S.repLoaded = true; renderReports(); } }
  if (v === "ask") { fillSelect($("#askModel"), S.meta.models.map(m => [m, m]), S.meta.model); setTimeout(() => $("#askInput").focus(), 50); }
  if (v === "backtest") renderBacktest();
  if (v === "archive") renderArchive();
  if (v === "method") { renderPaper(); const st = S.status || {}; $("#dataInfo").textContent = `当前：${(st.data || {}).source || "—"}，数据版本 ${st.loaded_at || "—"}，上次检查 ${st.last_check || "—"}；服务端每 ${st.refresh_hours} 小时轮询数据源，有新数据时页面自动刷新。`; $("#pwd").value = pwd(); }
}
function fillSelect(sel, opts, val) { sel.innerHTML = opts.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join(""); if (val) sel.value = val; }
async function init() {
  try { S.meta = await api("/api/meta"); }
  catch (e) { $("#cardsNow").innerHTML = `<div class="banner warn">无法连接服务：${esc(e.message)}</div>`; setTimeout(init, 3000); return; }
  const inds = S.meta.indicators.map(i => [i.id, i.short]);
  const nowInds = S.meta.indicators.filter(i => i.role === "nowcast").map(i => [i.id, i.short]);
  const modes = Object.entries(MODE_NAMES);
  fillSelect($("#modeSel"), modes, "title");
  fillSelect($("#repMode"), modes, "title");
  fillSelect($("#modelSel"), S.meta.models.map(m => [m, m]), S.meta.model);
  fillSelect($("#llmModel"), S.meta.models.map(m => [m, m]), S.meta.model);
  $("#btModel").innerHTML = `<option value="">全部</option>` + S.meta.models.map(m => `<option>${esc(m)}</option>`).join("");
  ["#serInd", "#ovInd"].forEach(s => fillSelect($(s), inds, "export_yoy"));
  fillSelect($("#askModel"), S.meta.models.map(m => [m, m]), S.meta.model);
  ["#repInd", "#btInd", "#llmInd", "#leakInd"].forEach(s => fillSelect($(s), nowInds, "export_yoy"));
  $("#arcInd").innerHTML = `<option value="">全部</option>` + inds.map(([v, t]) => `<option value="${v}">${esc(t)}</option>`).join("");
  $("#llmModes").innerHTML = modes.map(([k, t]) => `<label><input type="checkbox" value="${k}" ${k === "title" ? "checked" : ""}> ${t}</label>`).join("");
  const now = new Date(), ym = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1), pym = `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, "0")}`;
  $("#repMonth").value = pym; $("#repMonth").max = ym; $("#llmTo").value = pym; $("#btFrom").value = S.meta.backtest_start;
  $("#leakSplit").value = S.meta.leak_split; $("#llmFrom").min = S.meta.llm_earliest;
  $("#runAll").onclick = () => runNowcast(S.meta.indicators.filter(i => i.role === "nowcast").map(i => i.id), $("#runAll"));
  $("#updateAll").onclick = updateAndPredict;
  $("#tblMonths").onchange = renderTable; $("#refreshData").onclick = doRefresh;
  $("#askSend").onclick = askSend; $("#askClear").onclick = () => { S.chat = []; $("#chatBox").innerHTML = ""; };
  $("#askInput").addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); askSend(); } });
  $("#serInd").onchange = renderSeries; $("#serFrom").onchange = renderSeries;
  $("#repGo").onclick = renderReports;
  $("#btGo").onclick = renderBacktest; $("#btInd").onchange = renderBtChart;
  $("#llmGo").onclick = runLlmBacktest; $("#leakGo").onclick = runLeak;
  $("#arcGo").onclick = renderArchive; $("#arcInd").onchange = renderArchive; $("#arcSrc").onchange = renderArchive;
  $("#pwdSave").onclick = savePwd; $("#refresh").onclick = doRefresh;
  $("#ovUp").onclick = () => doOverride(false); $("#ovClear").onclick = () => doOverride(true);
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (S.view === "reports") renderSeries(); if (S.view === "backtest") renderBtChart(); }, 200); });
  await refreshStatus();
  setInterval(refreshStatus, 15000);
  show(location.hash.slice(1) || "workbench");
}
addEventListener("hashchange", () => show(location.hash.slice(1)));
init();
