"""Weekly planning (layer 6): score → consequences → MILP selection within crew capacity and budget → crew routes with
ride-along grouping → Saudi constraints → persisted list with tiers, routes and safe windows."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.models import ListItem, Observation, WeeklyList
from .decision.calendar import constraints_for
from .decision.optimize import pareto, routes, select
from .decision.rank import build_list, reason_line
from .model.core import promoted, score


def candidates(sc: pd.DataFrame) -> pd.DataFrame:
    s = get_settings()
    c = sc[sc.p_fail >= s.alert_probability].copy()
    c["risk_removed"] = c.risk_sar * s.intervention_efficacy
    c["cost"] = c.asset_type.map(lambda t: float(s.cost_planned.get(t, 650)))
    return c


def plan_week(db: Session, week_start: date, run_tag: str = "live", capacity: int | None = None, replace: bool = True, budget: float | None = None) -> WeeklyList:
    s = get_settings(); K = capacity or s.crew_jobs_per_week; B = budget if budget is not None else s.weekly_budget_sar
    mv = promoted(db)
    if mv is None:
        raise RuntimeError("no promoted model")
    existing = db.query(WeeklyList).filter_by(week_start=week_start, run_tag=run_tag).first()
    if existing:
        if not replace or existing.status != "proposed":
            return existing  # never overwrite a list the supervisor already acted on
        db.delete(existing); db.flush()
    sc = score(db, week_start, mv, run_tag=run_tag, explain_top=max(K * 3, 60))
    cand = candidates(sc)
    if run_tag == "live":
        idx = select(cand, K, B)
        chosen = cand.loc[idx]
        pool = sc[(sc.p_fail >= s.alert_probability / 2) & (~sc.asset_id.isin(chosen.asset_id))].copy()
        pool["risk_removed"] = pool.risk_sar * s.intervention_efficacy; pool["cost"] = pool.asset_type.map(lambda t: float(s.cost_planned.get(t, 650)))
        others = pool
        chosen, ride = routes(chosen, others, s.crews, s.rideby_radius_m, s.rideby_cost_share)
        if len(ride):
            chosen = pd.concat([chosen, ride], ignore_index=True)
        else:
            chosen["grouped"] = False
    else:   # backtest keeps the deterministic capacity rule (same crew, no budget) so PFR@L stays comparable across runs
        chosen = build_list(sc, K); chosen["grouped"] = False; chosen["route"] = None; chosen["seq"] = None
    chosen = chosen.sort_values(["grouped", "priority"], ascending=[True, False]).reset_index(drop=True)
    chosen["rank"] = range(1, len(chosen) + 1)
    last_sym = {}
    if len(chosen):
        obs = (db.query(Observation.asset_id, Observation.symptom_code, Observation.observed_at)
               .filter(Observation.asset_id.in_(chosen.asset_id.tolist()), Observation.observed_at < pd.Timestamp(week_start)).all())
        for a, code, at in sorted(obs, key=lambda r: r[2]):
            last_sym[a] = code
    wl = WeeklyList(week_start=week_start, model_version_id=mv.model_version_id, capacity=K, run_tag=run_tag)
    db.add(wl); db.flush()
    for r in chosen.itertuples():
        expl = r.explanation if isinstance(r.explanation, dict) else None
        tier = getattr(r, "tier", None) or "planned"
        con = constraints_for(week_start, r.category, tier)
        db.add(ListItem(list_id=wl.list_id, asset_id=r.asset_id, rank=int(r.rank), action=r.action, p_fail=float(r.p_fail), risk_sar=float(r.risk_sar),
                        reason=reason_line(expl, last_sym.get(r.asset_id), getattr(r, "days_since_last_fail", None)), tier=tier,
                        route=(None if pd.isna(getattr(r, "route", None)) else int(r.route)), seq=(None if pd.isna(getattr(r, "seq", None)) else int(r.seq)),
                        grouped=bool(getattr(r, "grouped", False)), safe_window=con["safe_window"]))
    db.commit()
    return wl


def pareto_curve(db: Session, week_start: date, capacity: int | None = None) -> list[dict]:
    """Budget frontier from the stored predictions of the week (no re-scoring)."""
    from ..core.models import Asset, Prediction
    s = get_settings(); K = capacity or s.crew_jobs_per_week
    P = db.query(Prediction).filter_by(week_start=week_start, run_tag="live").all()
    if not P:
        return []
    A = {a.asset_id: a for a in db.query(Asset).all()}
    sc = pd.DataFrame([dict(asset_id=p.asset_id, p_fail=p.p_fail, risk_sar=p.risk_sar, priority=p.priority, asset_type=A[p.asset_id].asset_type,
                            critical=(A[p.asset_id].criticality in ("crossing", "hospital", "school") or A[p.asset_id].kind in ("cabinet", "panel"))) for p in P])
    cand = candidates(sc)
    base = s.weekly_budget_sar
    budgets = sorted(set([round(base * f) for f in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)]))
    return pareto(cand, K, budgets)
