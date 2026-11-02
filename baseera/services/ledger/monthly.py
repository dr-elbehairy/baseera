"""Monthly ledger: PFR@L (2 / 7 / 14 / own L), emergency share, dark days, symptom capture rate — and drift detection."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.models import FailureEvent, LedgerMonth, Observation, WorkOrder
from .pfr import annotate_leads, pfr_at_L


def _month(d: date) -> str:
    return d.strftime("%Y-%m")


def compute_months(db: Session, run_tag: str = "live", zone: str = "all", months: list[str] | None = None) -> list[LedgerMonth]:
    s = get_settings()
    annotate_leads(db, run_tag)
    fails = db.query(FailureEvent).filter(FailureEvent.run_tag == run_tag).all()
    by_m: dict[str, list[FailureEvent]] = defaultdict(list)
    for f in fails:
        by_m[_month(f.failed_on)].append(f)
    wos = db.query(WorkOrder).all()
    wo_m: dict[str, list[WorkOrder]] = defaultdict(list)
    for w in wos:
        wo_m[_month(w.opened_at.date())].append(w)
    obs = db.query(Observation.asset_id, Observation.observed_at).all()
    obs_by_asset: dict[str, list[date]] = defaultdict(list)
    for a, at in obs:
        obs_by_asset[a].append(at.date())
    out = []
    for m in sorted(months or by_m.keys()):
        fl = by_m.get(m, [])
        n = len(fl)
        pfr = {str(L): pfr_at_L(fl, L) for L in s.lead_days}; pfr["own"] = pfr_at_L(fl)
        wm = wo_m.get(m, [])
        emerg = (sum(1 for w in wm if w.kind == "emergency") / len(wm)) if wm else None
        dark = sum(f.days_dark or 0 for f in fl) if fl else 0
        captured = sum(1 for f in fl if any(0 <= (f.failed_on - d).days <= 30 for d in obs_by_asset.get(f.asset_id, []))) / n if n else None
        row = db.query(LedgerMonth).filter_by(month=m, run_tag=run_tag, zone=zone).first() or LedgerMonth(month=m, run_tag=run_tag, zone=zone)
        row.n_failures, row.pfr, row.emergency_share, row.dark_days, row.symptom_capture_rate = n, pfr, emerg, dark, captured
        db.add(row); out.append(row)
    db.commit()
    return out


def drift(db: Session, run_tag: str = "live", L: str = "own", drop: float = 0.10) -> dict:
    """Flag when PFR@L fell by ≥ `drop` for two consecutive months versus the preceding three-month mean."""
    rows = db.query(LedgerMonth).filter_by(run_tag=run_tag, zone="all").order_by(LedgerMonth.month).all()
    vals = [(r.month, (r.pfr or {}).get(L)) for r in rows if r.n_failures >= 5 and (r.pfr or {}).get(L) is not None]
    if len(vals) < 5:
        return {"status": "insufficient_history", "months": len(vals)}
    base = sum(v for _, v in vals[-5:-2]) / 3
    last2 = [v for _, v in vals[-2:]]
    flag = all(v <= base - drop for v in last2)
    return {"status": "drift" if flag else "stable", "baseline": round(base, 3), "last_two": last2, "months": [m for m, _ in vals[-2:]],
            "action": "retrain" if flag else None}
