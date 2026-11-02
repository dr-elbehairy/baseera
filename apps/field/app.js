/* Baseera technician PWA — QR scan (BarcodeDetector with manual fallback), 20-second symptom form, offline queue + sync. */
const $ = (s) => document.querySelector(s);
const API = "/api";
let TOKEN = localStorage.getItem("baseera.ftoken"), ASSET = null, SYM = null, SEV = 1;
const QKEY = "baseera.queue";
const queue = () => JSON.parse(localStorage.getItem(QKEY) || "[]");
const saveQueue = (q) => { localStorage.setItem(QKEY, JSON.stringify(q)); $("#queueInfo").textContent = q.length ? `${q.length} سجلات بانتظار الاتصال` : ""; };
const toast = (m, bad) => { const t = $("#toast"); t.textContent = m; t.style.background = bad ? "#e5484d" : "#2bb673"; t.style.display = "block"; setTimeout(() => (t.style.display = "none"), 2200); };
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(16).slice(2));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/field/sw.js");
const setNet = () => { const on = navigator.onLine; $("#net").textContent = on ? "متصل" : "دون اتصال"; $("#net").className = on ? "" : "off"; if (on) sync(); };
window.addEventListener("online", setNet); window.addEventListener("offline", setNet);

async function api(path, opt = {}) {
  const r = await fetch(API + path, { ...opt, headers: { "Content-Type": "application/json", Authorization: "Bearer " + TOKEN } });
  if (r.status === 401) { localStorage.removeItem("baseera.ftoken"); TOKEN = null; $("#app").hidden = true; $("#login").hidden = false; throw new Error("unauthorised"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await fetch(API + "/auth/login", { method: "POST", body: new URLSearchParams(new FormData(e.target)) });
  if (!r.ok) return toast("بيانات الدخول غير صحيحة", true);
  TOKEN = (await r.json()).access_token; localStorage.setItem("baseera.ftoken", TOKEN); boot();
});

async function boot() {
  $("#login").hidden = true; $("#app").hidden = false; setNet();
  const syms = await api("/field/symptoms").catch(() => JSON.parse(localStorage.getItem("baseera.syms") || "[]"));
  localStorage.setItem("baseera.syms", JSON.stringify(syms));
  $("#symptoms").innerHTML = syms.map((s) => `<button data-c="${s.code}">${s.ar}</button>`).join("");
  saveQueue(queue()); loadTasks();
}
$("#symptoms").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; SYM = b.dataset.c; document.querySelectorAll("#symptoms button").forEach((x) => x.classList.toggle("on", x === b)); });
document.querySelector(".sev").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; SEV = +b.dataset.s; document.querySelectorAll(".sev button").forEach((x) => x.classList.toggle("on", x === b)); });

/* ------------------------------------------------------------------ scanning */
$("#startScan").onclick = async () => {
  if (!("BarcodeDetector" in window)) return toast("المتصفح لا يدعم مسح الرمز؛ اكتب الرمز يدويًا", true);
  const v = $("#video"); v.hidden = false;
  const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }); v.srcObject = stream; await v.play();
  const det = new BarcodeDetector({ formats: ["qr_code"] });
  const tick = async () => { if (v.hidden) return; try { const codes = await det.detect(v); if (codes.length) { stream.getTracks().forEach((t) => t.stop()); v.hidden = true; lookup(codes[0].rawValue.split("/").pop()); return; } } catch {} requestAnimationFrame(tick); };
  tick();
};
$("#lookup").onclick = () => lookup($("#codeInput").value);
async function lookup(code) {
  if (!code) return;
  try { ASSET = await api("/field/assets/" + encodeURIComponent(code.trim())); } catch (e) { return toast(e.message, true); }
  $("#asset").hidden = false; $("#aCode").textContent = ASSET.code;
  $("#aMeta").textContent = `${ASSET.type} · ${ASSET.street === "main" ? "شارع رئيسي" : "شارع فرعي"} · خزانة ${ASSET.cabinet || "—"} · احتمال العطل ${ASSET.p == null ? "—" : Math.round(ASSET.p * 100) + "%"}`;
  $("#aTask").innerHTML = ASSET.task ? `<p><span class="pill">مهمة الأسبوع: ${ASSET.task.action_ar}</span> <span class="pill">${ASSET.task.status}</span></p><p class="muted">${ASSET.task.reason || ""}</p>` : `<p class="muted">ليس في قائمة الأسبوع · ${ASSET.last_symptom ? "آخر علامة: " + ASSET.last_symptom.ar + " (" + ASSET.last_symptom.at.slice(0, 10) + ")" : "لا علامات سابقة"}</p>`;
  $("#outcomeBox").hidden = !(ASSET.task && ASSET.task.status !== "done");
  window.scrollTo({ top: $("#asset").offsetTop - 60, behavior: "smooth" });
}

/* ------------------------------------------------------------------ submit (online or queued) */
$("#sendObs").onclick = () => {
  if (!ASSET || !SYM) return toast("اختر العلامة أولًا", true);
  enqueue({ kind: "observation", body: { asset_code: ASSET.code, symptom_code: SYM, severity: SEV, note: $("#note").value || null, observed_at: new Date().toISOString(), client_ref: uid() } });
  SYM = null; document.querySelectorAll("#symptoms button").forEach((x) => x.classList.remove("on")); $("#note").value = "";
};
$("#sendOutcome").onclick = () => {
  if (!ASSET?.task) return;
  enqueue({ kind: "outcome", body: { item_id: ASSET.task.item_id, finding: $("#finding").value, action_taken: $("#actionTaken").value || $("#finding").value, cost_sar: $("#cost").value ? +$("#cost").value : null, visited_at: new Date().toISOString(), client_ref: uid() } });
  $("#outcomeBox").hidden = true;
};
function enqueue(rec) { const q = queue(); q.push(rec); saveQueue(q); toast(navigator.onLine ? "جارٍ الإرسال…" : "حُفظ محليًا وسيُرسل عند الاتصال"); sync(); }
let syncing = false;
async function sync() {
  if (syncing || !navigator.onLine || !TOKEN) return; const q = queue(); if (!q.length) return; syncing = true;
  try {
    const obs = q.filter((r) => r.kind === "observation").map((r) => r.body), out = q.filter((r) => r.kind === "outcome").map((r) => r.body);
    if (obs.length) await api("/field/observations", { method: "POST", body: JSON.stringify(obs) });
    if (out.length) await api("/field/outcomes", { method: "POST", body: JSON.stringify(out) });
    saveQueue([]); toast(`تمت مزامنة ${q.length} سجل`); loadTasks();
  } catch (e) { toast("تعذّرت المزامنة: " + e.message, true); } finally { syncing = false; }
}
async function loadTasks() {
  try { const t = await api("/field/tasks"); localStorage.setItem("baseera.tasks", JSON.stringify(t)); render(t); } catch { render(JSON.parse(localStorage.getItem("baseera.tasks") || "[]")); }
  function render(t) { $("#tasks").innerHTML = t.length ? t.map((x) => `<div class="task"><span>#${x.rank} <b>${x.code}</b> · ${x.action_ar}</span><button class="sm" onclick="lookup('${x.code}')">فتح</button></div>`).join("") : "لا مهام معتمدة بعد"; }
}
if (TOKEN) boot();
