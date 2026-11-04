"""Technician endpoints (PWA). Observations and outcomes accept batches with client_ref for offline-sync idempotency."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.models import Asset, ListItem, Observation, Outcome, Prediction, User, WeeklyList, WorkOrder
from ...core.security import audit, require
from ...services.ingest.base import normalise_code
from ...core.catalog import CATEGORIES, SYMPTOM_AR, SYMPTOM_CODES as SYMPTOMS, TYPES, symptoms_for
from ...services.decision.rank import ACTION_AR
from sqlalchemy import func

router = APIRouter(prefix="/field", tags=["field"])

FINDINGS = {"confirmed_degradation", "no_issue", "already_failed", "inaccessible"}


@router.get("/symptoms")
def symptoms(category: str | None = None):
    """Symptom vocabulary; with ?category= only that category's symptoms plus the generic ones."""
    return symptoms_for(category)


@router.get("/assets/{code}")
def by_code(code: str, db: Session = Depends(get_db), u: User = Depends(require("technician", "supervisor"))):
    a = db.query(Asset).filter_by(asset_code=normalise_code(code)).first()
    if not a:
        raise HTTPException(404, f"asset {normalise_code(code)} not found")
    wk = db.query(func.max(WeeklyList.week_start)).filter(WeeklyList.run_tag == "live").scalar()
    item = None
    if wk:
        wl = db.query(WeeklyList).filter_by(week_start=wk, run_tag="live").first()
        if wl:
            item = next((i for i in wl.items if i.asset_id == a.asset_id), None)
    p = db.query(Prediction).filter_by(asset_id=a.asset_id, week_start=wk, run_tag="live").first() if wk else None
    last = db.query(Observation).filter_by(asset_id=a.asset_id).order_by(Observation.observed_at.desc()).first()
    return dict(asset_id=a.asset_id, code=a.asset_code, type=a.asset_type, category=a.category, category_ar=CATEGORIES.get(a.category, {}).get("ar"),
                type_ar=TYPES[a.asset_type][1], kind=a.kind, street=a.street_class, crit=a.criticality, symptoms=symptoms_for(a.category),
                cabinet=a.cabinet.cabinet_code if a.cabinet else None, p=(round(p.p_fail, 3) if p else None),
                task=(dict(item_id=item.item_id, action=item.action, action_ar=ACTION_AR.get(item.action), status=item.status, reason=item.reason, tier=item.tier, safe_window=item.safe_window,
                           work_order=(db.query(WorkOrder).filter_by(item_id=item.item_id).first().details if db.query(WorkOrder).filter_by(item_id=item.item_id).first() else None)) if item else None),
                last_symptom=(dict(code=last.symptom_code, ar=SYMPTOM_AR.get(last.symptom_code, last.symptom_code), at=last.observed_at.isoformat()) if last else None))


class ObservationIn(BaseModel):
    asset_code: str
    symptom_code: str
    severity: int = Field(1, ge=1, le=3)
    observed_at: datetime | None = None
    note: str | None = None
    client_ref: str | None = None


@router.post("/observations", status_code=201)
def post_observations(items: list[ObservationIn], db: Session = Depends(get_db), u: User = Depends(require("technician", "supervisor"))):
    out = []
    for it in items:
        if it.symptom_code not in SYMPTOMS:
            out.append(dict(client_ref=it.client_ref, status="rejected", reason=f"unknown symptom {it.symptom_code}")); continue
        a = db.query(Asset).filter_by(asset_code=normalise_code(it.asset_code)).first()
        if not a:
            out.append(dict(client_ref=it.client_ref, status="rejected", reason="unknown asset")); continue
        if it.client_ref and db.query(Observation).filter_by(client_ref=it.client_ref).first():
            out.append(dict(client_ref=it.client_ref, status="duplicate")); continue
        o = Observation(asset_id=a.asset_id, observed_at=it.observed_at or datetime.utcnow(), symptom_code=it.symptom_code, severity=it.severity,
                        source="technician_qr", observer_id=u.username, note=it.note, client_ref=it.client_ref)
        db.add(o); db.flush()
        out.append(dict(client_ref=it.client_ref, status="created", obs_id=o.obs_id))
    db.commit()
    return out


class OutcomeIn(BaseModel):
    item_id: str
    finding: str
    action_taken: str
    cost_sar: float | None = None
    visited_at: datetime | None = None
    client_ref: str | None = None


@router.post("/outcomes", status_code=201)
def post_outcomes(items: list[OutcomeIn], db: Session = Depends(get_db), u: User = Depends(require("technician", "supervisor"))):
    out = []
    for it in items:
        if it.finding not in FINDINGS:
            out.append(dict(client_ref=it.client_ref, status="rejected", reason=f"finding must be one of {sorted(FINDINGS)}")); continue
        li = db.get(ListItem, it.item_id)
        if not li:
            out.append(dict(client_ref=it.client_ref, status="rejected", reason="unknown item")); continue
        if (it.client_ref and db.query(Outcome).filter_by(client_ref=it.client_ref).first()) or db.query(Outcome).filter_by(item_id=li.item_id).first():
            out.append(dict(client_ref=it.client_ref, status="duplicate")); continue
        o = Outcome(item_id=li.item_id, visited_at=it.visited_at or datetime.utcnow(), finding=it.finding, action_taken=it.action_taken,
                    cost_sar=it.cost_sar, technician_id=u.username, client_ref=it.client_ref)
        before = li.status; li.status = "done"
        db.add(o); audit(db, u.username, "outcome.create", "list_item", li.item_id, dict(status=before), dict(status="done", finding=it.finding))
        db.flush(); out.append(dict(client_ref=it.client_ref, status="created", outcome_id=o.outcome_id))
    db.commit()
    return out


@router.get("/tasks")
def my_tasks(db: Session = Depends(get_db), u: User = Depends(require("technician", "supervisor"))):
    wk = db.query(func.max(WeeklyList.week_start)).filter(WeeklyList.run_tag == "live").scalar()
    if not wk:
        return []
    wl = db.query(WeeklyList).filter_by(week_start=wk, run_tag="live").first()
    A = {a.asset_id: a for a in db.query(Asset).filter(Asset.asset_id.in_([i.asset_id for i in wl.items])).all()} if wl.items else {}
    wos = {w.item_id: w.details for w in db.query(WorkOrder).filter(WorkOrder.item_id.isnot(None)).all()}
    return [dict(item_id=i.item_id, rank=i.rank, code=A[i.asset_id].asset_code, type=A[i.asset_id].asset_type, category=A[i.asset_id].category, lon=A[i.asset_id].lon, lat=A[i.asset_id].lat,
                 action=i.action, action_ar=ACTION_AR.get(i.action), status=i.status, reason=i.reason, tier=i.tier, route=i.route, seq=i.seq, safe_window=i.safe_window,
                 work_order=wos.get(i.item_id))
            for i in sorted(wl.items, key=lambda x: (x.route or 99, x.seq or 99, x.rank)) if i.status in ("approved", "proposed")]
