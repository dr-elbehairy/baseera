/* Baseera platform app — vanilla JS, no build step. Every number comes from the API. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const API = "/api";
let TOKEN = localStorage.getItem("baseera.token"), ME = null, ASSETS = [], CUR = null, BT = null, SCHEMA = [], PIPE = "assets", PREVIEW_FILE = null, PARAMS = [], JOBPOLL = null, CATALOG = [], CAT = "";
const CAT_AR = { lighting: "الإنارة", pumping: "محطات الضخ", elevators: "المصاعد", pavement: "الأرصفة والمعابر" };
const STATUS_CAT = { pilot: "التجربة الحالية", ready: "جاهزة للاستيعاب" };
const fmt = (x, d = 0) => (x == null ? "—" : Number(x).toLocaleString("en", { maximumFractionDigits: d }));
const pct = (x, d = 0) => (x == null ? "—" : (100 * x).toFixed(d) + "%");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dt = (s) => (s ? s.replace("T", " ").slice(0, 16) : "—");
const TITLES = { glossary: "دليل الرموز والمصطلحات", home: "لوحة المتابعة", week: "قائمة الأسبوع", map: "خريطة الخطر", schedule: "الجدولة والتحسين", twin: "التوأم الرقمي والإشارات", assistant: "مساعد بصيرة", ledger: "سجل قابلية التنبؤ", backtest: "الاختبار الرجعي", data: "البيانات والمدخلات", params: "معاملات التشغيل", ops: "التشغيل والمهام", method: "المنهجية" };
const TIER_AR = { immediate: "فوري", urgent: "عاجل", planned: "مخطط", monitor: "مراقبة" };
const tierBadge = (t) => t ? `<span class="tier ${t}">${TIER_AR[t] || t}</span>` : "";
const winTxt = (w) => (w && w[0] != null) ? `اليوم ${w[0]}–${w[1]}` : "—";
const ROUTE_COLORS = ["#0f5f6b", "#b7791f", "#2d5fa6", "#7b3fa0", "#1f8a5b"];
const ROLE_AR = { supervisor: "مشرف", technician: "فني", manager: "مدير تشغيل", admin: "مدير النظام" };

/* ------------------------------------------------------------------ infra */
async function api(path, opt = {}) {
  const headers = { ...(opt.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}), ...(opt.headers || {}) };
  const r = await fetch(API + path, { ...opt, headers });
  if (r.status === 401) { logout(); throw new Error("انتهت الجلسة"); }
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail || r.statusText)); }
  return r.json();
}
function toast(msg, kind = "") { const t = document.createElement("div"); t.className = "toast " + kind; t.textContent = msg; document.body.appendChild(t); setTimeout(() => t.remove(), 2800); }
function modal(html, onOk) {
  const root = $("#modalRoot"); root.innerHTML = `<div class="modal-bg"><div class="modal">${html}<div class="ft"><button class="btn ghost" id="mCancel">إلغاء</button><button class="btn" id="mOk">تأكيد</button></div></div></div>`;
  const close = () => (root.innerHTML = ""); $("#mCancel").onclick = close; $(".modal-bg").onclick = (e) => { if (e.target === e.currentTarget) close(); };
  $("#mOk").onclick = async () => { try { if ((await onOk($(".modal"))) !== false) close(); } catch (e) { toast(e.message, "bad"); } };
}
function logout() { TOKEN = null; localStorage.removeItem("baseera.token"); $("#app").hidden = true; $("#login").hidden = false; clearInterval(JOBPOLL); }
$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await fetch(API + "/auth/login", { method: "POST", body: new URLSearchParams(new FormData(e.target)) });
  if (!r.ok) return toast("بيانات الدخول غير صحيحة", "bad");
  TOKEN = (await r.json()).access_token; localStorage.setItem("baseera.token", TOKEN); boot();
});
$("#logout").onclick = logout;

async function boot() {
  try { ME = await api("/auth/me"); } catch { return; }
  $("#who").textContent = `${ME.display_name} · ${ROLE_AR[ME.role] || ME.role}`;
  $$("#nav [data-roles]").forEach((a) => (a.hidden = !a.dataset.roles.split(",").includes(ME.role)));
  $("#login").hidden = true; $("#app").hidden = false;
  try { CATALOG = await api("/admin/catalog"); } catch { CATALOG = []; }
  renderChips(); loadAssets(); route();
}
function renderChips() {
  $("#catChips").innerHTML = [["", "كل الفئات"], ...Object.entries(CAT_AR)].map(([k, v]) => `<button class="chip ${CAT === k ? "on" : ""}" data-cat="${k}">${v}</button>`).join("");
}
$("#catChips").addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (!b) return; CAT = b.dataset.cat; renderChips(); route(); if (!$("#d-catalog").hidden) renderCatalog(); });
const inCat = (c) => !CAT || c === CAT;
window.addEventListener("hashchange", route);
function route() {
  let h = (location.hash || "#home").slice(1);
  const link = $(`#nav a[href="#${h}"]`); if (link && link.hidden) { h = "home"; location.hash = "#home"; }
  $$(".view").forEach((v) => (v.hidden = v.id !== "v-" + h));
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + h));
  $("#title").textContent = TITLES[h] || ""; $("#crumbs").textContent = "بصيرة / " + (TITLES[h] || "") + (CAT ? " / " + CAT_AR[CAT] : "");
  $("#catChips").hidden = !["home", "week", "map", "schedule", "twin", "backtest", "data"].includes(h);
  clearInterval(JOBPOLL);
  ({ glossary: () => loadGlossary($("#glossaryView")), home: loadHome, week: loadWeek, map: () => loadAssets().then(drawMap), schedule: loadSchedule, twin: loadTwinView, assistant: loadAssistant, ledger: loadLedger, backtest: loadBacktest, data: loadData, params: loadParams, ops: loadOps }[h] || (() => {}))();
}

/* ------------------------------------------------------------------ home */
async function loadHome() {
  const canAdmin = ["admin", "manager"].includes(ME.role);
  let ov = null; if (canAdmin) { try { ov = await api("/admin/overview"); } catch {} }
  try { CUR = await api("/weekly-lists/current"); } catch { CUR = null; }
  let L = null; try { L = await api("/ledger/months"); } catch {}
  const last = L?.months?.filter((m) => m.n_failures).slice(-1)[0];
  if (ov && ov.categories) $("#homeCats").innerHTML = ov.categories.filter((c) => inCat(c.key)).map((c) => `<div class="catcard"><div class="row between"><b>${esc(c.ar)}</b><span class="badge ${c.status === "pilot" ? "ok" : "info"}">${STATUS_CAT[c.status] || c.status}</span></div><div class="row" style="gap:18px;margin-top:6px"><div><span class="n">${fmt(c.n_assets)}</span> <small class="muted">أصل</small></div><div><span class="n">${fmt(c.n_failures)}</span> <small class="muted">عطل مسجّل</small></div></div><p class="small text2" style="margin:4px 0 0">${esc(c.status_ar)}</p></div>`).join("");
  else $("#homeCats").innerHTML = Object.entries(CAT_AR).filter(([k]) => inCat(k)).map(([k, v]) => { const n = ASSETS.filter((a) => a.category === k).length; return `<div class="catcard"><b>${v}</b><div><span class="n">${fmt(n)}</span> <small class="muted">أصل في الخريطة</small></div></div>`; }).join("");
  const nAssets = CAT ? (ov ? (ov.categories.find((c) => c.key === CAT) || {}).n_assets : ASSETS.filter((a) => a.category === CAT).length) : (ov ? ov.tables.assets.n : ASSETS.length);
  const nList = CUR ? CUR.items.filter((i) => inCat(i.category)).length : null;
  $("#homeKpis").innerHTML = kpi("أصول تحت المراقبة", fmt(nAssets)) + kpi("قائمة الأسبوع", CUR ? `${nList} <small>بند · ${CUR.status === "approved" ? "معتمدة" : "مقترحة"}</small>` : "—")
    + kpi("PFR@L آخر شهر <small>(قوائم معتمدة)</small>", last ? pct(last.pfr.own) : "—", "accent") + kpi("نسبة الطارئ", last ? pct(last.emergency_share) : "—") + (ov ? kpi("سطور محجورة", fmt(ov.quarantine_open), ov.quarantine_open ? "" : "") : "");
  if (ov) {
    const T = ov.tables, names = { cabinets: "الخزانات", assets: "الأصول", weather: "أيام الطقس", reports: "البلاغات", work_orders: "أوامر العمل", observations: "العلامات" };
    $("#homeData").innerHTML = `<table class="tbl">${Object.entries(names).map(([k, n]) => `<tr><td>${n}</td><td class="num"><b>${fmt(T[k].n)}</b></td><td class="small text2">${T[k].from ? T[k].from.slice(0, 10) + " ← " + T[k].to.slice(0, 10) : ""}</td><td>${Object.entries(T[k].by_source).map(([s, c]) => `<span class="badge ${s === "simulated" ? "sim" : "ok"}">${s === "simulated" ? "محاكاة" : s} ${fmt(c)}</span>`).join(" ")}</td></tr>`).join("")}</table>`;
    const m = ov.model;
    $("#homeModel").innerHTML = m ? `<div class="kv"><span>النموذج المعتمد</span><b>${esc(m.name)} <span class="mono">${m.model_version_id.slice(0, 8)}</span></b><span>AUC</span><b>${m.auc?.toFixed(3)}</b><span>البوابات</span><b>${Object.entries(m.gates).map(([k, g]) => `<span class="gate ${g ? "ok" : ""}">${k}</span>`).join(" ")}</b><span>آخر قائمة</span><b>${ov.weekly_list ? `${ov.weekly_list.week_start} · ${ov.weekly_list.items} بند · ${ov.weekly_list.status}` : "—"}</b><span>آخر مهمة</span><b>${ov.last_job ? `${JOB_AR[ov.last_job.kind] || ov.last_job.kind} · ${STATUS_AR[ov.last_job.status]}` : "—"}</b></div>` : `<div class="empty">لا نموذج معتمد بعد. <a href="#ops">شغّل إعادة الحساب</a> أو ابدأ بالمحاكاة.</div>`;
    const steps = $$("#homeSteps li"); const n = T.assets.n ? (m ? (ov.weekly_list ? (ov.weekly_list.status === "approved" ? (last ? 5 : 4) : 3) : 2) : 1) : 0;
    steps.forEach((li, i) => { li.className = i < n ? "done" : i === n ? "on" : ""; });
    $("#envTag").textContent = "البيئة: " + ov.env;
  } else {
    $("#homeData").innerHTML = `<p class="text2">${fmt(ASSETS.length)} أصلًا في الخريطة. تفاصيل المصادر متاحة لمدير النظام.</p>`;
    $("#homeModel").innerHTML = CUR ? `<div class="kv"><span>أسبوع</span><b>${CUR.week_start}</b><span>الحالة</span><b>${CUR.status === "approved" ? "معتمدة" : "مقترحة"}</b><span>البنود</span><b>${CUR.items.length} / ${CUR.capacity}</b></div>` : `<div class="empty">لا قائمة بعد.</div>`;
  }
}
const kpi = (l, v, cls = "") => `<div class="kpi ${cls}"><span>${l}</span><b>${v}</b></div>`;

