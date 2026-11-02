# Runbook

## First run
`make install && cp .env.example .env && make demo && make serve` — see README.

## Loading a real export (from the UI)

Login as `admin` → البيانات والمدخلات → pick the source → upload CSV/Excel → read the preview (accepted / quarantined with reasons) → اعتماد الإدخال → التشغيل والمهام → إعادة الحساب الكاملة. Quarantined rows are fixed and retried from the same screen.

## Loading a real export (CLI)
1. Cabinets then assets: `baseera ingest cabinets cabinets.csv` · `baseera ingest assets assets.csv` (columns as in `services/ingest/pipelines/core.py`).
2. Weather: `baseera ingest weather weather.csv` (day, tmax_c, rain_mm, dust).
3. Reports and work orders (daily): `baseera ingest reports reports.csv` · `baseera ingest work_orders wo.csv`.
4. Review quarantine: `GET /api/admin/quarantine` — fix source, re-run (idempotent on external_ref).
5. `baseera build-features --as-of <sunday>` → `baseera train --as-of <sunday>` → `baseera plan` → `baseera ledger`.

## Weekly cycle (worker / CronJob)
Sunday 06:00 `build-features && plan`; daily 02:00 `ledger`; monthly `train` (or when `/api/ledger/months` reports drift).

## Calibration from the field

UI: المعاملات (admin). Values are stored in `sys_setting`, win over `.env`, and are audited. `POST /api/admin/params/reset` returns to the `.env` defaults.

### Legacy (.env only)
Edit `.env` (`BASEERA_CREW_JOBS_PER_WEEK`, `BASEERA_EMERGENCY_MULTIPLIER`, `BASEERA_CONSEQUENCE_SAR_PER_UNIT`,
`BASEERA_LEAD_DEFAULT`, lead_by_mode in config) → restart → `baseera plan` (rule changes apply immediately) → `baseera backtest`
to re-measure.

## Model not promoted
`baseera train` prints the gates. `auc` below 0.80 → check feature rows and label balance; `pfr_gain_over_age` below 0.10 →
symptoms are not being captured (see `symptom_capture_rate` in the ledger); `single_group_share` above 0.90 → suspect leakage
in that feature group. Promote manually only with `--force` and an ADR entry.

## Backups
PostgreSQL: daily `pg_dump` to object storage (35 days). Models: `data/models/*.joblib` are reproducible from the database.

## Health
`GET /api/health` · container HEALTHCHECK · logs are JSON on stdout.
