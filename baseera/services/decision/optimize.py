"""Risk–cost optimiser (layer 6).

select()  — mixed-integer selection: maximise Σ risk removed (p × CoF × efficacy) subject to crew capacity and weekly
            budget; critical assets above the alert threshold are forced in. scipy.optimize.milp (HiGHS); greedy fallback.
pareto()  — the budget frontier: for a sweep of budgets, the share of total risk removed → the decision-maker chooses the
            operating point with eyes open ("بميزانية 60k نزيل 71%، بـ90k نزيل 85%").
routes()  — group the selected jobs into crew routes (k-means on lon/lat, nearest-neighbour order) and attach ride-along
            jobs: non-selected assets above threshold within `rideby_radius_m` of a route, costed at `rideby_cost_share`.
tier()    — فوري / عاجل / مخطط / مراقبة from risk and the failure window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

from ...core.config import get_settings
from ...core.geo import haversine_m

TIER_AR = {"immediate": "فوري", "urgent": "عاجل", "planned": "مخطط", "monitor": "مراقبة"}


def tier(p: float, risk: float, risk_q90: float, risk_q97: float, window_lo: int | None, window_hi: int | None, window_mid: int | None, L: int) -> str:
    """As in the vision: فوري = high risk and the expected failure day falls inside the crew's lead time L (the window may close
    before we can act) · عاجل = high risk with the expected day within the month, or top-3% risk · مخطط = above the alert
    threshold · مراقبة = everything else."""
    if risk >= risk_q90 and window_mid is not None and window_mid <= L:
        return "immediate"
    if risk >= risk_q97 or (risk >= risk_q90 and window_mid is not None and window_mid <= 30) or (window_hi is not None and window_hi <= 21 and p >= 0.35):
        return "urgent"
    if p >= get_settings().alert_probability:
        return "planned"
    return "monitor"


def select(cand: pd.DataFrame, capacity: int, budget: float | None = None) -> pd.Index:
    """cand: candidates above threshold with columns risk_removed, cost, critical. Returns index of chosen rows."""
    n = len(cand)
    if n == 0:
        return cand.index
    gain = cand.risk_removed.values.astype(float); cost = cand.cost.values.astype(float); crit = cand.critical.values.astype(bool)
    A = [np.ones(n)]; lb = [0]; ub = [capacity]
    if budget is not None:
        A.append(cost); lb.append(0); ub.append(max(budget, float(cost[crit].sum())))
    lower = np.where(crit, 1.0, 0.0)
    if crit.sum() > capacity:  # more critical items than capacity: keep the riskiest critical ones
        order = np.argsort(-gain * crit); lower[:] = 0; lower[order[:capacity]] = 1
    try:
        res = milp(c=-gain, constraints=LinearConstraint(np.vstack(A), lb, ub), integrality=np.ones(n), bounds=Bounds(lower, np.ones(n)),
                   options={"time_limit": 10})
        if res.success and res.x is not None:
            return cand.index[res.x > 0.5]
    except Exception:
        pass
    # greedy fallback: by gain per riyal, critical first
    order = sorted(range(n), key=lambda i: (-crit[i], -(gain[i] / max(cost[i], 1))))
    chosen, spent = [], 0.0
    for i in order:
        if len(chosen) >= capacity: break
        if budget is not None and spent + cost[i] > budget and not crit[i]: continue
        chosen.append(i); spent += cost[i]
    return cand.index[chosen]


def pareto(cand: pd.DataFrame, capacity: int, budgets: list[float]) -> list[dict]:
    total = float(cand.risk_removed.sum()) or 1.0
    out = []
    for b in budgets:
        idx = select(cand, capacity, b); ch = cand.loc[idx]
        out.append(dict(budget=b, n_jobs=int(len(ch)), cost=float(ch.cost.sum()), risk_removed=float(ch.risk_removed.sum()), share=round(float(ch.risk_removed.sum()) / total, 3)))
    return out


def routes(chosen: pd.DataFrame, others: pd.DataFrame, crews: int, radius_m: float, cost_share: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign route/seq to chosen jobs; return (chosen with route/seq, ride-along rows picked from others)."""
    chosen = chosen.copy()
    if chosen.empty:
        return chosen, others.iloc[0:0]
    k = max(1, min(crews, len(chosen)))
    pts = chosen[["lon", "lat"]].values.astype(float)
    # k-means (small, deterministic)
    rng = np.random.default_rng(0); centers = pts[rng.choice(len(pts), k, replace=False)]
    for _ in range(25):
        lab = np.argmin(((pts[:, None, :] - centers[None, :, :]) ** 2).sum(-1), axis=1)
        for j in range(k):
            if (lab == j).any(): centers[j] = pts[lab == j].mean(0)
    chosen["route"] = lab + 1
    # nearest-neighbour order inside each route
    seq = np.zeros(len(chosen), int)
    for j in range(1, k + 1):
        ids = np.where(chosen.route.values == j)[0]
        if not len(ids): continue
        cur = ids[np.argmax(chosen.priority.values[ids])]; order = [cur]; rest = set(ids) - {cur}
        while rest:
            nxt = min(rest, key=lambda i: haversine_m(pts[cur][0], pts[cur][1], pts[i][0], pts[i][1])); order.append(nxt); rest.remove(nxt); cur = nxt
        for s_, i in enumerate(order, 1): seq[i] = s_
    chosen["seq"] = seq
    # ride-alongs: others above threshold within radius of any chosen point on a route
    ride = []
    if len(others):
        op = others[["lon", "lat"]].values.astype(float)
        for i in range(len(others)):
            d = [haversine_m(op[i][0], op[i][1], p[0], p[1]) for p in pts]
            j = int(np.argmin(d))
            if d[j] <= radius_m:
                r = others.iloc[i].copy(); r["route"] = int(chosen.route.values[j]); r["seq"] = int(chosen.seq.values[j]); r["grouped"] = True
                r["cost"] = float(r["cost"]) * cost_share; r["priority"] = float(r["risk_removed"]) / max(float(r["cost"]), 1.0); ride.append(r)
    ride_df = pd.DataFrame(ride) if ride else others.iloc[0:0]
    return chosen, ride_df
