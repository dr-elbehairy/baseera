# بصيرة · Baseera — Predictive maintenance for urban assets

**سجل قابلية التنبؤ وقائمة الأسبوع لصيانة الأصول الحضرية** — الهاكاثون الهندسي 2026، المسار الأول / التحدي الأول، فريق T-0848.

Baseera does one thing a municipality cannot do today: it **measures what share of failures could have been anticipated
(PFR@L)** and turns that into a capacity-limited weekly list the supervisor approves and the technician executes from a QR scan.
No sensors in v0.1 — it runs on the data the municipality already has (reports, work orders, asset registry, weather) plus
symptoms the technician records in 20 seconds.

## Five layers, one repository

| layer | what it does | code |
|---|---|---|
| 1 Sources & ingestion | CSV/API exports → validate → match asset (code, then ≤ 25 m) → upsert or **quarantine with a reason** | `baseera/services/ingest/` |
| 2 Data platform | `ops_*` facts, `feat_*` weekly as-of snapshots, `ledger_*` measurements (SQLite locally, PostgreSQL in Docker) | `baseera/core/models.py`, `services/features/` |
| 3 Model & decision | gradient boosting + isotonic calibration, temporal split, **promotion gates**; decision engine with **one declared rule** | `services/model/`, `services/decision/` |
| 4 Applications & API | FastAPI (JWT, RBAC, audit), supervisor web app, technician PWA (QR, offline queue) | `baseera/api/`, `apps/web`, `apps/field` |
| 5 Feedback & measurement | outcomes, observations and failures flow back; monthly ledger (PFR@L, emergency share, dark days); drift → retrain | `services/ledger/`, `services/backtest.py` |

The simulated municipality (`baseera/sim/`) is **just another source**: it writes raw CSVs that go through the same pipelines,
tagged `source='simulated'`. Replace the CSVs with a real export and nothing downstream changes.

## Run it in five commands (new engineer, ~5 minutes)

```bash
python -m venv .venv && source .venv/bin/activate      # Python ≥ 3.11
make install                                           # pip install -r requirements.txt && pip install -e .
cp .env.example .env
make demo                                              # simulate → ingest → features → train (gated) → plan → ledger → backtest
make serve                                             # http://localhost:8000  (supervisor/demo)   http://localhost:8000/field (technician/demo)
```

`make demo` prints each stage with timing; the last line is the backtest headline (PFR@L vs age rule vs today). All numbers in
the web app come from the database or `data/backtest.json`; nothing is typed by hand.

With Docker (PostgreSQL + API + weekly worker): `cp .env.example .env && docker compose up -d --build`, then
`docker compose exec api python -m baseera.cli demo`.

## The weekly cycle

```
Sunday 06:00   build-features → score → plan      (worker / CronJob)        → weekly list "proposed"
Sunday 08:00   supervisor reviews in /             approve · override (reason required) · skip
Sun–Thu        technician in /field                QR scan → symptom (20 s) → outcome; works offline, syncs with client_ref idempotency
continuous     ledger                              failure events → lead days → had_warning_at_L → PFR@L per month → drift → retrain
```

## API (OpenAPI at `/api/docs`)

`POST /api/auth/login` · `GET /api/assets?bbox=` · `GET /api/assets/{id}` · `GET /api/weekly-lists/current` ·
`PATCH /api/weekly-lists/items/{id}` · `POST /api/weekly-lists/{id}/approve` · `GET /api/field/assets/{code}` ·
`POST /api/field/observations` (batch) · `POST /api/field/outcomes` (batch) · `GET /api/field/tasks` ·
`GET /api/ledger/months` · `GET /api/ledger/backtest` · `GET /api/ledger/models` · `POST /api/admin/ingest/{pipeline}/run` ·
`POST /api/admin/features/build` · `POST /api/admin/model/train` · `POST /api/admin/model/score` · `GET /api/admin/quarantine`.

Roles: `supervisor` (approve/override), `technician` (field), `manager` (ledger), `admin` (operations). Demo password `demo`
(disabled when `BASEERA_ENV=production`; use OIDC/SSO).

## The metric, formally

