"""Operational endpoints (admin panel): data overview, uploads with preview, templates, manual records, quarantine review,
runtime parameters, background jobs (recompute / train / plan / ledger / backtest / simulation seed / purge)."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core import catalog as CAT
from ...core import params as P
from ...core.config import get_settings
from ...core.db import get_db
from ...core.models import (Asset, AuditLog, Cabinet, Dependency, FailureEvent, IngestRun, Job, ModelVersion, Observation, Quarantine, Report, TelemetryDay, User,
                            WeatherDay, WeeklyList, WorkOrder)
from ...core.security import audit, require
from ...services import jobs as J
from ...services.features.build import build_features
from ...services.ingest.pipelines.core import ORDER, PIPELINES
from ...services.ingest.schema import describe, preview, read_table, template_csv
from ...services.ledger.failures import derive_failures
from ...services.ledger.monthly import compute_months
from ...services.model.core import train
from ...services.plan import plan_week

router = APIRouter(prefix="/admin", tags=["admin"])


def last_sunday(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=(d.weekday() + 1) % 7)


# ----------------------------------------------------------------------------- overview
@router.get("/overview")
def overview(db: Session = Depends(get_db), u: User = Depends(require("admin", "manager"))):
    def by_source(model):
        return {k: v for k, v in db.query(model.source, func.count()).group_by(model.source).all()}
    def span(model, col):
        lo, hi = db.query(func.min(col), func.max(col)).first()
        return dict(n=db.query(func.count()).select_from(model).scalar(), by_source=by_source(model), **{"from": str(lo) if lo else None, "to": str(hi) if hi else None})
    mv = db.query(ModelVersion).filter(ModelVersion.promoted.is_(True)).order_by(ModelVersion.created_at.desc()).first()
    wl = db.query(WeeklyList).filter_by(run_tag="live").order_by(WeeklyList.week_start.desc()).first()
    job = J.running(db) or db.query(Job).order_by(Job.created_at.desc()).first()
    return dict(
        tables=dict(cabinets=span(Cabinet, Cabinet.install_date), assets=span(Asset, Asset.install_date), weather=span(WeatherDay, WeatherDay.day),
                    reports=span(Report, Report.reported_at), work_orders=span(WorkOrder, WorkOrder.opened_at), observations=span(Observation, Observation.observed_at),
                    telemetry=span(TelemetryDay, TelemetryDay.day), dependencies=span(Dependency, Dependency.dep_id)),
        failures=db.query(func.count()).select_from(FailureEvent).filter_by(run_tag="live").scalar(),
        quarantine_open=db.query(func.count()).select_from(Quarantine).filter(Quarantine.resolved_at.is_(None)).scalar(),
        model=(dict(model_version_id=mv.model_version_id, name=mv.name, created_at=mv.created_at.isoformat(), auc=mv.metrics.get("auc"),
                    gates={k: v["pass"] for k, v in mv.gates.items()}) if mv else None),
        weekly_list=(dict(week_start=str(wl.week_start), status=wl.status, items=len(wl.items)) if wl else None),
        last_job=(J.to_dict(job) if job else None),
        categories=[dict(key=c, ar=v["ar"], status=v["status"], status_ar=v["status_ar"],
                         n_assets=db.query(func.count()).select_from(Asset).filter_by(category=c).scalar(),
                         n_failures=db.query(func.count()).select_from(FailureEvent).join(Asset, Asset.asset_id == FailureEvent.asset_id)
                                      .filter(FailureEvent.run_tag == "live", Asset.category == c).scalar()) for c, v in CAT.CATEGORIES.items()],
        backtest_available=os.path.exists(os.path.join(get_settings().data_dir, "backtest.json")),
        env=get_settings().env)


@router.get("/catalog")
def catalog(u: User = Depends(require())):
    """Asset categories, types, symptoms, failure modes and telemetry channels the platform understands."""
    return CAT.describe()


@router.get("/glossary")
def glossary(u: User = Depends(require())):
    """Arabic definitions of every code the platform shows: prefixes, kinds, classes A/B/C, tiers, actions, statuses, sources, metrics, channels, parts."""
    return CAT.glossary()


# ----------------------------------------------------------------------------- ingestion
@router.get("/ingest/schema")
def ingest_schema(u: User = Depends(require("admin", "manager", "supervisor"))):
    return describe()


@router.get("/ingest/{pipeline}/template.csv", response_class=PlainTextResponse)
def ingest_template(pipeline: str, u: User = Depends(require("admin", "manager", "supervisor"))):
    if pipeline not in PIPELINES:
        raise HTTPException(404, "unknown pipeline")
    return PlainTextResponse(template_csv(pipeline), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{pipeline}_template.csv"'})


@router.post("/ingest/{pipeline}/preview")
async def ingest_preview(pipeline: str, file: UploadFile, db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    if pipeline not in PIPELINES:
        raise HTTPException(400, f"pipeline must be one of {ORDER}")
    try:
        df = read_table(file.filename or "upload.csv", await file.read())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"could not read file: {e}")
    if len(df) > 200_000:
        raise HTTPException(413, "file too large for preview (max 200k rows); split it")
    return preview(db, pipeline, df)


@router.post("/ingest/{pipeline}/run")
async def run_ingest(pipeline: str, file: UploadFile, source: str = "municipal", db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    if pipeline not in PIPELINES:
        raise HTTPException(400, f"pipeline must be one of {ORDER}")
    s = get_settings(); os.makedirs(os.path.join(s.data_dir, "uploads"), exist_ok=True)
    content = await file.read()
    try:
        df = read_table(file.filename or "upload.csv", content)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"could not read file: {e}")
    path = os.path.join(s.data_dir, "uploads", f"{pipeline}-{datetime.utcnow():%Y%m%d%H%M%S}.csv")
    df.to_csv(path, index=False)
    run = PIPELINES[pipeline](db, source=source).run(df.to_dict("records"))
    audit(db, u.username, "ingest.run", "ingest_run", run.run_id, None, dict(pipeline=pipeline, file=file.filename, n_in=run.n_in, n_ok=run.n_ok, n_q=run.n_quarantined))
    db.commit()
    return dict(run_id=run.run_id, pipeline=pipeline, n_in=run.n_in, n_ok=run.n_ok, n_quarantined=run.n_quarantined)


@router.get("/ingest/runs")
def ingest_runs(limit: int = 50, db: Session = Depends(get_db), u: User = Depends(require("admin", "manager"))):
    return [dict(run_id=r.run_id, pipeline=r.pipeline, started=r.started_at.isoformat(), n_in=r.n_in, n_ok=r.n_ok, n_quarantined=r.n_quarantined)
            for r in db.query(IngestRun).order_by(IngestRun.started_at.desc()).limit(limit).all()]


class Record(BaseModel):
    source: str = "municipal"
    row: dict


@router.post("/records/{pipeline}")
def add_record(pipeline: str, body: Record, db: Session = Depends(get_db), u: User = Depends(require("admin", "supervisor"))):
    """One record typed in a form. Rejected rows land in quarantine with the reason, like any upload."""
    if pipeline not in PIPELINES:
        raise HTTPException(400, f"pipeline must be one of {ORDER}")
    ok, reason = PIPELINES[pipeline](db, source=body.source).run_one({k: ("" if v is None else v) for k, v in body.row.items()})
    audit(db, u.username, "record.add", pipeline, None, None, dict(ok=ok, reason=reason, row=body.row))
    db.commit()
    if not ok:
        raise HTTPException(422, reason or "rejected")
    return dict(ok=True)


# ----------------------------------------------------------------------------- quarantine
@router.get("/quarantine")
def quarantine(pipeline: str | None = None, unresolved: bool = True, limit: int = 200, db: Session = Depends(get_db), u: User = Depends(require("admin", "manager"))):
    q = db.query(Quarantine)
    if pipeline: q = q.filter_by(pipeline=pipeline)
    if unresolved: q = q.filter(Quarantine.resolved_at.is_(None))
    rows = q.order_by(Quarantine.received_at.desc()).limit(limit).all()
    summary = [dict(pipeline=p, n=n) for p, n in db.query(Quarantine.pipeline, func.count()).filter(Quarantine.resolved_at.is_(None)).group_by(Quarantine.pipeline).all()]
    return dict(n=q.count(), summary=summary, items=[dict(row_id=r.row_id, pipeline=r.pipeline, reason=r.reason, received=r.received_at.isoformat(), payload=r.raw_payload) for r in rows])


class Resolve(BaseModel):
    note: str | None = None


@router.post("/quarantine/{row_id}/resolve")
def resolve(row_id: int, body: Resolve, db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    r = db.get(Quarantine, row_id)
    if not r:
        raise HTTPException(404, "row not found")
    r.resolved_at, r.resolved_by = datetime.utcnow(), u.username
    audit(db, u.username, "quarantine.resolve", "quarantine", str(row_id), None, dict(note=body.note))
    db.commit()
    return dict(row_id=row_id, resolved=True)


class Retry(BaseModel):
    payload: dict
    source: str = "municipal"


@router.post("/quarantine/{row_id}/retry")
def retry(row_id: int, body: Retry, db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    """Corrected payload re-enters the same pipeline; on success the original row is resolved."""
    r = db.get(Quarantine, row_id)
    if not r:
        raise HTTPException(404, "row not found")
    ok, reason = PIPELINES[r.pipeline](db, source=body.source).run_one(body.payload)
    if ok:
        r.resolved_at, r.resolved_by = datetime.utcnow(), u.username
    audit(db, u.username, "quarantine.retry", "quarantine", str(row_id), r.raw_payload, dict(ok=ok, reason=reason, payload=body.payload))
    db.commit()
    if not ok:
        raise HTTPException(422, reason or "rejected again")
    return dict(row_id=row_id, resolved=True)


# ----------------------------------------------------------------------------- parameters
@router.get("/params")
def get_params(db: Session = Depends(get_db), u: User = Depends(require("admin", "manager", "supervisor"))):
    return P.current(db)


class ParamsBody(BaseModel):
    values: dict


@router.patch("/params")
def patch_params(body: ParamsBody, db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    try:
        changed = P.set_many(db, body.values, by=u.username)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    audit(db, u.username, "params.set", "sys_setting", None, {k: v["before"] for k, v in changed.items()}, {k: v["after"] for k, v in changed.items()})
    db.commit()
    return dict(changed=changed, params=P.current(db))


class ResetBody(BaseModel):
    keys: list[str] | None = None


@router.post("/params/reset")
def reset_params(body: ResetBody, db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    P.reset(db, body.keys)
    audit(db, u.username, "params.reset", "sys_setting", None, None, dict(keys=body.keys))
    db.commit()
    return P.current(db)


# ----------------------------------------------------------------------------- jobs
class JobBody(BaseModel):
    params: dict = {}


@router.post("/jobs/{kind}")
def submit_job(kind: str, body: JobBody, db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    if kind not in J.KINDS:
        raise HTTPException(400, f"kind must be one of {J.KINDS}")
    if kind == "purge" and body.params.get("confirm") != "PURGE":
        raise HTTPException(400, "purge requires params.confirm == 'PURGE'")
    try:
        j = J.submit(db, kind, {**body.params, "by": u.username}, by=u.username)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    audit(db, u.username, "job.submit", "sys_job", j.job_id, None, dict(kind=kind, params=body.params))
    db.commit()
    return J.to_dict(j)


@router.get("/jobs")
def list_jobs(limit: int = 20, db: Session = Depends(get_db), u: User = Depends(require("admin", "manager"))):
    return [J.to_dict(j) for j in db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), u: User = Depends(require("admin", "manager"))):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return J.to_dict(j)


@router.get("/audit")
def audit_log(limit: int = 100, db: Session = Depends(get_db), u: User = Depends(require("admin", "manager"))):
    return [dict(at=a.at.isoformat(), actor=a.actor, action=a.action, entity=a.entity, entity_id=a.entity_id, after=a.after)
            for a in db.query(AuditLog).order_by(AuditLog.at.desc()).limit(limit).all()]


# ----------------------------------------------------------------------------- synchronous operations (scripts/CI; the UI uses jobs)
class WeekBody(BaseModel):
    as_of: date | None = None
    week_start: date | None = None


@router.post("/features/build")
def features(body: WeekBody, db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    as_of = body.as_of or date.today()
    derive_failures(db)
    n = build_features(db, as_of=as_of)
    return dict(as_of=str(as_of), rows=n)


@router.post("/model/train")
def model_train(body: WeekBody, db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    mv = train(db, as_of=body.as_of or date.today(), approved_by=u.username)
    audit(db, u.username, "model.train", "model_version", mv.model_version_id, None, dict(promoted=mv.promoted, gates={k: v["pass"] for k, v in mv.gates.items()}))
    db.commit()
    return dict(model_version_id=mv.model_version_id, promoted=mv.promoted, metrics={k: v for k, v in mv.metrics.items() if k != "importance"}, gates=mv.gates)


@router.post("/model/score")
def model_score(body: WeekBody, db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    wk = body.week_start or last_sunday(body.as_of)
    wl = plan_week(db, wk)
    audit(db, u.username, "plan.week", "weekly_list", wl.list_id, None, dict(week_start=str(wk), items=len(wl.items)))
    db.commit()
    return dict(list_id=wl.list_id, week_start=str(wk), items=len(wl.items), status=wl.status)


@router.post("/ledger/compute")
def ledger_compute(db: Session = Depends(get_db), u: User = Depends(require("admin", "manager"))):
    derive_failures(db)
    rows = compute_months(db)
    return dict(months=len(rows))
