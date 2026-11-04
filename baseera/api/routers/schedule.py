"""Risk–cost optimiser view: tiers, crew routes, budget Pareto frontier, Saudi constraints banner."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.catalog import CATEGORIES, MODES
from ...core.config import get_settings
from ...core.db import get_db
from ...core.models import Asset, ListItem, Prediction, User, WeeklyList, WorkOrder
from ...core.security import audit, require
from ...services.decision.calendar import week_banner
from ...services.decision.optimize import TIER_AR
from ...services.decision.rank import ACTION_AR
from ...services.plan import pareto_curve, plan_week

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("/current")
def current(db: Session = Depends(get_db), u: User = Depends(require("supervisor", "manager", "technician"))):
    wk = db.query(func.max(WeeklyList.week_start)).filter(WeeklyList.run_tag == "live").scalar()
    if not wk:
        raise HTTPException(404, "no weekly list yet")
    wl = db.query(WeeklyList).filter_by(week_start=wk, run_tag="live").first()
    A = {a.asset_id: a for a in db.query(Asset).filter(Asset.asset_id.in_([i.asset_id for i in wl.items])).all()} if wl.items else {}
    P = {p.asset_id: p for p in db.query(Prediction).filter(Prediction.week_start == wk, Prediction.run_tag == "live", Prediction.asset_id.in_(list(A))).all()} if A else {}
    wos = {w.item_id: w for w in db.query(WorkOrder).filter(WorkOrder.item_id.isnot(None)).all()}
    s = get_settings()
    items = []
    for i in sorted(wl.items, key=lambda x: (x.route or 99, x.seq or 99, x.rank)):
        a = A[i.asset_id]; p = P.get(i.asset_id)
        items.append(dict(item_id=i.item_id, rank=i.rank, code=a.asset_code, category=a.category, category_ar=CATEGORIES[a.category]["ar"], type=a.asset_type, lon=a.lon, lat=a.lat,
                          crit=a.criticality, p=round(i.p_fail, 3), risk_sar=round(i.risk_sar), cost=float(s.cost_planned.get(a.asset_type, 650)) * (s.rideby_cost_share if i.grouped else 1),
                          return_per_riyal=round(i.risk_sar * s.intervention_efficacy / (float(s.cost_planned.get(a.asset_type, 650)) * (s.rideby_cost_share if i.grouped else 1)), 2),
                          action=i.action, action_ar=ACTION_AR.get(i.action), tier=i.tier, tier_ar=TIER_AR.get(i.tier or "planned"), route=i.route, seq=i.seq, grouped=i.grouped,
                          safe_window=i.safe_window, status=i.status, mode=(p.mode_pred if p else None), mode_ar=(MODES[p.mode_pred][1] if p and p.mode_pred in MODES else None),
                          window=([p.window_lo, p.window_hi] if p and p.window_lo is not None else None), reason=i.reason, work_order=(wos[i.item_id].wo_id if i.item_id in wos else None)))
    tiers = {t: sum(1 for i in items if i["tier"] == t) for t in TIER_AR}
    routes = {}
    for i in items:
        routes.setdefault(i["route"] or 0, []).append(i)
    return dict(week_start=str(wk), status=wl.status, capacity=wl.capacity, budget=s.weekly_budget_sar, crews=s.crews, items=items, tiers=tiers,
                tiers_ar=TIER_AR, routes=[dict(route=r, n=len(v), cost=round(sum(x["cost"] for x in v)), risk=round(sum(x["risk_sar"] for x in v)), items=v) for r, v in sorted(routes.items())],
                grouped=sum(1 for i in items if i["grouped"]), total_cost=round(sum(i["cost"] for i in items)), total_risk=round(sum(i["risk_sar"] for i in items)),
                banner=week_banner(wk), pareto=pareto_curve(db, wk, wl.capacity))


class Replan(BaseModel):
    budget: float | None = None
    capacity: int | None = None


@router.post("/replan")
def replan(body: Replan, db: Session = Depends(get_db), u: User = Depends(require("supervisor", "admin"))):
    """Re-run the optimiser for the current week with a different budget/capacity (only while the list is still proposed)."""
    wk = db.query(func.max(WeeklyList.week_start)).filter(WeeklyList.run_tag == "live").scalar()
    if not wk:
        raise HTTPException(404, "no weekly list yet")
    wl = db.query(WeeklyList).filter_by(week_start=wk, run_tag="live").first()
    if wl.status != "proposed":
        raise HTTPException(409, "the list was already approved; replanning would discard decisions")
    new = plan_week(db, wk, capacity=body.capacity, budget=body.budget, replace=True)
    audit(db, u.username, "schedule.replan", "weekly_list", new.list_id, None, dict(budget=body.budget, capacity=body.capacity, items=len(new.items)))
    db.commit()
    return dict(list_id=new.list_id, items=len(new.items))
