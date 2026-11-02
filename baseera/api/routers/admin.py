"""Operational endpoints (admin): run ingestion, build features, train, score/plan, ledger, quarantine review."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import get_db
from ...core.models import IngestRun, Quarantine, User
from ...core.security import audit, require
from ...services.features.build import build_features
from ...services.ingest.pipelines.core import PIPELINES
from ...services.ledger.failures import derive_failures
from ...services.ledger.monthly import compute_months
from ...services.model.core import train
from ...services.plan import plan_week

router = APIRouter(prefix="/admin", tags=["admin"])


def last_sunday(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=(d.weekday() + 1) % 7)


@router.post("/ingest/{pipeline}/run")
async def run_ingest(pipeline: str, file: UploadFile, source: str = "municipal", db: Session = Depends(get_db), u: User = Depends(require("admin"))):
    if pipeline not in PIPELINES:
        raise HTTPException(400, f"pipeline must be one of {sorted(PIPELINES)}")
    s = get_settings(); os.makedirs(os.path.join(s.data_dir, "uploads"), exist_ok=True)
    path = os.path.join(s.data_dir, "uploads", f"{pipeline}-{datetime.utcnow():%Y%m%d%H%M%S}.csv")
    with open(path, "wb") as f:
        f.write(await file.read())
    run = PIPELINES[pipeline](db, source=source).run_csv(path)
    audit(db, u.username, "ingest.run", "ingest_run", run.run_id, None, dict(pipeline=pipeline, n_in=run.n_in, n_ok=run.n_ok, n_q=run.n_quarantined))
    db.commit()
    return dict(run_id=run.run_id, pipeline=pipeline, n_in=run.n_in, n_ok=run.n_ok, n_quarantined=run.n_quarantined)


@router.get("/ingest/runs")
def ingest_runs(limit: int = 50, db: Session = Depends(get_db), u: User = Depends(require("admin", "manager"))):
    return [dict(run_id=r.run_id, pipeline=r.pipeline, started=r.started_at.isoformat(), n_in=r.n_in, n_ok=r.n_ok, n_quarantined=r.n_quarantined)
            for r in db.query(IngestRun).order_by(IngestRun.started_at.desc()).limit(limit).all()]


@router.get("/quarantine")
def quarantine(pipeline: str | None = None, unresolved: bool = True, limit: int = 200, db: Session = Depends(get_db), u: User = Depends(require("admin", "manager"))):
    q = db.query(Quarantine)
    if pipeline: q = q.filter_by(pipeline=pipeline)
    if unresolved: q = q.filter(Quarantine.resolved_at.is_(None))
    rows = q.order_by(Quarantine.received_at.desc()).limit(limit).all()
    return dict(n=q.count(), items=[dict(row_id=r.row_id, pipeline=r.pipeline, reason=r.reason, received=r.received_at.isoformat(), payload=r.raw_payload) for r in rows])


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