```
lead(failure)     = failed_on − week_start of the earliest list containing the asset (≤ 45 days before the failure); −1 if none
had_warning_at_L  = lead ≥ L(failure mode)          L: lamp 3 · LED driver 7 · cable 7 · solar 7 · cabinet 14 · collision 2
PFR@L(month)      = mean(had_warning_at_L) over confirmed failures of the month
```
One implementation (`services/ledger/pfr.py`) serves the backtest and live operation. Live mode counts only **approved/done**
lists as warnings; a proposed list nobody looked at is not a warning.

## Decision rule (no hidden model)

```
risk_sar  = p_fail × [ planned_cost × (emergency_multiplier − 1) + consequence_units × consequence_sar ]
priority  = risk_sar × intervention_efficacy ÷ planned_cost
list      = p_fail ≥ alert_probability, by priority, until crew capacity; critical assets displace the weakest non-critical item
action    = inspect (< 0.35) · service (0.35–0.70) · replace (≥ 0.70 or beyond design life)
```
Every parameter is in `.env` (`baseera/core/config.py`) to be calibrated from the survey and mentor sessions.

## Admin panel — data in, results out

Everything an operator needs without touching a terminal (role `admin`; `manager` and `supervisor` read-only):

| Screen | What it does |
|---|---|
| **البيانات والمدخلات** | Upload CSV/Excel per source (cabinets → assets → weather → reports → work orders → observations), downloadable template, **dry-run preview** (rows accepted / quarantined with reasons, first 20 rows) before anything is written; single-record form; quarantine review with *fix & retry*; upload history |
| **المعاملات** | Field-calibrated parameters (lead L per failure mode, crew capacity, alert threshold, cost model, promotion gates) stored in `sys_setting`, audited, applied live over the `.env` defaults |
| **التشغيل والمهام** | Background jobs with progress: full recompute (features → train → plan → ledger), each step alone, one-year backtest, tagged simulation seed, purge (typed confirmation) |

Design system: light, Arabic-first, one primary colour (teal) with amber/red reserved for risk — `apps/web/styles.css`, shared by the technician PWA.

## Deploy (public demo)

* **Railway** (recommended): `railway up` from the repo, or connect the GitHub repo in the Railway dashboard. `railway.json` builds the Dockerfile; set `BASEERA_AUTO_DEMO=true`, `BASEERA_ENV=staging`, a new `BASEERA_JWT_SECRET`, and attach a PostgreSQL plugin (`BASEERA_DATABASE_URL=${{Postgres.DATABASE_URL}}` rewritten to `postgresql+psycopg://`). On an empty database the platform seeds the tagged simulation itself at first start (~2–3 min, progress visible under التشغيل والمهام).
* **Render**: `render.yaml` Blueprint (web service + managed PostgreSQL).
* **Vercel** is not suitable for the backend (long-running training, persistent database, scheduled worker); it can only host a static front end pointed at one of the above.
* **Production inside KSA**: `docker compose up --build` on a VM; see `docs/security.md`.

## Tests

`make test` — ingestion (validation, spatial matching, quarantine, idempotency, PDPL hashing), no-leakage checks on features,
model gates, decision rule arithmetic, PFR lead logic, ledger consistency, the **backtest as regression test** (Baseera must beat
the age rule with the same crew), and the full API cycle including an offline batch replay.

## Repository map

```
baseera/core        config · db · models · security · geo
baseera/services    ingest/ (base, match, pipelines, simulated) · features/ (build, catalog.md) · model/ · decision/ · ledger/ · plan.py · backtest.py
baseera/api         app.py · routers/{auth,assets,lists,field,ledger,admin}.py
baseera/sim         generate.py (simulated municipality — raw tables)
baseera/cli.py      migrate · seed-sim · ingest · build-features · train · plan · ledger · backtest · demo · serve
apps/web            supervisor app (map · weekly list · ledger · backtest · method)
apps/field          technician PWA (QR · symptoms · outcomes · offline queue · service worker)
tests/              conftest (small simulation) · test_ingest · test_pipeline · test_api
docs/               adr/ · security.md · runbook.md
```

## Status (v0.2.0, 2 Nov 2026)

* v0.2.0 — admin data panel (upload + preview + quarantine + manual records), runtime parameters, background jobs, new design system, Railway/Render deployment files; 25 tests.
* v0.1.0 — five-layer prototype.

Built and tested on simulated data. Field calibration (L, crew capacity, emergency multiplier, consequence cost) and the first
real export are the next inputs; see `docs/runbook.md` for how to load them without touching code.