/* ------------------------------------------------------------------ weekly list */
async function loadWeek() {
  try { CUR = await api("/weekly-lists/current"); } catch (e) { $("#weekTable tbody").innerHTML = `<tr><td colspan="10"><div class="empty">${esc(e.message)}</div></td></tr>`; $("#kpis").innerHTML = ""; return; }
  $("#weekDate").textContent = "أسبوع " + CUR.week_start;
  $("#capacity").textContent = `${CUR.used} / ${CUR.capacity} طاقة الطاقم · ${CUR.status === "approved" ? "معتمدة" : "مقترحة"}`; $("#capacity").className = "badge " + (CUR.status === "approved" ? "ok" : "warn");
  $("#approveAll").hidden = ME.role !== "supervisor" || CUR.status === "approved";
  $("#weekTable tbody").innerHTML = CUR.items.filter((i) => inCat(i.category)).map((i) => `<tr data-id="${i.item_id}" class="${i.status}">
    <td class="num">${i.rank}</td><td><a href="#map" data-asset="${i.asset_id}">${esc(i.code)}</a>${i.crit !== "none" ? ' <span class="crit">' + esc(CRIT_AR[i.crit] || i.crit) + "</span>" : ""}</td>
    <td><span class="badge">${esc(CAT_AR[i.category] || i.category || "")}</span></td><td title="${esc(i.type_ar || "")}">${esc(i.type_ar || i.type)} <small class="muted mono">${esc(i.type)}</small></td><td>${tierBadge(i.tier)}</td><td class="num"><span class="bar"><i class="${i.p >= .35 ? "hi" : i.p >= .1 ? "md" : ""}" style="width:${Math.min(100, i.p * 100)}%"></i></span>${pct(i.p)}</td>
    <td class="num small">${winTxt(i.window)}</td><td class="num">${fmt(i.risk_sar)}</td><td><b>${esc(i.action_ar)}</b></td><td class="small">${i.route ? `مسار ${i.route} · ${i.seq}${i.grouped ? " · تجميع" : ""}` : "—"}</td><td class="reason">${esc(i.reason)}<br><small class="muted">${esc(i.safe_window || "")}</small></td>
    <td>${statusAr(i)}</td><td class="actions">${ME.role === "supervisor" && i.status === "proposed" ? `<button class="btn sm" data-act="approved">اعتماد</button><button class="btn ghost sm" data-act="overridden">تجاوز</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="13"><div class="empty">لا أصول فوق عتبة الإنذار هذا الأسبوع في هذه الفئة</div></td></tr>';
  const sumRisk = CUR.items.reduce((s, i) => s + i.risk_sar, 0);
  const tiers = CUR.items.reduce((m, i) => ((m[i.tier] = (m[i.tier] || 0) + 1), m), {});
  $("#kpis").innerHTML = kpi("الأصول في القائمة", CUR.items.length) + kpi("الخطر المعالَج (ر.س)", fmt(sumRisk), "accent") + kpi("فوري / عاجل", `${tiers.immediate || 0} / ${tiers.urgent || 0}`) + kpi("مسارات", new Set(CUR.items.map((i) => i.route).filter(Boolean)).size) + kpi("الحالة", CUR.status === "approved" ? "معتمدة" : "مقترحة");
}
const CRIT_AR = { mosque: "مسجد", school: "مدرسة", crossing: "معبر", hospital: "مستشفى" };
const statusAr = (i) => ({ proposed: '<span class="badge">مقترح</span>', approved: '<span class="badge ok">معتمد</span>', overridden: `<span class="badge warn">تجاوز</span> <small>${esc(i.override_reason || "")}</small>`, done: `<span class="badge info">منفّذ</span> <small>${esc(i.outcome?.finding || "")}</small>`, skipped: '<span class="badge warn">مُلغى</span>' }[i.status] || i.status);
$("#weekTable").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-act]"); if (!b) return;
  const id = e.target.closest("tr").dataset.id, status = b.dataset.act;
  if (status === "approved") { try { await api(`/weekly-lists/items/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }); await loadWeek(); } catch (err) { toast(err.message, "bad"); } return; }
  modal(`<h3>تجاوز بند القائمة</h3><p class="text2 small">التجاوز حق المشرف، والسبب إلزامي ويُسجَّل.</p><label>السبب</label><textarea id="ovReason" rows="2"></textarea><label>الإجراء البديل</label><select id="ovAction"><option value="inspect">فحص</option><option value="service">صيانة</option><option value="replace">استبدال</option><option value="">إلغاء البند</option></select>`,
    async (m) => { const reason = $("#ovReason", m).value.trim(); if (!reason) { toast("السبب إلزامي", "bad"); return false; } const action = $("#ovAction", m).value; await api(`/weekly-lists/items/${id}`, { method: "PATCH", body: JSON.stringify(action ? { status, override_reason: reason, action } : { status: "skipped", override_reason: reason }) }); await loadWeek(); });
});
$("#approveAll").onclick = () => modal(`<h3>اعتماد كل البنود المقترحة؟</h3><p class="text2">${CUR.items.filter((i) => i.status === "proposed").length} بندًا ستصبح مهامًا للطاقم هذا الأسبوع.</p>`, async () => { await api(`/weekly-lists/${CUR.list_id}/approve`, { method: "POST" }); await loadWeek(); toast("اعتُمدت القائمة", "ok"); });

/* ------------------------------------------------------------------ map */
async function loadAssets() { try { ASSETS = (await api("/assets?limit=20000")).items; } catch { ASSETS = []; } }
const riskColor = (p) => (p == null ? "#8b96a3" : p >= 0.35 ? "#c0392b" : p >= 0.1 ? "#b7791f" : "#1f8a5b");
let MAPT = null;
function drawMap() {
  const c = $("#map"), ctx = c.getContext("2d"); ctx.fillStyle = "#eef2f5"; ctx.fillRect(0, 0, c.width, c.height); if (!ASSETS.length) return;
  const lons = ASSETS.map((a) => a.lon), lats = ASSETS.map((a) => a.lat);
  const x0 = Math.min(...lons), x1 = Math.max(...lons), y0 = Math.min(...lats), y1 = Math.max(...lats);
  const pad = 30, s = Math.min((c.width - 2 * pad) / (x1 - x0 || 1), (c.height - 2 * pad) / (y1 - y0 || 1));
  MAPT = (a) => [pad + (a.lon - x0) * s, c.height - pad - (a.lat - y0) * s];
  ctx.strokeStyle = "#dfe5eb"; for (let g = 0; g <= 10; g++) { ctx.beginPath(); ctx.moveTo(pad + (g * (c.width - 2 * pad)) / 10, 0); ctx.lineTo(pad + (g * (c.width - 2 * pad)) / 10, c.height); ctx.stroke(); }
  for (const a of ASSETS) {
    if (!inCat(a.category)) continue;
    const [x, y] = MAPT(a); ctx.fillStyle = riskColor(a.p);
    if (a.kind === "cabinet" || a.kind === "panel") ctx.fillRect(x - 6, y - 6, 12, 12);
    else if (a.category === "pumping") { ctx.beginPath(); ctx.moveTo(x, y - 7); ctx.lineTo(x + 7, y + 5); ctx.lineTo(x - 7, y + 5); ctx.closePath(); ctx.fill(); }
    else if (a.category === "elevators") { ctx.fillRect(x - 5, y - 5, 10, 10); ctx.strokeStyle = "#fff"; ctx.strokeRect(x - 5, y - 5, 10, 10); }
    else if (a.category === "pavement") { ctx.fillRect(x - 6, y - 2, 12, 4); }
    else { ctx.beginPath(); ctx.arc(x, y, a.listed ? 5 : 3, 0, 7); ctx.fill(); }
    if (a.listed) { ctx.strokeStyle = "#152230"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(x, y - 9); ctx.lineTo(x + 9, y); ctx.lineTo(x, y + 9); ctx.lineTo(x - 9, y); ctx.closePath(); ctx.stroke(); }
  }
}
$("#map").addEventListener("click", (e) => {
  const r = e.target.getBoundingClientRect(), x = (e.clientX - r.left) * (e.target.width / r.width), y = (e.clientY - r.top) * (e.target.height / r.height);
  let best = null, bd = 1e9; for (const a of ASSETS) { if (!inCat(a.category)) continue; const [ax, ay] = MAPT(a); const d = (ax - x) ** 2 + (ay - y) ** 2; if (d < bd) { bd = d; best = a; } }
  if (best && bd < 400) showCard(best.asset_id);
});
document.addEventListener("click", (e) => { const a = e.target.closest("a[data-asset]"); if (a) setTimeout(() => showCard(a.dataset.asset), 60); });
async function showCard(id) {
  const c = await api("/assets/" + id); const p = c.prediction, ex = p?.explanation || {};
  $("#detail").innerHTML = `<h3>${esc(c.code)} <small class="muted">${esc(CAT_AR[c.category] || "")} · ${esc(c.type_ar || c.type)} · ${c.street === "main" ? "رئيسي" : "فرعي"} · ${esc(CRIT_AR[c.crit] || "")}</small></h3>
    <div class="kv" style="margin-top:8px"><span>الخزانة</span><b>${esc(c.cabinet || "—")}</b><span>التركيب</span><b>${esc(c.install || "—")}</b><span>الاحتمال 14 يومًا</span><b style="color:${riskColor(p?.p)}">${pct(p?.p, 1)}</b><span>الخطر (ر.س)</span><b>${fmt(p?.risk_sar)}</b><span>المصدر</span><b><span class="badge ${c.source === "simulated" ? "sim" : "ok"}">${c.source === "simulated" ? "محاكاة" : esc(c.source)}</span></b></div>
    ${p ? `<div class="row" style="margin-top:8px">${tierBadge(p.tier)} <span class="badge">نافذة العطل: ${winTxt(p.window)}</span> ${p.mode ? `<span class="badge">${esc(MODE_AR_OF(p.mode))}</span>` : ""} <a href="#twin" data-twin="${esc(c.code)}" class="small">التوأم والإشارات ←</a></div>` : ""}
    ${p && p.cof ? `<h4 style="margin-top:10px">العواقب المكافئة ${fmt(p.cof.total)} ر.س</h4>${cofBars(p.cof)}` : ""}
    ${c.list_item ? `<p style="margin-top:8px"><span class="badge info">في قائمة الأسبوع #${c.list_item.rank} · ${esc(c.list_item.action)} · ${esc(c.list_item.status)}</span></p><p class="reason">${esc(c.list_item.reason)}</p>` : ""}
    ${Object.keys(ex).length ? `<h4 style="margin-top:10px">لماذا هذا الاحتمال</h4><ul class="expl">${Object.entries(ex).sort((a, b) => b[1] - a[1]).map(([g, v]) => `<li><span>${esc(GROUP_AR[g] || g)}</span><i style="width:${Math.max(2, Math.abs(v) * 300)}px;background:${v >= 0 ? "#c0392b" : "#1f8a5b"}"></i>${(v * 100).toFixed(1)} نقطة</li>`).join("")}</ul>` : ""}
    <h4 style="margin-top:10px">العلامات المسجّلة</h4>${c.observations.length ? `<ul class="plain">${c.observations.slice(0, 5).map((o) => `<li>${o.at.slice(0, 10)} · ${esc(o.symptom_ar || o.symptom)} · شدة ${o.severity} · ${esc(o.source_ar || o.source)}</li>`).join("")}</ul>` : '<p class="muted small">لا علامات</p>'}
    <h4 style="margin-top:10px">الأعطال السابقة</h4>${c.failures.length ? `<ul class="plain">${c.failures.map((f) => `<li>${f.on} · ${esc(f.mode_ar || f.mode || "غير محدد")} · ${f.lead == null ? "بلا إنذار" : "إنذار قبل " + f.lead + " يومًا"}</li>`).join("")}</ul>` : '<p class="muted small">لا أعطال مسجّلة</p>'}
    <p class="muted small">النموذج <span class="mono">${esc((p?.model_version_id || "").slice(0, 8))}</span></p>`;
}
const GROUP_AR = { symptoms: "أعراض مرصودة على الأصل", network: "انقطاعات جزئية على الدائرة", weather: "الحرارة والأمطار", history: "سجل الأعطال السابقة", asset: "عمر الأصل ونوعه", telemetry: "إشارات الحساسات", environment: "الإجهاد البيئي والعمر المكافئ", graph: "الاعتماديات" };
const CLASS_AR = { A: "أ · قابل للاستباق", B: "ب · بمهلة قصيرة", C: "ج · عشوائي/خفي" };
const COF_AR = { service: "انقطاع الخدمة", safety: "السلامة", financial: "علاوة الطارئ", environment: "البيئة", reputation: "السمعة" };
const MODE_AR_OF = (m) => { for (const c of CATALOG) { const x = c.modes.find((y) => y.code === m); if (x) return x.ar; } return m; };
function cofBars(cof) { const mx = Math.max(...Object.keys(COF_AR).map((k) => cof[k] || 0), 1); return Object.entries(COF_AR).map(([k, ar]) => `<div class="cofrow"><span>${ar}</span><i style="width:${Math.max(2, (cof[k] || 0) / mx * 100)}%"></i><span class="num">${fmt(cof[k])}</span></div>`).join("") + (cof.n_dependents ? `<p class="small muted">${fmt(cof.n_dependents)} أصل يعتمد عليه${cof.season_boost && cof.season_boost !== 1 ? ` · موسم الأمطار ×${cof.season_boost}` : ""}</p>` : ""); }
document.addEventListener("click", (e) => { const a = e.target.closest("a[data-twin]"); if (a) { setTimeout(() => { $("#twinCode").value = a.dataset.twin; loadTwin(a.dataset.twin); }, 80); } });

/* ------------------------------------------------------------------ schedule / optimiser */
let SCH = null;
async function loadSchedule() {
  $("#topRight").innerHTML = "";
  try { SCH = await api("/schedule/current"); } catch (e) { $("#schKpis").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  $("#schBanner").innerHTML = SCH.banner.length ? `<div class="callout warn">${SCH.banner.map(esc).join(" · ")}</div>` : "";
  const items = SCH.items.filter((i) => inCat(i.category)); const routesF = SCH.routes.map((r) => ({ ...r, items: r.items.filter((i) => inCat(i.category)) })).filter((r) => r.items.length);
  $("#schKpis").innerHTML = kpi("مهام الأسبوع" + (CAT ? " (" + CAT_AR[CAT] + ")" : ""), items.length) + kpi("الخطورة المعالَجة (ر.س)", fmt(items.reduce((s, i) => s + i.risk_sar, 0)), "accent") + kpi("التكلفة / الميزانية", `${fmt(items.reduce((s, i) => s + i.cost, 0))} / ${fmt(SCH.budget)}`) + kpi("الطواقم / المسارات", `${SCH.crews} / ${routesF.length}`) + kpi("بالتجميع الجغرافي", items.filter((i) => i.grouped).length);
  $("#tierCards").innerHTML = Object.entries(TIER_AR).map(([k, v]) => `<div class="tiercard"><span class="tier ${k}">${v}</span><b style="display:block">${items.filter((i) => i.tier === k).length}</b></div>`).join("");
  const pts = SCH.pareto; if (!$("#budgetIn").value) $("#budgetIn").value = SCH.budget;
  $("#paretoChart").innerHTML = pts.length ? paretoChart(pts, SCH.budget) : '<div class="empty">لا منحنى بعد</div>';
  $("#routeNote").textContent = `المسار يُرتَّب بأقرب جار؛ المهام الموسومة «تجميع» أُضيفت لأنها ضمن 250 م من المسار بتكلفة تنقل شبه صفرية`;
  $("#routeList").innerHTML = (routesF.length ? routesF : []).map((r) => ({ ...r, k: r.route - 1 })).map((r) => `<div class="card" style="margin-bottom:8px;border-inline-start:4px solid ${ROUTE_COLORS[r.k % 5]}"><div class="hd"><h4>مسار ${r.route} · ${r.items.length} مهام · ${fmt(r.items.reduce((s, i) => s + i.cost, 0))} ر.س · خطورة ${fmt(r.items.reduce((s, i) => s + i.risk_sar, 0))}</h4></div>
    <table class="tbl">${r.items.map((i) => `<tr><td class="num">${i.seq}</td><td><a href="#twin" data-twin="${esc(i.code)}">${esc(i.code)}</a> <small class="muted">${esc(i.type_ar || "")}</small>${i.grouped ? ' <span class="badge sim">تجميع</span>' : ""}</td><td>${tierBadge(i.tier)}</td><td class="small">${esc(i.mode_ar || "")}</td><td class="num small">${winTxt(i.window)}</td><td class="num">${i.return_per_riyal}×</td><td class="small muted">${esc(i.safe_window)}</td><td>${i.work_order ? '<span class="badge ok">أمر عمل</span>' : (ME.role === "supervisor" || ME.role === "admin") ? `<button class="btn ghost sm" data-wo="${i.item_id}">أمر عمل</button>` : ""}</td></tr>`).join("")}</table></div>`).join("") || '<div class="empty">لا مهام في هذه الفئة هذا الأسبوع</div>';
  drawRoutes();
}
function paretoChart(pts, budget) {
  const W = 620, H = 220, p = 40, xmax = Math.max(...pts.map((d) => d.budget)), xs = (b) => p + (b / xmax) * (W - 2 * p), ys = (v) => H - p - v * (H - 2 * p);
  const path = pts.map((d, i) => `${i ? "L" : "M"}${xs(d.budget)},${ys(d.share)}`).join(" ");
  const grid = [0, .25, .5, .75, 1].map((g) => `<line x1="${p}" x2="${W - p}" y1="${ys(g)}" y2="${ys(g)}" class="gridl"/><text x="${p - 6}" y="${ys(g) + 4}" class="tick">${g * 100}%</text>`).join("");
  const dots = pts.map((d) => `<circle cx="${xs(d.budget)}" cy="${ys(d.share)}" r="${d.budget === budget ? 6 : 3.5}" fill="${d.budget === budget ? "#b7791f" : "#0f5f6b"}"/><text x="${xs(d.budget)}" y="${ys(d.share) - 9}" class="tick mid">${pct(d.share)}</text><text x="${xs(d.budget)}" y="${H - 8}" class="tick mid">${fmt(d.budget / 1000)}k</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" direction="ltr">${grid}<path d="${path}" class="line"/>${dots}</svg><p class="small text2">النقطة الذهبية = الميزانية الحالية. كل نقطة: نسبة الخطورة المُزالة · عدد المهام.</p>`;
}
function drawRoutes() {
  const c = $("#routeMap"), ctx = c.getContext("2d"); ctx.fillStyle = "#eef2f5"; ctx.fillRect(0, 0, c.width, c.height); if (!ASSETS.length || !SCH) return;
  const lons = ASSETS.map((a) => a.lon), lats = ASSETS.map((a) => a.lat), x0 = Math.min(...lons), x1 = Math.max(...lons), y0 = Math.min(...lats), y1 = Math.max(...lats);
  const pad = 30, s = Math.min((c.width - 2 * pad) / (x1 - x0 || 1), (c.height - 2 * pad) / (y1 - y0 || 1)), T = (a) => [pad + (a.lon - x0) * s, c.height - pad - (a.lat - y0) * s];
  ctx.fillStyle = "#c9d2db"; for (const a of ASSETS) { const [x, y] = T(a); ctx.fillRect(x - 1, y - 1, 2, 2); }
  SCH.routes.forEach((r, k) => { const col = ROUTE_COLORS[k % 5]; const pts = r.items.slice().sort((a, b) => a.seq - b.seq).map(T); if (CAT && !r.items.some((i) => inCat(i.category))) return;
    ctx.strokeStyle = col; ctx.lineWidth = 2.5; ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke();
    r.items.forEach((i) => { if (!inCat(i.category)) return; const [x, y] = T(i); ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, i.grouped ? 5 : 7, 0, 7); ctx.fill(); ctx.fillStyle = "#fff"; ctx.font = "bold 9px sans-serif"; ctx.textAlign = "center"; ctx.fillText(i.seq, x, y + 3); }); });
}
$("#replan").onclick = async () => { try { await api("/schedule/replan", { method: "POST", body: JSON.stringify({ budget: +$("#budgetIn").value }) }); toast("أُعيدت الجدولة", "ok"); loadSchedule(); } catch (e) { toast(e.message, "bad"); } };
document.addEventListener("click", async (e) => { const b = e.target.closest("button[data-wo]"); if (!b) return; try { const r = await api(`/assistant/work-order/${b.dataset.wo}`, { method: "POST" }); toast("وُلّد أمر العمل " + r.details.asset, "ok"); if (SCH) loadSchedule(); } catch (err) { toast(err.message, "bad"); } });

/* ------------------------------------------------------------------ twin */
async function loadTwinView() {
  $("#topRight").innerHTML = "";
  try { const sc = await api("/schedule/current"); $("#twinQuick").innerHTML = sc.items.filter((i) => inCat(i.category)).slice(0, 6).map((i) => `<button class="chip" data-twinq="${esc(i.code)}">${esc(i.code)}</button>`).join(""); const first = sc.items.find((i) => inCat(i.category)); if (first && (!$("#twinCode").value || CAT)) { $("#twinCode").value = first.code; loadTwin(first.code); } } catch {}
}
$("#twinQuick").addEventListener("click", (e) => { const b = e.target.closest("[data-twinq]"); if (b) { $("#twinCode").value = b.dataset.twinq; loadTwin(b.dataset.twinq); } });
$("#twinGo").onclick = () => loadTwin($("#twinCode").value.trim());
async function loadTwin(code) {
  if (!code) return; let t; try { t = await api("/twin/assets/" + encodeURIComponent(code)); } catch (e) { $("#twinBody").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const p = t.prediction, S = t.sesi, d = t.diagnosis;
  const sesiBars = Object.entries({ heat: "الحرارة (أرينيوس)", dust: "الغبار", humidity: "الرطوبة/الملوحة", season: "أحمال المواسم", rain: "الأمطار" }).map(([k, ar]) => `<div class="sesibar"><span>${ar}</span><i style="width:${Math.max(2, (S.components[k] || 0) * 100)}%"></i><span class="num">${((S.components[k] || 0) * 100).toFixed(0)}%</span></div>`).join("");
  $("#twinBody").innerHTML = `
    <div class="kpis">${kpi("الأصل", `${esc(t.code)} <small>${esc(t.type_ar)}</small>`)}${kpi("احتمال العطل 14 يومًا", p ? pct(p.p) : "—", "accent")}${kpi("نافذة العطل (ثقة 90%)", p ? winTxt(p.window) : "—")}${kpi("الأولوية", p ? tierBadge(p.tier) : "—")}${kpi("الخطورة (ر.س)", p ? fmt(p.risk_sar) : "—")}</div>
    <div class="grid g2">
      <div class="card"><div class="hd"><h3>الإشارات (آخر 120 يومًا)</h3><span class="small text2">خط الأساس = أول 60 يومًا للأصل نفسه؛ z &gt; 2 = شذوذ</span></div>
        ${t.channels.length ? t.channels.map((c) => `<div class="chan"><div><b>${esc(c.ar)}</b><br><small class="muted">${esc(c.source)} · الأساس ${c.baseline} ${esc(c.unit)}</small></div><div class="spark">${spark(c.series, c.anomalous)}</div><div class="num"><b style="color:${c.anomalous ? "#c0392b" : "inherit"}">${c.last} ${esc(c.unit)}</b><br><small class="muted">z = ${c.z}</small></div></div>`).join("") : '<div class="empty">لا قنوات حساسات لهذا الأصل (الإنارة بلا عداد ذكي تعتمد على العلامات والبلاغات)</div>'}
      </div>
      <div class="stack">
        <div class="card"><div class="hd"><h3>مؤشر الإجهاد البيئي SESI</h3><span class="badge">${S.index != null ? (S.index * 100).toFixed(0) + "%" : "—"}</span></div>${sesiBars}
          <div class="kv" style="margin-top:8px"><span>العمر الزمني</span><b>${S.calendar_age_y ?? "—"} سنة</b><span>العمر المكافئ</span><b style="color:#b7791f">${S.equivalent_age_y ?? "—"} سنة (×${S.ageing_factor ?? "—"})</b></div>
          <div class="spark" style="margin-top:6px">${spark(S.series, false)}</div></div>
        <div class="card"><div class="hd"><h3>التشخيص المتوقع</h3>${d.mode_ar ? `<span class="badge info">${esc(d.mode_ar)}</span>` : ""}</div>
          <p class="small text2">${d.basis === "evidence" ? `ثقة ${((d.confidence || 0) * 100).toFixed(0)}% من ${d.evidence.length} دليل` : "لا دليل مباشر؛ النمط الأرجح لنوع الأصل"}</p>
          ${d.evidence && d.evidence.length ? `<ul class="plain">${d.evidence.map((e) => e.kind === "channel" ? `<li>إشارة «${esc(e.ar || e.code)}»: ${e.last} ${esc(e.unit || "")} مقابل أساس ${e.baseline} (z ${e.z})</li>` : `<li>علامة «${esc(e.ar || e.code)}» في ${e.at} (شدة ${e.weight})</li>`).join("")}</ul>` : ""}</div>
        ${p && p.cof ? `<div class="card"><div class="hd"><h3>العواقب المترابطة</h3><span class="badge">${fmt(p.cof.total)} ر.س</span></div>${cofBars(p.cof)}<p class="small muted">يعتمد عليه ${t.graph.dependents} أصل${t.graph.parent ? ` · يتغذى من ${esc(t.graph.parent)}` : ""}</p></div>` : ""}
      </div>
    </div>`;
}
function spark(series, bad) { if (!series || !series.length) return ""; const W = 400, H = 54, vs = series.map((s) => s.v), mn = Math.min(...vs), mx = Math.max(...vs), r = mx - mn || 1;
  const path = series.map((s, i) => `${i ? "L" : "M"}${(i / (series.length - 1)) * W},${H - 4 - ((s.v - mn) / r) * (H - 8)}`).join(" "); return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" direction="ltr"><path d="${path}" fill="none" stroke="${bad ? "#c0392b" : "#0f5f6b"}" stroke-width="2"/></svg>`; }

/* ------------------------------------------------------------------ assistant */
async function loadAssistant() {
  $("#topRight").innerHTML = "";
  let sc = null; try { sc = await api("/schedule/current"); } catch {}
  const a = sc?.items?.[0]?.code, b = sc?.items?.slice(-1)[0]?.code;
  $("#askSuggest").innerHTML = [a && b ? `لماذا قُدّم ${a} على ${b}؟` : null, "ما ملخص الأسبوع؟", a ? `اشرح ${a}` : null].filter(Boolean).map((q) => `<button class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join("");
  if (!$("#chat").children.length) ask("ما ملخص الأسبوع؟");
  loadWOs();
}
$("#askSuggest").addEventListener("click", (e) => { const b = e.target.closest("[data-q]"); if (b) ask(b.dataset.q); });
$("#askForm").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#askIn").value.trim(); if (q) { ask(q); $("#askIn").value = ""; } });
async function ask(q) {
  const chat = $("#chat"); chat.insertAdjacentHTML("beforeend", `<div class="msg q">${esc(q)}</div>`);
  try { const r = await api("/assistant/ask", { method: "POST", body: JSON.stringify({ question: q }) }); chat.insertAdjacentHTML("beforeend", `<div class="msg a">${esc(r.answer)}</div>`); $("#asMode").textContent = r.mode === "llm" ? "نموذج لغوي + حقائق المنصة" : "قالبي من حقائق المنصة"; }
  catch (e) { chat.insertAdjacentHTML("beforeend", `<div class="msg a">${esc(e.message)}</div>`); }
  chat.scrollTop = chat.scrollHeight;
}
async function loadWOs() { const w = await api("/assistant/work-orders"); $("#woList").innerHTML = w.length ? w.map((x) => `<div class="wo"><div class="row between"><b>${esc(x.details.asset)} · ${esc(x.details.type_ar)}</b>${tierBadge(x.details.tier)}</div><pre>${esc(x.details.text)}</pre></div>`).join("") : '<div class="empty">لا أوامر عمل مولَّدة بعد؛ ولّدها من شاشة الجدولة</div>'; }

/* ------------------------------------------------------------------ ledger */
async function loadLedger() {
  let L; try { L = await api("/ledger/months"); } catch (e) { $("#ledgerTable tbody").innerHTML = `<tr><td colspan="9"><div class="empty">${esc(e.message)}</div></td></tr>`; return; }
  const M = L.months;
  $("#ledgerTable tbody").innerHTML = M.map((m) => `<tr><td>${m.month}</td><td class="num">${m.n_failures}</td><td class="num">${pct(m.pfr["2"])}</td><td class="num">${pct(m.pfr["7"])}</td><td class="num">${pct(m.pfr["14"])}</td><td class="num"><b>${pct(m.pfr.own)}</b></td><td class="num">${pct(m.emergency_share)}</td><td class="num">${fmt(m.dark_days)}</td><td class="num">${pct(m.symptom_capture_rate)}</td></tr>`).join("") || '<tr><td colspan="9"><div class="empty">لا أشهر محسوبة بعد</div></td></tr>';
  $("#ledgerChart").innerHTML = lineChart(M.map((m) => ({ x: m.month.slice(2), y: m.pfr.own })), "PFR@L الخاصة بكل شهر (قوائم معتمدة فقط)");
  const d = L.drift; $("#drift").className = "callout " + (d.status === "drift" ? "bad" : ""); $("#drift").innerHTML = d.status === "drift" ? `<b>انجراف:</b> PFR@L انخفض شهرين متتاليين (${d.last_two.map((v) => pct(v)).join("، ")}) عن المتوسط ${pct(d.baseline)}. إعادة التدريب مطلوبة.` : d.status === "stable" ? `مستقر: المتوسط ${pct(d.baseline)} · آخر شهرين ${d.last_two.map((v) => pct(v)).join("، ")}` : "تاريخ غير كافٍ لفحص الانجراف (" + d.months + " أشهر)";
  const models = await api("/ledger/models");
  $("#modelsTable tbody").innerHTML = models.map((m) => `<tr><td>${esc(m.name)} <span class="mono muted">${m.model_version_id.slice(0, 8)}</span></td><td>${m.created_at.slice(0, 10)}</td><td class="num">${m.metrics.auc?.toFixed(3)}</td><td class="num">${m.metrics.brier?.toFixed(4)}</td><td class="num">${pct(m.metrics.pfr_at_L_validation)}</td><td class="num">${pct(m.metrics.pfr_age_rule_validation)}</td><td>${Object.entries(m.gates).map(([k, g]) => `<span class="gate ${g.pass ? "ok" : ""}">${k}</span>`).join(" ")}</td><td>${m.promoted ? '<span class="badge ok">معتمد</span>' : ""}</td></tr>`).join("");
}

/* ------------------------------------------------------------------ backtest */
async function loadBacktest() {
  try { BT = await api("/ledger/backtest"); } catch (e) { $("#btKpis").innerHTML = `<div class="empty">لا اختبار رجعي بعد. ${ME.role === "admin" ? '<a href="#ops">شغّله من التشغيل</a>' : ""}</div>`; $("#btBars").innerHTML = $("#btSeries").innerHTML = ""; return; }
  $("#topRight").innerHTML = `<span class="badge ${BT.source_note === "simulation" ? "sim" : "ok"}">${BT.source_note === "simulation" ? "بيانات محاكاة" : "بيانات ميدانية"}</span>`;
  const P = BT.pfr_own_L;
  $("#btKpis").innerHTML = kpi("PFR@L — بصيرة", pct(P.baseera), "accent") + kpi("PFR@L — قاعدة العمر", pct(P.age_rule)) + kpi("PFR@L — اليوم", "0%") + kpi("نسبة الطارئ", `${pct(BT.emergency_share.reactive)} ← ${pct(BT.emergency_share.baseera)}`) + kpi("أيام الانطفاء", `${fmt(BT.dark_days.reactive)} ← ${fmt(BT.dark_days.baseera)}`) + kpi("AUC · الدقة@30", `${BT.metrics.auc.toFixed(2)} · ${pct(BT.precision30)}`) + kpi("الأعطال / الأسابيع", `${BT.n_failures} / ${BT.weeks}`) + kpi("تغطية نافذة العطل", BT.window_coverage != null ? pct(BT.window_coverage) + ` <small>(${BT.window_n})</small>` : "—") + kpi("الحد الأعلى النظري", BT.ceiling != null ? pct(BT.ceiling) : "—");
  $("#btBars").innerHTML = barChart(Object.entries(BT.pfr).map(([L, v]) => ({ label: "L=" + L, a: v.baseera, b: v.age_rule })), "PFR@L بحسب المهلة: بصيرة مقابل قاعدة العمر");
  $("#btSeries").innerHTML = lineChart(BT.series.map((s) => ({ x: s.week.slice(5), y: s.failures ? s.anticipated / s.failures : null })), "نسبة الأعطال المُنذَر بها أسبوعيًا");
  $("#btCats tbody").innerHTML = (BT.by_category || []).filter((c) => inCat(c.category)).map((c) => `<tr><td><b>${esc(c.ar)}</b></td><td class="num">${fmt(c.n_assets)}</td><td class="num">${c.n}</td><td class="num"><b>${pct(c.pfr_L)}</b></td><td class="num">${pct(c.pfr_age)}</td><td class="num">${pct(c.emergency_share)}</td></tr>`).join("") || '<tr><td colspan="6" class="muted small">الاختبار الرجعي الحالي سابق لإضافة الفئات؛ أعد تشغيله</td></tr>';
  const modeCat = (m) => (CATALOG.find((c) => c.modes.some((x) => x.code === m)) || {}).key;
  $("#btModes tbody").innerHTML = BT.by_mode.filter((m) => inCat(modeCat(m.mode))).map((m) => `<tr><td>${esc(m.mode_ar)}</td><td>${esc(CAT_AR[(CATALOG.find((c) => c.modes.some((x) => x.code === m.mode)) || {}).key] || "")}</td><td title="${esc(CLASS_AR[m.cls] || "")}">${esc(CLASS_AR[m.cls] || m.cls)}</td><td class="num">${m.n}</td><td class="num">${m.L}</td><td class="num"><b>${pct(m.pfr_L)}</b></td><td class="num">${pct(m.pfr7)}</td><td class="num">${m.median_lead ?? "—"}</td></tr>`).join("");
}

/* ------------------------------------------------------------------ data panel */
async function loadData() {
  $("#topRight").innerHTML = "";
  if (!SCHEMA.length) SCHEMA = await api("/admin/ingest/schema");
  let ov = null; try { ov = await api("/admin/overview"); } catch {}
  $("#pipes").innerHTML = SCHEMA.map((p) => `<div class="pipe ${p.name === PIPE ? "on" : ""}" data-p="${p.name}"><b>${p.order} · ${esc(p.label)}</b><span class="n">${ov ? fmt(ov.tables[p.name].n) : ""}</span><small class="muted">${esc(p.help)}</small></div>`).join("");
  $("#manualPipe").innerHTML = SCHEMA.map((p) => `<option value="${p.name}">${esc(p.label)}</option>`).join("");
  $("#qPipe").innerHTML = '<option value="">كل الخطوط</option>' + SCHEMA.map((p) => `<option value="${p.name}">${esc(p.label)}</option>`).join("");
  if (ov) { $("#qCount").textContent = ov.quarantine_open || ""; }
  selectPipe(PIPE); renderManual($("#manualPipe").value);
  const canEdit = ME.role === "admin"; $("#commit").hidden = !canEdit; $("#drop").style.opacity = canEdit ? 1 : .6;
}
$("#pipes").addEventListener("click", (e) => { const p = e.target.closest(".pipe"); if (p) selectPipe(p.dataset.p); });
function selectPipe(name) {
  PIPE = name; const p = SCHEMA.find((x) => x.name === name); $$(".pipe").forEach((el) => el.classList.toggle("on", el.dataset.p === name));
  $("#upTitle").textContent = p.label; $("#upHelp").textContent = p.help; $("#tplLink").href = `${API}/admin/ingest/${name}/template.csv`; $("#tplLink").onclick = async (e) => { e.preventDefault(); const r = await fetch(`${API}/admin/ingest/${name}/template.csv`, { headers: { Authorization: "Bearer " + TOKEN } }); const b = await r.blob(); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `${name}_template.csv`; a.click(); };
  $("#fields").innerHTML = `<table class="tbl"><thead><tr><th>العمود</th><th>المعنى</th><th>مثال</th><th>ملاحظة</th></tr></thead><tbody>${p.fields.map((f) => `<tr><td><span class="mono">${f.name}</span>${f.required ? ' <span class="crit">إلزامي</span>' : ""}</td><td>${esc(f.label)}</td><td><span class="mono muted">${esc(f.example)}</span></td><td class="small text2">${esc(f.help)}</td></tr>`).join("")}</tbody></table>`;
  resetPreview(); steps(0);
}
function steps(n) { $$("#upSteps li").forEach((li, i) => (li.className = i < n ? "done" : i === n ? "on" : "")); }
function resetPreview() { PREVIEW_FILE = null; $("#preview").className = "empty"; $("#preview").textContent = "ارفع ملفًا لتظهر المعاينة: عدد السطور، ما سيُقبل، وما سيُحجر وسببه."; $("#pvBadge").innerHTML = ""; $("#commit").disabled = true; $("#commitMsg").textContent = ""; $("#sampleCard").hidden = true; }
const drop = $("#drop"); drop.onclick = () => $("#file").click();
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); }; drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) previewFile(e.dataTransfer.files[0]); };
$("#file").onchange = (e) => { if (e.target.files[0]) previewFile(e.target.files[0]); e.target.value = ""; };
async function previewFile(file) {
  if (ME.role !== "admin") return toast("المعاينة والرفع لمدير النظام", "bad");
  steps(1); $("#preview").className = ""; $("#preview").innerHTML = `<p class="text2">جارٍ فحص <b>${esc(file.name)}</b>…</p>`;
  const fd = new FormData(); fd.append("file", file);
  let pv; try { pv = await api(`/admin/ingest/${PIPE}/preview`, { method: "POST", body: fd }); } catch (e) { $("#preview").innerHTML = `<div class="callout bad">${esc(e.message)}</div>`; return; }
  PREVIEW_FILE = file; steps(2);
  const okAll = pv.quarantined === 0 && !pv.missing_required.length;
  $("#pvBadge").innerHTML = `<span class="badge ${okAll ? "ok" : pv.ok ? "warn" : "bad"}">${okAll ? "جاهز" : pv.ok ? "جزئي" : "مرفوض"}</span>`;
  $("#preview").innerHTML = `<div class="kpis" style="margin-bottom:10px">${kpi("السطور", fmt(pv.rows))}${kpi("ستُقبل", fmt(pv.ok), "accent")}${kpi("ستُحجر", fmt(pv.quarantined))}</div>
    ${pv.missing_required.length ? `<div class="callout bad">أعمدة إلزامية ناقصة: <span class="mono">${pv.missing_required.join(", ")}</span></div>` : ""}
    ${pv.unknown_columns.length ? `<div class="callout warn">أعمدة غير معروفة ستُتجاهل: <span class="mono">${esc(pv.unknown_columns.join(", "))}</span></div>` : ""}
    ${pv.reasons.length ? `<h4>أسباب الحجر</h4><table class="tbl">${pv.reasons.map((r) => `<tr><td>${esc(r.reason)}</td><td class="num"><b>${fmt(r.n)}</b></td></tr>`).join("")}</table>` : `<p class="text2 small">كل السطور صالحة.</p>`}`;
  $("#commit").disabled = !(pv.ok > 0); $("#commitMsg").textContent = pv.ok ? `سيُدخل ${fmt(pv.ok)} سطرًا بالمصدر «${$("#source").selectedOptions[0].text}»؛ المحجور يبقى للمراجعة.` : "";
  $("#sampleCard").hidden = false; $("#sample").innerHTML = `<table class="tbl"><thead><tr>${pv.columns.map((c) => `<th><span class="mono">${esc(c)}</span></th>`).join("")}</tr></thead><tbody>${pv.sample.map((r) => `<tr>${pv.columns.map((c) => `<td class="small">${esc(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
$("#commit").onclick = async () => {
  if (!PREVIEW_FILE) return; const fd = new FormData(); fd.append("file", PREVIEW_FILE); $("#commit").disabled = true; $("#commitMsg").textContent = "جارٍ الإدخال…";
  try { const r = await api(`/admin/ingest/${PIPE}/run?source=${$("#source").value}`, { method: "POST", body: fd }); steps(4); toast(`أُدخل ${fmt(r.n_ok)} سطرًا؛ ${fmt(r.n_quarantined)} في الحجر`, "ok"); $("#commitMsg").innerHTML = `تم: ${fmt(r.n_ok)} مقبول · ${fmt(r.n_quarantined)} محجور. <a href="#ops">أعد الحساب</a> ليظهر الأثر في القائمة.`; PREVIEW_FILE = null; loadData(); }
  catch (e) { toast(e.message, "bad"); $("#commit").disabled = false; }
};
$("#dataTabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $$("#dataTabs button").forEach((x) => x.classList.toggle("on", x === b)); ["upload", "manual", "quarantine", "runs", "catalog", "glossary"].forEach((t) => ($("#d-" + t).hidden = t !== b.dataset.t)); if (b.dataset.t === "quarantine") loadQuarantine(); if (b.dataset.t === "runs") loadRuns(); if (b.dataset.t === "catalog") renderCatalog(); if (b.dataset.t === "glossary") loadGlossary($("#glossaryBody")); });
function renderCatalog() {
  $("#catalogBody").innerHTML = CATALOG.filter((c) => inCat(c.key)).map((c) => `<div class="card" style="margin-bottom:12px"><div class="hd"><h3>${esc(c.ar)} <span class="badge ${c.status === "pilot" ? "ok" : "info"}">${STATUS_CAT[c.status]}</span></h3><span class="small text2">${esc(c.status_ar)}</span></div>
    <div class="grid g3"><div><h4>أنواع الأصول</h4><table class="tbl">${c.types.map((t) => `<tr><td><span class="mono">${t.code}</span></td><td>${esc(t.ar)}</td><td class="num small">${t.design_life_y} سنة · ${fmt(t.cost_planned)} ر.س</td></tr>`).join("")}</table></div>
    <div><h4>أنماط العطل (الصنف · المهلة L)</h4><table class="tbl">${c.modes.map((m) => `<tr><td><span class="mono">${m.code}</span></td><td>${esc(m.ar)}</td><td class="num small">${m.cls} · ${m.L} يوم</td></tr>`).join("")}</table></div>
    <div><h4>العلامات المرصودة</h4><table class="tbl">${c.symptoms.map((s) => `<tr><td><span class="mono">${s.code}</span></td><td>${esc(s.ar)}</td></tr>`).join("")}</table>
    ${c.channels && c.channels.length ? `<h4 style="margin-top:8px">قنوات الإشارات</h4><table class="tbl">${c.channels.map((ch) => `<tr><td><span class="mono">${ch.code}</span></td><td>${esc(ch.ar)} <small class="muted">${esc(ch.unit)} · ${esc(ch.source)}</small></td></tr>`).join("")}</table>` : ""}</div></div></div>`).join("");
}
let GLOSS = null;
async function loadGlossary(target) {
  $("#topRight").innerHTML = "";
  if (!GLOSS) GLOSS = await api("/admin/glossary");
  const G = GLOSS, tbl = (rows, cols) => `<table class="tbl">${rows.map((r) => `<tr>${cols.map((c, k) => `<td class="${k === 0 ? "" : "small"}">${k === 0 ? `<span class="mono">${esc(r[c])}</span>` : esc(r[c] ?? "")}</td>`).join("")}</tr>`).join("")}</table>`;
  const card = (title, body, note) => `<div class="card" style="margin-bottom:12px"><div class="hd"><h3>${title}</h3>${note ? `<span class="small text2">${note}</span>` : ""}</div>${body}</div>`;
  target.innerHTML = `
    <div class="callout">هذا الدليل يعرّف كل رمز يظهر في المنصة بالعربية. الرموز الإنجليزية ثابتة في قاعدة البيانات والملفات المرفوعة (حتى تبقى قابلة للتبادل مع أنظمة الجهة)، والتسمية العربية هي ما يراه المشرف والفني.</div>
    <div class="grid g2">
      ${card("بادئات رموز الأصول", tbl(G.code_prefixes, ["code", "ar"]), "LP-10001 · CB-01 · PS-32 · EL-7 · PV-143")}
      ${card("أصناف الأصول (kind)", tbl(G.kinds, ["code", "ar"]))}
      ${card("تصنيف الشارع والموقع الحرج", tbl([...G.streets, ...G.criticality], ["code", "ar"]), "يدخلان في العواقب والأولوية")}
      ${card("فئات أنماط العطل أ/ب/ج", tbl(G.classes, ["code", "ar", "desc"]), "بحسب فترة P–F والمهلة L")}
      ${card("فئات الأولوية", tbl(G.tiers, ["code", "ar", "desc"]))}
      ${card("الإجراءات", tbl(G.actions, ["code", "ar", "desc"]))}
      ${card("حالات بند القائمة", tbl(G.statuses, ["code", "ar"]))}
      ${card("نتائج الزيارة (تطبيق الفني)", tbl(G.findings, ["code", "ar"]))}
      ${card("مصادر البيانات", tbl(G.sources, ["code", "ar"]))}
      ${card("أنواع البلاغات وأوامر العمل", tbl([...G.report_types, ...G.work_order_kinds], ["code", "ar"]))}
    </div>
    ${card("قنوات الإشارات (مراقبة الحالة)", tbl(G.channels, ["code", "ar", "unit", "category_ar", "source_ar", "direction"]), "تجميع يومي لكل أصل")}
    ${card("المؤشرات والمصطلحات", tbl(G.metrics, ["code", "ar"]))}
    ${card("قطع الغيار وخطوات العمل لكل نمط عطل", tbl(G.parts, ["mode", "mode_ar", "parts", "checklist", "hours"]), "ما يُطبع في أمر العمل المولَّد")}
    <p class="small muted">أنواع الأصول وأنماط العطل والعلامات لكل فئة: في تبويب «كتالوج الأصول» بلوحة المدخلات. الأسماء العربية كلها في ملف واحد يمكن للجهة تعديله: core/catalog.py.</p>`;
}
$("#manualPipe").onchange = (e) => renderManual(e.target.value);
function renderManual(name) {
  const p = SCHEMA.find((x) => x.name === name); if (!p) return; $("#manualHelp").textContent = p.help;
  $("#manualForm").innerHTML = p.fields.map((f) => `<div><label>${esc(f.label)}${f.required ? " *" : ""}</label><input name="${f.name}" placeholder="${esc(f.example)}" ${f.required ? "required" : ""}><small class="muted">${esc(f.help)}</small></div>`).join("");
  $("#manualMsg").textContent = "";
}
$("#manualSave").onclick = async () => {
  const row = Object.fromEntries(new FormData($("#manualForm")).entries());
  try { await api(`/admin/records/${$("#manualPipe").value}`, { method: "POST", body: JSON.stringify({ row, source: $("#source").value }) }); $("#manualMsg").innerHTML = '<span class="badge ok">حُفظ</span>'; toast("حُفظ السجل", "ok"); $("#manualForm").reset(); }
  catch (e) { $("#manualMsg").innerHTML = `<span class="badge bad">رُفض</span> ${esc(e.message)}`; }
};
async function loadQuarantine() {
  const q = await api(`/admin/quarantine?limit=200${$("#qPipe").value ? "&pipeline=" + $("#qPipe").value : ""}`); $("#qCount").textContent = q.n || "";
  $("#qTable tbody").innerHTML = q.items.map((r) => `<tr data-id="${r.row_id}" data-p="${r.pipeline}"><td class="num">${r.row_id}</td><td>${esc(PIPE_AR(r.pipeline))}</td><td class="reason">${esc(r.reason)}</td><td><span class="mono small">${esc(JSON.stringify(r.payload)).slice(0, 140)}</span></td><td class="small">${dt(r.received)}</td><td class="actions">${ME.role === "admin" ? '<button class="btn sm" data-q="fix">تصحيح وإعادة</button><button class="btn ghost sm" data-q="close">إغلاق</button>' : ""}</td></tr>`).join("") || '<tr><td colspan="6"><div class="empty">لا سطور محجورة</div></td></tr>';
}
const PIPE_AR = (n) => (SCHEMA.find((x) => x.name === n) || { label: n }).label;
$("#qPipe").onchange = loadQuarantine; $("#qReload").onclick = loadQuarantine;
$("#qTable").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-q]"); if (!b) return; const tr = b.closest("tr"), id = tr.dataset.id, name = tr.dataset.p;
  if (b.dataset.q === "close") return modal(`<h3>إغلاق السطر #${id}</h3><label>ملاحظة</label><input id="qNote">`, async (m) => { await api(`/admin/quarantine/${id}/resolve`, { method: "POST", body: JSON.stringify({ note: $("#qNote", m).value }) }); loadQuarantine(); });
  const q = await api(`/admin/quarantine?limit=1&unresolved=false&pipeline=${name}`); const row = (await api(`/admin/quarantine?limit=200&pipeline=${name}`)).items.find((x) => String(x.row_id) === id) || q.items[0];
  const p = SCHEMA.find((x) => x.name === name);
  modal(`<h3>تصحيح السطر #${id}</h3><p class="small text2">${esc(row.reason)}</p><div class="form-grid">${p.fields.map((f) => `<div><label>${esc(f.label)}</label><input name="${f.name}" value="${esc(row.payload[f.name] ?? "")}"></div>`).join("")}</div>`,
    async (m) => { const payload = Object.fromEntries($$("input[name]", m).map((i) => [i.name, i.value])); await api(`/admin/quarantine/${id}/retry`, { method: "POST", body: JSON.stringify({ payload, source: $("#source").value }) }); toast("أُعيد إدخال السطر", "ok"); loadQuarantine(); });
});
async function loadRuns() { const r = await api("/admin/ingest/runs"); $("#runsTable tbody").innerHTML = r.map((x) => `<tr><td class="small">${dt(x.started)}</td><td>${esc(PIPE_AR(x.pipeline))}</td><td class="num">${fmt(x.n_in)}</td><td class="num">${fmt(x.n_ok)}</td><td class="num">${x.n_quarantined ? `<span class="badge warn">${fmt(x.n_quarantined)}</span>` : "0"}</td></tr>`).join("") || '<tr><td colspan="5"><div class="empty">لا عمليات بعد</div></td></tr>'; }

/* ------------------------------------------------------------------ params */
async function loadParams() {
  $("#topRight").innerHTML = ""; PARAMS = await api("/admin/params"); const canEdit = ME.role === "admin"; $("#paramsSave").hidden = $("#paramsReset").hidden = !canEdit;
  const groups = [...new Set(PARAMS.map((p) => p.group))];
  $("#paramGroups").innerHTML = groups.map((g) => `<div class="card" style="margin-bottom:12px"><div class="hd"><h3>${esc(g)}</h3></div>${PARAMS.filter((p) => p.group === g).map((p) => `<div class="param"><div class="lbl"><b>${esc(p.label)} ${p.overridden ? '<span class="badge info">معاير</span>' : ""}</b><small>${esc(p.help)}${p.overridden ? ` · عدّله ${esc(p.updated_by)} في ${dt(p.updated_at)}` : ""}</small></div><div>${inputFor(p, canEdit)}</div><div class="dflt">الافتراضي: ${esc(fmtVal(p.default))}</div></div>`).join("")}</div>`).join("");
}
const fmtVal = (v) => (typeof v === "object" ? Object.entries(v).map(([k, x]) => `${k}=${x}`).join(" ") : String(v));
function inputFor(p, canEdit) {
  const dis = canEdit ? "" : "disabled";
  if (p.type.startsWith("dict")) return `<div class="stack" style="gap:4px">${Object.entries(p.value).map(([k, v]) => `<label class="row" style="gap:6px;margin:0"><span class="mono" style="width:90px">${k}</span><input data-k="${p.key}" data-sub="${k}" type="number" step="any" value="${v}" ${dis}></label>`).join("")}</div>`;
  return `<input data-k="${p.key}" type="number" step="${p.type === "int" ? 1 : "any"}" value="${p.value}" ${dis}>`;
}
$("#paramsSave").onclick = async () => {
  const values = {};
  for (const p of PARAMS) {
    if (p.type.startsWith("dict")) { const d = {}; $$(`input[data-k="${p.key}"]`).forEach((i) => (d[i.dataset.sub] = +i.value)); if (JSON.stringify(d) !== JSON.stringify(p.value)) values[p.key] = d; }
    else { const v = +$(`input[data-k="${p.key}"]`).value; if (v !== p.value) values[p.key] = v; }
  }
  if (!Object.keys(values).length) return toast("لا تغييرات");
  try { const r = await api("/admin/params", { method: "PATCH", body: JSON.stringify({ values }) }); toast(`حُفظ ${Object.keys(r.changed).length} معامل`, "ok"); $("#paramsMsg").innerHTML = 'لتطبيق التغيير على القائمة: <a href="#ops">أعد الحساب</a>.'; loadParams(); } catch (e) { toast(e.message, "bad"); }
};
$("#paramsReset").onclick = () => modal("<h3>إعادة كل المعاملات إلى الافتراضيات؟</h3>", async () => { await api("/admin/params/reset", { method: "POST", body: JSON.stringify({}) }); loadParams(); });

/* ------------------------------------------------------------------ ops / jobs */
const JOB_AR = { recompute: "إعادة الحساب الكاملة", features: "الخصائص", train: "التدريب", plan: "قائمة الأسبوع", ledger: "السجل", backtest: "الاختبار الرجعي", seed_sim: "محاكاة", purge: "مسح البيانات" };
const STATUS_AR = { queued: "في الانتظار", running: "جارٍ", done: "اكتمل", failed: "فشل" };
async function loadOps() {
  $("#topRight").innerHTML = ""; if (!$("#asOf").value) $("#asOf").value = new Date().toISOString().slice(0, 10);
  $$("[data-job]").forEach((b) => (b.disabled = ME.role !== "admin")); $("#purge").disabled = ME.role !== "admin";
  await refreshJobs(); JOBPOLL = setInterval(refreshJobs, 2500);
  const a = await api("/admin/audit?limit=60"); $("#auditTable tbody").innerHTML = a.map((x) => `<tr><td class="small">${dt(x.at)}</td><td>${esc(x.actor)}</td><td><span class="mono">${esc(x.action)}</span></td><td class="small">${esc(x.entity)} ${esc((x.entity_id || "").slice(0, 8))}</td><td class="small text2">${esc(JSON.stringify(x.after || {})).slice(0, 120)}</td></tr>`).join("");
}
async function refreshJobs() {
  const jobs = await api("/admin/jobs?limit=15"); const j = jobs[0];
  $("#jobsTable tbody").innerHTML = jobs.map((x) => `<tr><td class="small">${dt(x.created_at)}</td><td>${JOB_AR[x.kind] || x.kind}</td><td>${esc(x.created_by)}</td><td><span class="badge ${{ done: "ok", failed: "bad", running: "info", queued: "" }[x.status]}">${STATUS_AR[x.status]}</span></td><td class="small text2">${x.error ? esc(x.error.split("\n")[0]).slice(0, 100) : esc(JSON.stringify(x.result || {})).slice(0, 120)}</td></tr>`).join("") || '<tr><td colspan="5"><div class="empty">لا مهام بعد</div></td></tr>';
  if (!j) { $("#jobBadge").textContent = "لا مهام"; return; }
  $("#jobBadge").className = "badge " + ({ done: "ok", failed: "bad", running: "info", queued: "" }[j.status]); $("#jobBadge").textContent = `${JOB_AR[j.kind] || j.kind} · ${STATUS_AR[j.status]}`;
  $("#jobBar").style.width = j.progress + "%"; $("#jobStep").textContent = j.step || ""; $("#jobLog").innerHTML = (j.log || []).map((l) => `<div>${esc(l)}</div>`).join("");
  $("#jobResult").innerHTML = j.status === "failed" ? `<div class="callout bad"><pre style="white-space:pre-wrap;margin:0;direction:ltr;text-align:left;font-size:11.5px">${esc(j.error)}</pre></div>` : j.status === "done" && j.result ? `<div class="callout">${esc(JSON.stringify(j.result)).slice(0, 600)}</div>` : "";
  const busy = ["queued", "running"].includes(j.status); $$("[data-job]").forEach((b) => (b.disabled = busy || ME.role !== "admin"));
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-job]"); if (!b) return;
  const kind = b.dataset.job, params = { as_of: $("#asOf").value };
  if (kind === "seed_sim") { params.poles = +$("#simPoles").value; params.cabinets = +$("#simCab").value; }
  try { await api(`/admin/jobs/${kind}`, { method: "POST", body: JSON.stringify({ params }) }); toast("بدأت المهمة"); refreshJobs(); } catch (err) { toast(err.message, "bad"); }
});
$("#purge").onclick = () => modal(`<h3>مسح كل البيانات التشغيلية؟</h3><p class="text2">تُحذف الأصول والبلاغات وأوامر العمل والعلامات والنماذج والقوائم. المستخدمون والمعاملات وسجل التدقيق تبقى. اكتب <span class="mono">PURGE</span> للتأكيد.</p><input id="purgeConfirm" placeholder="PURGE">`,
  async (m) => { await api("/admin/jobs/purge", { method: "POST", body: JSON.stringify({ params: { confirm: $("#purgeConfirm", m).value } }) }); toast("بدأ المسح"); refreshJobs(); });

/* ------------------------------------------------------------------ tiny SVG charts (no library) */
function lineChart(pts, title) {
  const W = 900, H = 240, p = 36, xs = pts.length;
  const path = pts.map((d, i) => d.y == null ? "" : `${i ? "L" : "M"}${p + (i * (W - 2 * p)) / Math.max(1, xs - 1)},${H - p - d.y * (H - 2 * p)}`).join(" ");
  const grid = [0, 0.25, 0.5, 0.75, 1].map((g) => `<line x1="${p}" x2="${W - p}" y1="${H - p - g * (H - 2 * p)}" y2="${H - p - g * (H - 2 * p)}" class="gridl"/><text x="${p - 6}" y="${H - p - g * (H - 2 * p) + 4}" class="tick">${g * 100}%</text>`).join("");
  const labels = pts.map((d, i) => i % Math.ceil(xs / 12) ? "" : `<text x="${p + (i * (W - 2 * p)) / Math.max(1, xs - 1)}" y="${H - 8}" class="tick mid">${esc(d.x)}</text>`).join("");
  return `<h4>${esc(title)}</h4><svg viewBox="0 0 ${W} ${H}" direction="ltr">${grid}<path d="${path}" class="line"/>${labels}</svg>`;
}
function barChart(rows, title) {
  const W = 900, H = 240, p = 36, bw = (W - 2 * p) / rows.length;
  const bars = rows.map((r, i) => { const x = p + i * bw; return `<rect x="${x + bw * 0.15}" y="${H - p - r.a * (H - 2 * p)}" width="${bw * 0.3}" height="${r.a * (H - 2 * p)}" class="a"/><rect x="${x + bw * 0.5}" y="${H - p - r.b * (H - 2 * p)}" width="${bw * 0.3}" height="${r.b * (H - 2 * p)}" class="b"/><text x="${x + bw / 2}" y="${H - 8}" class="tick mid">${esc(r.label)}</text><text x="${x + bw * 0.3}" y="${H - p - r.a * (H - 2 * p) - 4}" class="tick mid">${pct(r.a)}</text><text x="${x + bw * 0.65}" y="${H - p - r.b * (H - 2 * p) - 4}" class="tick mid">${pct(r.b)}</text>`; }).join("");
  return `<h4>${esc(title)} <small class="muted">■ بصيرة ▫ قاعدة العمر</small></h4><svg viewBox="0 0 ${W} ${H}" direction="ltr">${bars}</svg>`;
}

/* The technician PWA used to be cache-first; a stale worker could keep serving an old shell. Clear it from here once —
   the PWA registers its new network-first worker on its next open. Idempotent and harmless when nothing is registered. */
(async () => { try { if ("serviceWorker" in navigator) { const rs = await navigator.serviceWorker.getRegistrations(); for (const r of rs) await r.unregister(); } if (window.caches) { for (const k of await caches.keys()) await caches.delete(k); } } catch {} })();

if (TOKEN) boot();
