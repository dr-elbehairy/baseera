from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import get_db
from ...core.models import Asset, ListItem, Outcome, User, WeeklyList
from ...core.security import audit, require
from ...services.decision.rank import ACTION_AR

router = APIRouter(prefix="/weekly-lists", tags=["weekly list"])


def _serialise(db: Session, wl: WeeklyList) -> dict:
    A = {a.asset_id: a for a in db.query(Asset).filter(Asset.asset_id.in_([i.asset_id for i in wl.items])).all()} if wl.items else {}
    outcomes = {o.item_id: o for o in db.query(Outcome).filter(Outcome.item_id.in_([i.item_id for i in wl.items])).all()} if wl.items else {}
    used = sum(1 for i in wl.items if i.status in ("proposed", "approved", "done"))
    return dict(list_id=wl.list_id, week_start=str(wl.week_start), status=wl.status, capacity=wl.capacity, used=used, run_tag=wl.run_tag,
                model_version_id=wl.model_version_id, items=[
                    dict(item_id=i.item_id, rank=i.rank, asset_id=i.asset_id, code=A[i.asset_id].asset_code if i.asset_id in A else None,
                         type=A[i.asset_id].asset_type if i.asset_id in A else None, street=A[i.asset_id].street_class if i.asset_id in A else None,
                         crit=A[i.asset_id].criticality if i.asset_id in A else None, lon=A[i.asset_id].lon if i.asset_id in A else None,
                         lat=A[i.asset_id].lat if i.asset_id in A else None, action=i.action, action_ar=ACTION_AR.get(i.action, i.action),
                         p=round(i.p_fail, 4), risk_sar=round(i.risk_sar, 1), reason=i.reason, status=i.status, override_reason=i.override_reason,
                         outcome=(dict(finding=outcomes[i.item_id].finding, action_taken=outcomes[i.item_id].action_taken,
                                       cost=outcomes[i.item_id].cost_sar, at=outcomes[i.item_id].visited_at.isoformat()) if i.item_id in outcomes else None))
                    for i in sorted(wl.items, key=lambda x: x.rank)])


@router.get("/current")
def current(db: Session = Depends(get_db), u: User = Depends(require("supervisor", "manager", "technician"))):
    wk = db.query(func.max(WeeklyList.week_start)).filter(WeeklyList.run_tag == "live").scalar()
    if not wk:
        raise HTTPException(404, "no weekly list yet; run plan")
    return _serialise(db, db.query(WeeklyList).filter_by(week_start=wk, run_tag="live").first())


@router.get("")
def history(limit: int = 12, db: Session = Depends(get_db), u: User = Depends(require("supervisor", "manager"))):
    rows = db.query(WeeklyList).filter_by(run_tag="live").order_by(WeeklyList.week_start.desc()).limit(limit).all()
    return [dict(list_id=w.list_id, week_start=str(w.week_start), status=w.status, capacity=w.capacity, n=len(w.items)) for w in rows]


@router.get("/{list_id}")
def one(list_id: str, db: Session = Depends(get_db), u: User = Depends(require("supervisor", "manager", "technician"))):
    wl = db.get(WeeklyList, list_id)
    if not wl:
        raise HTTPException(404, "list not found")
    return _serialise(db, wl)


class Decision(BaseModel):
    status: str  # approved | overridden | skipped
    override_reason: str | None = None
    action: str | None = None  # supervisor may change the action when overriding


@router.patch("/items/{item_id}")
def decide(item_id: str, body: Decision, db: Session = Depends(get_db), u: User = Depends(require("supervisor"))):
    i = db.get(ListItem, item_id)
    if not i:
        raise HTTPException(404, "item not found")
    if body.status not in ("approved", "overridden", "skipped"):
        raise HTTPException(400, "status must be approved|overridden|skipped")
    if body.status in ("overridden", "skipped") and not (body.override_reason or "").strip():
        raise HTTPException(400, "override_reason is required when overriding or skipping")
    before = dict(status=i.status, action=i.action, override_reason=i.override_reason)
    i.status = body.status; i.override_reason = body.override_reason
    if body.action and body.status == "overridden":
        if body.action not in ACTION_AR:
            raise HTTPException(400, "action must be inspect|service|replace")
        i.action = body.action
    i.decided_by, i.decided_at = u.username, datetime.utcnow()
    audit(db, u.username, "list_item.decide", "list_item", item_id, before, dict(status=i.status, action=i.action, override_reason=i.override_reason))
    db.commit()
    return dict(item_id=i.item_id, status=i.status, action=i.action, override_reason=i.override_reason)


@router.post("/{list_id}/approve")
def approve_all(list_id: str, db: Session = Depends(get_db), u: User = Depends(require("supervisor"))):
    wl = db.get(WeeklyList, list_id)
    if not wl:
        raise HTTPException(404, "list not found")
    n = 0
    for i in wl.items:
        if i.status == "proposed":
            i.status, i.decided_by, i.decided_at = "approved", u.username, datetime.utcnow(); n += 1
    wl.status = "approved"
    audit(db, u.username, "weekly_list.approve", "weekly_list", list_id, None, dict(approved_items=n))
    db.commit()
    return dict(list_id=list_id, status=wl.status, approved=n)
