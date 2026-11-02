/* Baseera supervisor app — vanilla JS, no build step. All numbers come from the API. */
const $ = (s, el = document) => el.querySelector(s);
const API = "/api";
let TOKEN = localStorage.getItem("baseera.token"), ME = null, ASSETS = [], CUR = null, BT = null;
const fmt = (x, d = 0) => (x == null ? "—" : Number(x).toLocaleString("en", { maximumFractionDigits: d }));
const pct = (x, d = 0) => (x == null ? "—" : (100 * x).toFixed(d) + "%");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opt = {}) {
  const r = await fetch(API + path, { ...opt, headers: { "Content-Type": "application/json", ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}), ...(opt.headers || {}) } });
  if (r.status === 401) { logout(); throw new Error("unauthorised"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function logout() { TOKEN = null; localStorage.removeItem("baseera.token"); $("#app").hidden = true; $("#login").hidden = false; }

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const r = await fetch(API + "/auth/login", { method: "POST", body: new URLSearchParams(fd) });
  if (!r.ok) { alert("بيانات الدخول غير صحيحة"); return; }
  const t = await r.json(); TOKEN = t.access_token; localStorage.setItem("baseera.token", TOKEN); boot();
});
$("#logout").onclick = logout;

async function boot() {
  try { ME = await api("/auth/me"); } catch { return; }
  $("#who").textContent = ME.display_name + " · " + ME.role;
  $("#login").hidden = true; $("#app").hidden = false;
  await Promise.all([loadWeek(), loadAssets()]);
  route();
}

/* ------------------------------------------------------------------ routing */
window.addEventListener("hashchange", route);
function route() {
  const h = (location.hash || "#week").slice(1);
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== "v-" + h));
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + h));
  if (h === "map") drawMap();
  if (h === "ledger") loadLedger();
  if (h === "backtest") loadBacktest();
}

/* ------------------------------------------------------------------ weekly list */
async function loadWeek() {
  try { CUR = await api("/weekly-lists/current"); } catch (e) { $("#weekTable tbody").innerHTML = `<tr><td colspan="10" class="muted">${esc(e.message)}</td></tr>`; return; }
  $("#weekDate").textContent = "أسبوع " + CUR.week_start;
  $("#capacity").textContent = `${CUR.used} / ${CUR.capacity} طاقة الطاقم · ${CUR.status === "approved" ? "معتمدة" : "مقترحة"}`;
  $("#approveAll").hidden = ME.role !== "supervisor" || CUR.status === "approved";
  const rows = CUR.items.map((i) => `<tr data-id="${i.item_id}" class="${i.status}">
    <td>${i.rank}</td><td><a href="#map" data-asset="${i.asset_id}">${esc(i.code)}</a>${i.crit !== "none" ? ' <span class="crit">' + esc(i.crit) + "</span>" : ""}</td>
    <td>${esc(i.type)}</td><td>${i.street === "main" ? "رئيسي" : "فرعي"}</td><td><span class="bar"><i style="width:${Math.min(100, i.p * 100)}%"></i></span> ${pct(i.p)}</td>
    <td>${fmt(i.risk_sar)}</td><td><b>${esc(i.action_ar)}</b></td><td class="reason">${esc(i.reason)}</td>
    <td>${statusAr(i)}</td><td class="actions">${ME.role === "supervisor" && i.status === "proposed" ? `<button data-act="approved">اعتماد</button><button class="ghost" data-act="overridden">تجاوز</button>` : ""}</td></tr>`).join("");
  $("#weekTable tbody").innerHTML = rows || '<tr><td colspan="10" class="muted">لا أصول فوق عتبة الإنذار هذا الأسبوع</td></tr>';
  const sumRisk = CUR.items.reduce((s, i) => s + i.risk_sar, 0);
  $("#kpis").innerHTML = kpi("الأصول في القائمة", CUR.items.length) + kpi("الخطر المتوقع (ر.س)", fmt(sumRisk)) + kpi("احتمال أعلى بند", pct(CUR.items[0]?.p)) + kpi("الحالة", CUR.status === "approved" ? "معتمدة" : "مقترحة");
}
const statusAr = (i) => ({ proposed: "مقترح", approved: "معتمد", overridden: "تجاوز: " + esc(i.override_reason || ""), done: "منفّذ · " + esc(i.outcome?.finding || ""), skipped: "مُلغى" }[i.status] || i.status);
const kpi = (l, v) => `<div class="kpi"><span>${l}</span><b>${v}</b></div>`;
$("#weekTable").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-act]"); if (!b) return;
  const id = e.target.closest("tr").dataset.id; const status = b.dataset.act; let body = { status };
  if (status === "overridden") { const reason = prompt("سبب التجاوز (إلزامي):"); if (!reason) return; const action = prompt("الإجراء البديل: inspect / service / replace", "inspect"); body = { status, override_reason: reason, action }; }
  try { await api(`/weekly-lists/items/${id}`, { method: "PATCH", body: JSON.stringify(body) }); await loadWeek(); } catch (err) { alert(err.message); }
});
$("#approveAll").onclick = async () => { if (!confirm("اعتماد كل البنود المقترحة؟")) return; await api(`/weekly-lists/${CUR.list_id}/approve`, { method: "POST" }); await loadWeek(); };

