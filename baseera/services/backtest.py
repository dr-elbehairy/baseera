"""Temporal backtest — the regression test of the whole system.

Train on everything labelled before `split`, then walk the test period week by week: score → plan (proposed list) →
measure leads against the failures that actually happened. Compares Baseera with the age rule (same crew capacity)
and with today's reactive practice (no list). Writes run_tag='backtest' rows and returns a JSON-able summary that the
web ledger and the hackathon deck read. Nothing here is hand-typed.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..core.catalog import CATEGORIES, MODE_AR, MODE_CLASS as CLASS
from ..core.config import get_settings
from ..core.models import Asset, FailureEvent, LedgerMonth, ListItem, Prediction, WeeklyList
from .features.build import frame, week_starts_between
from .ledger.failures import derive_failures
from .ledger.monthly import compute_months
from .ledger.pfr import L_for, annotate_leads, leads_for_failures
from .model.core import train
from .plan import plan_week



def _clear(db: Session) -> None:
    for model in (ListItem,):
        ids = [l.list_id for l in db.query(WeeklyList.list_id).filter(WeeklyList.run_tag == "backtest")]
        if ids:
            db.execute(delete(ListItem).where(ListItem.list_id.in_(ids)))
    db.execute(delete(WeeklyList).where(WeeklyList.run_tag == "backtest"))
    db.execute(delete(Prediction).where(Prediction.run_tag == "backtest"))
    db.execute(delete(FailureEvent).where(FailureEvent.run_tag == "backtest"))
    db.execute(delete(LedgerMonth).where(LedgerMonth.run_tag == "backtest"))
    db.commit()


def run_backtest(db: Session, split: date, end: date, out_path: str | None = None, train_model: bool = True) -> dict:
    s = get_settings()
    _clear(db)
    derive_failures(db, run_tag="backtest")
    if train_model:
        mv = train(db, as_of=split, name="backtest", force=True)
    else:
        from .model.core import promoted
        mv = promoted(db)
    weeks = [w for w in week_starts_between(split, end - timedelta(days=s.horizon_days))]
    lists: dict[date, set[str]] = {}
    for w in weeks:
        wl = plan_week(db, w, run_tag="backtest")
        lists[w] = {i.asset_id for i in wl.items}
    # failures in the test window
    fails = db.query(FailureEvent).filter(FailureEvent.run_tag == "backtest", FailureEvent.failed_on >= weeks[0], FailureEvent.failed_on < end).all()
    annotate_leads(db, "backtest", weeks[0], end)
    A = {a.asset_id: a for a in db.query(Asset).all()}
    # age-rule baseline: oldest assets first, same capacity
    ages = sorted(A.values(), key=lambda a: a.install_date or date(2000, 1, 1))
    order = [a.asset_id for a in ages]; ptr = 0; age_lists = {}
    for w in weeks:
        age_lists[w] = set(order[(ptr % len(order)):(ptr % len(order)) + s.crew_jobs_per_week]); ptr += s.crew_jobs_per_week
    pairs = [(f.asset_id, f.failed_on) for f in fails]
    lead_b = np.array([(-1 if f.lead_days is None else f.lead_days) for f in fails])
    lead_a = np.array(leads_for_failures(pairs, age_lists))
    own_L = np.array([L_for(f.failure_mode) for f in fails])
    cls = np.array([CLASS.get(f.failure_mode or "", "C") for f in fails])
    eff = s.intervention_efficacy
    averted_b = eff * (lead_b >= own_L)                       # expected share of each failure averted by a timely planned job
    dark = np.array([f.days_dark or 0 for f in fails], float)
    cost_pl = np.array([float(s.cost_planned.get(A[f.asset_id].asset_type, 650)) for f in fails])
    n_items = sum(len(v) for v in lists.values())
    hits = 0
    fail_by_asset: dict[str, list[date]] = {}
    for f in fails:
        fail_by_asset.setdefault(f.asset_id, []).append(f.failed_on)
    for w, ids in lists.items():
        for a in ids:
            if any(0 <= (d - w).days < 30 for d in fail_by_asset.get(a, [])):
                hits += 1
    by_mode = []
    for mode in sorted(set(f.failure_mode for f in fails if f.failure_mode)):
        m = np.array([f.failure_mode == mode for f in fails])
        by_mode.append(dict(mode=mode, mode_ar=MODE_AR.get(mode, mode), cls=CLASS.get(mode, "C"), n=int(m.sum()), L=L_for(mode),
                            pfr_L=round(float((lead_b[m] >= own_L[m]).mean()), 3), pfr7=round(float((lead_b[m] >= 7).mean()), 3),
                            median_lead=(float(np.median(lead_b[m][lead_b[m] >= 0])) if (lead_b[m] >= 0).any() else None)))
    cat = np.array([A[f.asset_id].category for f in fails])
    by_category = []
    for c in CATEGORIES:
        m = cat == c
        if m.any():
            by_category.append(dict(category=c, ar=CATEGORIES[c]["ar"], n=int(m.sum()), n_assets=sum(1 for a in A.values() if a.category == c),
                                    pfr_L=round(float((lead_b[m] >= own_L[m]).mean()), 3), pfr_age=round(float((lead_a[m] >= own_L[m]).mean()), 3),
                                    emergency_share=round(float(1 - averted_b[m].mean()), 3)))
    months = compute_months(db, run_tag="backtest")
    res = dict(
        model_version_id=mv.model_version_id, metrics=mv.metrics, gates=mv.gates, split=str(split), end=str(end), weeks=len(weeks),
        n_assets=len(A), n_failures=len(fails), capacity=s.crew_jobs_per_week,
        pfr={str(L): dict(baseera=round(float((lead_b >= L).mean()), 3), age_rule=round(float((lead_a >= L).mean()), 3), reactive=0.0) for L in s.lead_days},
        pfr_own_L=dict(baseera=round(float((lead_b >= own_L).mean()), 3), age_rule=round(float((lead_a >= own_L).mean()), 3), reactive=0.0,
                       predictable_only=round(float((lead_b[cls != "C"] >= own_L[cls != "C"]).mean()), 3) if (cls != "C").any() else None),
        precision30=round(hits / max(1, n_items), 3), alerts_per_week=round(n_items / max(1, len(weeks)), 1), missed=int((lead_b < 0).sum()),
        emergency_share=dict(reactive=1.0, baseera=round(float(1 - averted_b.mean()), 3)),
        dark_days=dict(reactive=int(dark.sum()), baseera=int(round(float((dark * (1 - averted_b)).sum())))),
        cost=dict(reactive=int((cost_pl * s.emergency_multiplier).sum()),
                  baseera=int((cost_pl * (s.emergency_multiplier * (1 - averted_b) + averted_b)).sum())),
        lead_hist=dict(bins=["0–1", "2–6", "7–13", "14–20", "21–29", "30–45"], counts=np.histogram(lead_b[lead_b >= 0], bins=[0, 2, 7, 14, 21, 30, 46])[0].tolist()),
        by_mode=sorted(by_mode, key=lambda r: (r["cls"], -r["n"])), class_counts={c: int((cls == c).sum()) for c in "ABC"}, by_category=by_category,
        series=[dict(week=str(w), failures=int(sum(1 for f in fails if w <= f.failed_on < w + timedelta(days=7))),
                     anticipated=int(sum(1 for f, lb, L in zip(fails, lead_b, own_L) if w <= f.failed_on < w + timedelta(days=7) and lb >= L)),
                     listed=len(lists[w])) for w in weeks],
        months=[dict(month=m.month, n=m.n_failures, pfr=m.pfr, dark_days=m.dark_days, capture=m.symptom_capture_rate) for m in months],
        generated=str(date.today()), source_note="simulation" if all(a.source == "simulated" for a in A.values()) else "mixed/real",
    )
    out_path = out_path or os.path.join(s.data_dir, "backtest.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(res, open(out_path, "w"), ensure_ascii=False, indent=1, default=str)
    return res
