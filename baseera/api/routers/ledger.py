from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import get_db
from ...core.models import LedgerMonth, ModelVersion, User
from ...core.security import require
from ...services.ledger.monthly import drift

router = APIRouter(prefix="/ledger", tags=["ledger"])


@router.get("/months")
def months(run_tag: str = "live", db: Session = Depends(get_db), u: User = Depends(require("manager", "supervisor"))):
    rows = db.query(LedgerMonth).filter_by(run_tag=run_tag).order_by(LedgerMonth.month).all()
    return dict(run_tag=run_tag, lead_days=get_settings().lead_days, months=[
        dict(month=r.month, zone=r.zone, n_failures=r.n_failures, pfr=r.pfr, emergency_share=r.emergency_share, dark_days=r.dark_days,
             symptom_capture_rate=r.symptom_capture_rate) for r in rows], drift=drift(db, run_tag))


@router.get("/backtest")
def backtest(db: Session = Depends(get_db), u: User = Depends(require("manager", "supervisor", "technician"))):
    p = os.path.join(get_settings().data_dir, "backtest.json")
    if not os.path.exists(p):
        raise HTTPException(404, "no backtest yet; run `baseera backtest`")
    return json.load(open(p))


@router.get("/models")
def models(db: Session = Depends(get_db), u: User = Depends(require("manager", "supervisor"))):
    return [dict(model_version_id=m.model_version_id, name=m.name, created_at=m.created_at.isoformat(), trained_from=str(m.trained_from),
                 trained_to=str(m.trained_to), metrics={k: v for k, v in m.metrics.items() if k != "importance"}, gates=m.gates, promoted=m.promoted,
                 approved_by=m.approved_by) for m in db.query(ModelVersion).order_by(ModelVersion.created_at.desc()).all()]