/* ------------------------------------------------------------------ map */
async function loadAssets() { try { ASSETS = (await api("/assets?limit=20000")).items; } catch { ASSETS = []; } }
const riskColor = (p) => (p == null ? "#6c6f93" : p >= 0.35 ? "#e5484d" : p >= 0.1 ? "#f2b84b" : "#2bb673");
let MAPT = null;
function drawMap() {
  const c = $("#map"), ctx = c.getContext("2d"); if (!ASSETS.length) return;
  const lons = ASSETS.map((a) => a.lon), lats = ASSETS.map((a) => a.lat);
  const x0 = Math.min(...lons), x1 = Math.max(...lons), y0 = Math.min(...lats), y1 = Math.max(...lats);
  const pad = 30, sx = (c.width - 2 * pad) / (x1 - x0 || 1), sy = (c.height - 2 * pad) / (y1 - y0 || 1), s = Math.min(sx, sy);
  MAPT = (a) => [pad + (a.lon - x0) * s, c.height - pad - (a.lat - y0) * s];
  ctx.fillStyle = "#15142f"; ctx.fillRect(0, 0, c.width, c.height);
  for (const a of ASSETS) {
    const [x, y] = MAPT(a); ctx.fillStyle = riskColor(a.p);
    if (a.kind === "cabinet") { ctx.fillRect(x - 6, y - 6, 12, 12); } else { ctx.beginPath(); ctx.arc(x, y, a.listed ? 5 : 3, 0, 7); ctx.fill(); }
    if (a.listed) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(x, y - 9); ctx.lineTo(x + 9, y); ctx.lineTo(x, y + 9); ctx.lineTo(x - 9, y); ctx.closePath(); ctx.stroke(); }
  }
}
$("#map").addEventListener("click", (e) => {
  const r = e.target.getBoundingClientRect(), x = (e.clientX - r.left) * (e.target.width / r.width), y = (e.clientY - r.top) * (e.target.height / r.height);
  let best = null, bd = 1e9; for (const a of ASSETS) { const [ax, ay] = MAPT(a); const d = (ax - x) ** 2 + (ay - y) ** 2; if (d < bd) { bd = d; best = a; } }
  if (best && bd < 400) showCard(best.asset_id);
});
document.addEventListener("click", (e) => { const a = e.target.closest("a[data-asset]"); if (a) { setTimeout(() => showCard(a.dataset.asset), 50); } });
async function showCard(id) {
  const c = await api("/assets/" + id); const p = c.prediction, ex = p?.explanation || {};
  $("#detail").innerHTML = `<h3>${esc(c.code)} <small class="muted">${esc(c.type)} · ${c.street === "main" ? "رئيسي" : "فرعي"} · ${esc(c.crit)}</small></h3>
    <div class="kv"><span>الخزانة</span><b>${esc(c.cabinet || "—")}</b><span>التركيب</span><b>${esc(c.install || "—")}</b><span>الاحتمال 14 يومًا</span><b style="color:${riskColor(p?.p)}">${pct(p?.p, 1)}</b><span>الخطر (ر.س)</span><b>${fmt(p?.risk_sar)}</b></div>
    ${c.list_item ? `<p class="pill">في قائمة الأسبوع #${c.list_item.rank} · ${esc(c.list_item.action)} · ${esc(c.list_item.status)}</p><p class="reason">${esc(c.list_item.reason)}</p>` : ""}
    ${Object.keys(ex).length ? `<h4>لماذا</h4><ul class="expl">${Object.entries(ex).sort((a, b) => b[1] - a[1]).map(([g, v]) => `<li><span>${esc(GROUP_AR[g] || g)}</span><i style="width:${Math.max(2, Math.abs(v) * 300)}px;background:${v >= 0 ? "#e5484d" : "#2bb673"}"></i>${(v * 100).toFixed(1)} نقطة</li>`).join("")}</ul>` : ""}
    <h4>العلامات المسجّلة</h4>${c.observations.length ? `<ul class="plain">${c.observations.slice(0, 5).map((o) => `<li>${o.at.slice(0, 10)} · ${esc(o.symptom)} · شدة ${o.severity} · ${esc(o.source)}</li>`).join("")}</ul>` : '<p class="muted">لا علامات</p>'}
    <h4>الأعطال السابقة</h4>${c.failures.length ? `<ul class="plain">${c.failures.map((f) => `<li>${f.on} · ${esc(f.mode || "?")} · ${f.lead == null ? "بلا إنذار" : "إنذار قبل " + f.lead + " يومًا"}</li>`).join("")}</ul>` : '<p class="muted">لا أعطال مسجّلة</p>'}
    <p class="muted small">المصدر: ${esc(c.source)} · النموذج ${esc((p?.model_version_id || "").slice(0, 8))}</p>`;
}
const GROUP_AR = { symptoms: "أعراض مرصودة على الأصل", network: "انقطاعات جزئية على نفس الدائرة", weather: "الحرارة والأمطار", history: "سجل الأعطال السابقة", asset: "عمر الأصل ونوعه" };

/* ------------------------------------------------------------------ ledger */
async function loadLedger() {
  const L = await api("/ledger/months"), M = L.months;
  $("#ledgerTable tbody").innerHTML = M.map((m) => `<tr><td>${m.month}</td><td>${m.n_failures}</td><td>${pct(m.pfr["2"])}</td><td>${pct(m.pfr["7"])}</td><td>${pct(m.pfr["14"])}</td><td><b>${pct(m.pfr.own)}</b></td><td>${pct(m.emergency_share)}</td><td>${fmt(m.dark_days)}</td><td>${pct(m.symptom_capture_rate)}</td></tr>`).join("");
  $("#ledgerChart").innerHTML = lineChart(M.map((m) => ({ x: m.month.slice(2), y: m.pfr.own })), "PFR@L الخاصة بكل شهر (قوائم معتمدة فقط)");
  const d = L.drift; $("#drift").innerHTML = d.status === "drift" ? `<b>انجراف:</b> PFR@L انخفض شهرين متتاليين (${d.last_two.map((v) => pct(v)).join("، ")}) عن المتوسط ${pct(d.baseline)} — إعادة التدريب مطلوبة` : d.status === "stable" ? `مستقر: المتوسط ${pct(d.baseline)} · آخر شهرين ${d.last_two.map((v) => pct(v)).join("، ")}` : "تاريخ غير كافٍ لفحص الانجراف (" + d.months + " أشهر)";
  const models = await api("/ledger/models");
  $("#modelsTable tbody").innerHTML = models.map((m) => `<tr><td>${m.name} <small class="muted">${m.model_version_id.slice(0, 8)}</small></td><td>${m.created_at.slice(0, 10)}</td><td>${m.metrics.auc?.toFixed(3)}</td><td>${m.metrics.brier?.toFixed(4)}</td><td>${pct(m.metrics.pfr_at_L_validation)}</td><td>${pct(m.metrics.pfr_age_rule_validation)}</td><td>${Object.entries(m.gates).map(([k, g]) => `<span class="gate ${g.pass ? "ok" : "bad"}">${k}</span>`).join(" ")}</td><td>${m.promoted ? "✓" : ""}</td></tr>`).join("");
}

/* ------------------------------------------------------------------ backtest */
async function loadBacktest() {
  try { BT = await api("/ledger/backtest"); } catch (e) { $("#btKpis").innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  $("#btSource").textContent = BT.source_note === "simulation" ? "بيانات محاكاة" : "بيانات ميدانية";
  const P = BT.pfr_own_L;
  $("#btKpis").innerHTML = kpi("PFR@L — بصيرة", pct(P.baseera)) + kpi("PFR@L — قاعدة العمر", pct(P.age_rule)) + kpi("PFR@L — اليوم", "0%") + kpi("نسبة الطارئ", `${pct(BT.emergency_share.reactive)} ← ${pct(BT.emergency_share.baseera)}`) + kpi("أيام الانطفاء", `${fmt(BT.dark_days.reactive)} ← ${fmt(BT.dark_days.baseera)}`) + kpi("AUC · الدقة@30", `${BT.metrics.auc.toFixed(2)} · ${pct(BT.precision30)}`) + kpi("الأعطال / الأسابيع", `${BT.n_failures} / ${BT.weeks}`);
  $("#btBars").innerHTML = barChart(Object.entries(BT.pfr).map(([L, v]) => ({ label: "L=" + L, a: v.baseera, b: v.age_rule })), "PFR@L بحسب المهلة: بصيرة مقابل قاعدة العمر");
  $("#btSeries").innerHTML = lineChart(BT.series.map((s) => ({ x: s.week.slice(5), y: s.failures ? s.anticipated / s.failures : null })), "نسبة الأعطال المُنذَر بها أسبوعيًا");
  $("#btModes tbody").innerHTML = BT.by_mode.map((m) => `<tr><td>${esc(m.mode_ar)}</td><td>${m.cls}</td><td>${m.n}</td><td>${m.L}</td><td><b>${pct(m.pfr_L)}</b></td><td>${pct(m.pfr7)}</td><td>${m.median_lead ?? "—"}</td></tr>`).join("");
}

/* ------------------------------------------------------------------ tiny SVG charts (no library) */
function lineChart(pts, title) {
  const W = 900, H = 240, p = 36, xs = pts.length; const ys = pts.map((d) => d.y).filter((v) => v != null);
  const path = pts.map((d, i) => d.y == null ? "" : `${i ? "L" : "M"}${p + (i * (W - 2 * p)) / Math.max(1, xs - 1)},${H - p - d.y * (H - 2 * p)}`).join(" ");
  const grid = [0, 0.25, 0.5, 0.75, 1].map((g) => `<line x1="${p}" x2="${W - p}" y1="${H - p - g * (H - 2 * p)}" y2="${H - p - g * (H - 2 * p)}" class="grid"/><text x="${p - 6}" y="${H - p - g * (H - 2 * p) + 4}" class="tick">${g * 100}%</text>`).join("");
  const labels = pts.map((d, i) => i % Math.ceil(xs / 12) ? "" : `<text x="${p + (i * (W - 2 * p)) / Math.max(1, xs - 1)}" y="${H - 8}" class="tick mid">${esc(d.x)}</text>`).join("");
  return `<h4>${esc(title)}</h4><svg viewBox="0 0 ${W} ${H}">${grid}<path d="${path}" class="line"/>${labels}</svg>`;
}
function barChart(rows, title) {
  const W = 900, H = 240, p = 36, bw = (W - 2 * p) / rows.length;
  const bars = rows.map((r, i) => { const x = p + i * bw; return `<rect x="${x + bw * 0.15}" y="${H - p - r.a * (H - 2 * p)}" width="${bw * 0.3}" height="${r.a * (H - 2 * p)}" class="a"/><rect x="${x + bw * 0.5}" y="${H - p - r.b * (H - 2 * p)}" width="${bw * 0.3}" height="${r.b * (H - 2 * p)}" class="b"/><text x="${x + bw / 2}" y="${H - 8}" class="tick mid">${esc(r.label)}</text><text x="${x + bw * 0.3}" y="${H - p - r.a * (H - 2 * p) - 4}" class="tick mid">${pct(r.a)}</text><text x="${x + bw * 0.65}" y="${H - p - r.b * (H - 2 * p) - 4}" class="tick mid">${pct(r.b)}</text>`; }).join("");
  return `<h4>${esc(title)} <small class="muted">■ بصيرة ▫ قاعدة العمر</small></h4><svg viewBox="0 0 ${W} ${H}">${bars}</svg>`;
}

if (TOKEN) boot();
