/* Baseera platform app — vanilla JS, no build step. Every number comes from the API. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const API = "/api";
let TOKEN = localStorage.getItem("baseera.token"), ME = null, ASSETS = [], CUR = null, BT = null, SCHEMA = [], PIPE = "assets", PREVIEW_FILE = null, PARAMS = [], JOBPOLL = null;
const fmt = (x, d = 0) => (x == null ? "—" : Number(x).toLocaleString("en", { maximumFractionDigits: d }));
const pct = (x, d = 0) => (x == null ? "—" : (100 * x).toFixed(d) + "%");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dt = (s) => (s ? s.replace("T", " ").slice(0, 16) : "—");
const TITLES = { home: "لوحة المتابعة", week: "قائمة الأسبوع", map: "خريطة الخطر", ledger: "سجل قابلية التنبؤ", backtest: "الاختبار الرجعي", data: "البيانات والمدخلات", params: "معاملات التشغيل", ops: "التشغيل والمهام", method: "المنهجية" };
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
  loadAssets(); route();
}
window.addEventListener("hashchange", route);
function route() {
  let h = (location.hash || "#home").slice(1);
  const link = $(`#nav a[href="#${h}"]`); if (link && link.hidden) { h = "home"; location.hash = "#home"; }
  $$(".view").forEach((v) => (v.hidden = v.id !== "v-" + h));
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + h));
  $("#title").textContent = TITLES[h] || ""; $("#crumbs").textContent = "بصيرة / " + (TITLES[h] || "");
  clearInterval(JOBPOLL);
  ({ home: loadHome, week: loadWeek, map: () => loadAssets().then(drawMap), ledger: loadLedger, backtest: loadBacktest, data: loadData, params: loadParams, ops: loadOps }[h] || (() => {}))();
}

/* ------------------------------------------------------------------ home */
async function loadHome() {
  const canAdmin = ["admin", "manager"].includes(ME.role);
  let ov = null; if (canAdmin) { try { ov = await api("/admin/overview"); } catch {} }
  try { CUR = await api("/weekly-lists/current"); } catch { CUR = null; }
  let L = null; try { L = await api("/ledger/months"); } catch {}
  const last = L?.months?.filter((m) => m.n_failures).slice(-1)[0];
  $("#homeKpis").innerHTML = kpi("أصول تحت المراقبة", fmt(ov ? ov.tables.assets.n : ASSETS.length)) + kpi("قائمة الأسبوع", CUR ? `${CUR.items.length} <small>بند · ${CUR.status === "approved" ? "معتمدة" : "مقترحة"}</small>` : "—")
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
  $("#weekTable tbody").innerHTML = CUR.items.map((i) => `<tr data-id="${i.item_id}" class="${i.status}">
    <td class="num">${i.rank}</td><td><a href="#map" data-asset="${i.asset_id}">${esc(i.code)}</a>${i.crit !== "none" ? ' <span class="crit">' + esc(CRIT_AR[i.crit] || i.crit) + "</span>" : ""}</td>
    <td>${esc(i.type)}</td><td>${i.street === "main" ? "رئيسي" : "فرعي"}</td><td class="num"><span class="bar"><i class="${i.p >= .35 ? "hi" : i.p >= .1 ? "md" : ""}" style="width:${Math.min(100, i.p * 100)}%"></i></span>${pct(i.p)}</td>
    <td class="num">${fmt(i.risk_sar)}</td><td><b>${esc(i.action_ar)}</b></td><td class="reason">${esc(i.reason)}</td>
    <td>${statusAr(i)}</td><td class="actions">${ME.role === "supervisor" && i.status === "proposed" ? `<button class="btn sm" data-act="approved">اعتماد</button><button class="btn ghost sm" data-act="overridden">تجاوز</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="10"><div class="empty">لا أصول فوق عتبة الإنذار هذا الأسبوع</div></td></tr>';
  const sumRisk = CUR.items.reduce((s, i) => s + i.risk_sar, 0);
  $("#kpis").innerHTML = kpi("الأصول في القائمة", CUR.items.length) + kpi("الخطر المتوقع (ر.س)", fmt(sumRisk), "accent") + kpi("احتمال أعلى بند", pct(CUR.items[0]?.p)) + kpi("الحالة", CUR.status === "approved" ? "معتمدة" : "مقترحة");
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
    const [x, y] = MAPT(a); ctx.fillStyle = riskColor(a.p);
    if (a.kind === "cabinet") ctx.fillRect(x - 6, y - 6, 12, 12); else { ctx.beginPath(); ctx.arc(x, y, a.listed ? 5 : 3, 0, 7); ctx.fill(); }
    if (a.listed) { ctx.strokeStyle = "#152230"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(x, y - 9); ctx.lineTo(x + 9, y); ctx.lineTo(x, y + 9); ctx.lineTo(x - 9, y); ctx.closePath(); ctx.stroke(); }
  }
}
$("#map").addEventListener("click", (e) => {
  const r = e.target.getBoundingClientRect(), x = (e.clientX - r.left) * (e.target.width / r.width), y = (e.clientY - r.top) * (e.target.height / r.height);
  let best = null, bd = 1e9; for (const a of ASSETS) { const [ax, ay] = MAPT(a); const d = (ax - x) ** 2 + (ay - y) ** 2; if (d < bd) { bd = d; best = a; } }
  if (best && bd < 400) showCard(best.asset_id);
});
document.addEventListener("click", (e) => { const a = e.target.closest("a[data-asset]"); if (a) setTimeout(() => showCard(a.dataset.asset), 60); });
async function showCard(id) {
  const c = await api("/assets/" + id); const p = c.prediction, ex = p?.explanation || {};
  $("#detail").innerHTML = `<h3>${esc(c.code)} <small class="muted">${esc(c.type)} · ${c.street === "main" ? "رئيسي" : "فرعي"} · ${esc(CRIT_AR[c.crit] || "")}</small></h3>
    <div class="kv" style="margin-top:8px"><span>الخزانة</span><b>${esc(c.cabinet || "—")}</b><span>التركيب</span><b>${esc(c.install || "—")}</b><span>الاحتمال 14 يومًا</span><b style="color:${riskColor(p?.p)}">${pct(p?.p, 1)}</b><span>الخطر (ر.س)</span><b>${fmt(p?.risk_sar)}</b><span>المصدر</span><b><span class="badge ${c.source === "simulated" ? "sim" : "ok"}">${c.source === "simulated" ? "محاكاة" : esc(c.source)}</span></b></div>
    ${c.list_item ? `<p style="margin-top:8px"><span class="badge info">في قائمة الأسبوع #${c.list_item.rank} · ${esc(c.list_item.action)} · ${esc(c.list_item.status)}</span></p><p class="reason">${esc(c.list_item.reason)}</p>` : ""}
    ${Object.keys(ex).length ? `<h4 style="margin-top:10px">لماذا هذا الاحتمال</h4><ul class="expl">${Object.entries(ex).sort((a, b) => b[1] - a[1]).map(([g, v]) => `<li><span>${esc(GROUP_AR[g] || g)}</span><i style="width:${Math.max(2, Math.abs(v) * 300)}px;background:${v >= 0 ? "#c0392b" : "#1f8a5b"}"></i>${(v * 100).toFixed(1)} نقطة</li>`).join("")}</ul>` : ""}
    <h4 style="margin-top:10px">العلامات المسجّلة</h4>${c.observations.length ? `<ul class="plain">${c.observations.slice(0, 5).map((o) => `<li>${o.at.slice(0, 10)} · ${esc(o.symptom)} · شدة ${o.severity} · ${esc(o.source)}</li>`).join("")}</ul>` : '<p class="muted small">لا علامات</p>'}
    <h4 style="margin-top:10px">الأعطال السابقة</h4>${c.failures.length ? `<ul class="plain">${c.failures.map((f) => `<li>${f.on} · ${esc(f.mode || "?")} · ${f.lead == null ? "بلا إنذار" : "إنذار قبل " + f.lead + " يومًا"}</li>`).join("")}</ul>` : '<p class="muted small">لا أعطال مسجّلة</p>'}
    <p class="muted small">النموذج <span class="mono">${esc((p?.model_version_id || "").slice(0, 8))}</span></p>`;
}
const GROUP_AR = { symptoms: "أعراض مرصودة على الأصل", network: "انقطاعات جزئية على الدائرة", weather: "الحرارة والأمطار", history: "سجل الأعطال السابقة", asset: "عمر الأصل ونوعه" };

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
  $("#btKpis").innerHTML = kpi("PFR@L — بصيرة", pct(P.baseera), "accent") + kpi("PFR@L — قاعدة العمر", pct(P.age_rule)) + kpi("PFR@L — اليوم", "0%") + kpi("نسبة الطارئ", `${pct(BT.emergency_share.reactive)} ← ${pct(BT.emergency_share.baseera)}`) + kpi("أيام الانطفاء", `${fmt(BT.dark_days.reactive)} ← ${fmt(BT.dark_days.baseera)}`) + kpi("AUC · الدقة@30", `${BT.metrics.auc.toFixed(2)} · ${pct(BT.precision30)}`) + kpi("الأعطال / الأسابيع", `${BT.n_failures} / ${BT.weeks}`);
  $("#btBars").innerHTML = barChart(Object.entries(BT.pfr).map(([L, v]) => ({ label: "L=" + L, a: v.baseera, b: v.age_rule })), "PFR@L بحسب المهلة: بصيرة مقابل قاعدة العمر");
  $("#btSeries").innerHTML = lineChart(BT.series.map((s) => ({ x: s.week.slice(5), y: s.failures ? s.anticipated / s.failures : null })), "نسبة الأعطال المُنذَر بها أسبوعيًا");
  $("#btModes tbody").innerHTML = BT.by_mode.map((m) => `<tr><td>${esc(m.mode_ar)}</td><td>${m.cls}</td><td class="num">${m.n}</td><td class="num">${m.L}</td><td class="num"><b>${pct(m.pfr_L)}</b></td><td class="num">${pct(m.pfr7)}</td><td class="num">${m.median_lead ?? "—"}</td></tr>`).join("");
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
$("#dataTabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $$("#dataTabs button").forEach((x) => x.classList.toggle("on", x === b)); ["upload", "manual", "quarantine", "runs"].forEach((t) => ($("#d-" + t).hidden = t !== b.dataset.t)); if (b.dataset.t === "quarantine") loadQuarantine(); if (b.dataset.t === "runs") loadRuns(); });
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

if (TOKEN) boot();
