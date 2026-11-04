from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.catalog import MODES, SOURCE_AR, SYMPTOM_AR, TYPES
from ...core.db import get_db
from ...core.models import Asset, FailureEvent, ListItem, Observation, Prediction, User, WeeklyList, WorkOrder
from ...core.security import require

router = APIRouter(prefix="/assets", tags=["assets"])


def _latest_week(db: Session, run_tag: str = "live") -> date | None:
    return db.query(func.max(Prediction.week_start)).filter(Prediction.run_tag == run_tag).scalar()


@router.get("")
def list_assets(bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"), asset_type: str | None = None, category: str | None = None,
                limit: int = Query(5000, le=20000), db: Session = Depends(get_db), u: User = Depends(require("supervisor", "manager", "technician"))):
    q = db.query(Asset).filter(Asset.active.is_(True))
    if bbox:
        try:
            x0, y0, x1, y1 = [float(v) for v in bbox.split(",")]
        except ValueError:
            raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")
        q = q.filter(Asset.lon.between(x0, x1), Asset.lat.between(y0, y1))
    if asset_type:
        q = q.filter(Asset.asset_type == asset_type.upper())
    if category:
        q = q.filter(Asset.category == category)
    assets = q.limit(limit).all()
    wk = _latest_week(db)
    preds = {}
    if wk:
        preds = {p.asset_id: p for p in db.query(Prediction).filter(Prediction.week_start == wk, Prediction.run_tag == "live").all()}
    listed = set()
    if wk:
        wl = db.query(WeeklyList).filter_by(week_start=wk, run_tag="live").first()
        if wl:
            listed = {i.asset_id for i in wl.items}
    return {"week_start": str(wk) if wk else None, "n": len(assets), "items": [
        dict(asset_id=a.asset_id, code=a.asset_code, type=a.asset_type, category=a.category, kind=a.kind, street=a.street_class, crit=a.criticality, lon=a.lon, lat=a.lat,
             install=str(a.install_date) if a.install_date else None, cabinet=a.cabinet.cabinet_code if a.cabinet else None,
             p=(round(preds[a.asset_id].p_fail, 4) if a.asset_id in preds else None),
             risk=(round(preds[a.asset_id].risk_sar, 1) if a.asset_id in preds else None), listed=a.asset_id in listed) for a in assets]}


@router.get("/{asset_id}")
def asset_card(asset_id: str, db: Session = Depends(get_db), u: User = Depends(require())):
    a = db.get(Asset, asset_id) or db.query(Asset).filter_by(asset_code=asset_id).first()
    if not a:
        raise HTTPException(404, "asset not found")
    wk = _latest_week(db)
    p = db.query(Prediction).filter_by(asset_id=a.asset_id, week_start=wk, run_tag="live").first() if wk else None
    obs = db.query(Observation).filter_by(asset_id=a.asset_id).order_by(Observation.observed_at.desc()).limit(10).all()
    fails = db.query(FailureEvent).filter_by(asset_id=a.asset_id, run_tag="live").order_by(FailureEvent.failed_on.desc()).limit(6).all()
    wos = db.query(WorkOrder).filter_by(asset_id=a.asset_id).order_by(WorkOrder.opened_at.desc()).limit(6).all()
    item = None
    if wk:
        wl = db.query(WeeklyList).filter_by(week_start=wk, run_tag="live").first()
        if wl:
            item = next((i for i in wl.items if i.asset_id == a.asset_id), None)
    return dict(asset_id=a.asset_id, code=a.asset_code, type=a.asset_type, type_ar=TYPES[a.asset_type][1], category=a.category, kind=a.kind, street=a.street_class, crit=a.criticality, lon=a.lon, lat=a.lat,
                install=str(a.install_date) if a.install_date else None, cabinet=a.cabinet.cabinet_code if a.cabinet else None, owner=a.owner_entity,
                source=a.source, week_start=str(wk) if wk else None,
                prediction=(dict(p=round(p.p_fail, 4), risk_sar=round(p.risk_sar, 1), priority=round(p.priority, 4), explanation=p.explanation,
                                 model_version_id=p.model_version_id, tier=p.tier, mode=p.mode_pred, window=([p.window_lo, p.window_hi] if p.window_lo is not None else None), cof=p.cof) if p else None),
                list_item=(dict(item_id=item.item_id, rank=item.rank, action=item.action, status=item.status, reason=item.reason) if item else None),
                observations=[dict(at=o.observed_at.isoformat(), symptom=o.symptom_code, symptom_ar=SYMPTOM_AR.get(o.symptom_code, o.symptom_code), severity=o.severity, source=o.source, source_ar=SOURCE_AR.get(o.source, o.source)) for o in obs],
                failures=[dict(on=str(f.failed_on), mode=f.failure_mode, mode_ar=(MODES[f.failure_mode][1] if f.failure_mode in MODES else None), lead=f.lead_days, warned=f.had_warning_at_L, dark=f.days_dark) for f in fails],
                work_orders=[dict(opened=w.opened_at.isoformat(), kind=w.kind, fault=w.fault_code, cost=w.cost_sar) for w in wos])
