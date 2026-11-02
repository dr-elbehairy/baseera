"""Weekly planning: score the week, build the capacity-limited list with the decision engine, persist it."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.models import ListItem, Observation, WeeklyList
from .decision.rank import build_list, reason_line
from .model.core import promoted, score


def plan_week(db: Session, week_start: date, run_tag: str = "live", capacity: int | None = None, replace: bool = True) -> WeeklyList:
    s = get_settings(); K = capacity or s.crew_jobs_per_week
    mv = promoted(db)
    if mv is None:
        raise RuntimeError("no promoted model")
    existing = db.query(WeeklyList).filter_by(week_start=week_start, run_tag=run_tag).first()
    if existing:
        if not replace or existing.status != "proposed":
            return existing  # never overwrite a list the supervisor already acted on
        db.delete(existing); db.flush()
    sc = score(db, week_start, mv, run_tag=run_tag, explain_top=max(K * 3, 50))
    chosen = build_list(sc, K)
    # last recorded symptom per listed asset (for the one-line reason)
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
        db.add(ListItem(list_id=wl.list_id, asset_id=r.asset_id, rank=int(r.rank), action=r.action, p_fail=float(r.p_fail), risk_sar=float(r.risk_sar),
                        reason=reason_line(expl, last_sym.get(r.asset_id), getattr(r, "days_since_last_fail", None))))
    db.commit()
    return wl
