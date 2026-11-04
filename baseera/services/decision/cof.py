"""Consequence of failure (CoF) in SAR, multi-dimensional and interconnected (ISO 55000 / ISO 31000 style):
  financial   emergency premium over the planned job
  service     users affected × duration, amplified by the dependency graph (what else goes dark when this fails)
  safety      criticality (crossing / school / hospital) × category safety factor
  environment leaks, pooling, energy waste
  reputation  reports and public visibility (main roads)
Every term is a parameter in Settings so the municipality can calibrate it; the breakdown is stored with every prediction.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from ...core.catalog import COF_FACTORS, consequence_units_of
from ...core.config import get_settings
from ...core.models import Dependency

CRIT_W = {"none": 1.0, "mosque": 1.6, "school": 2.0, "crossing": 2.4, "hospital": 3.0}
ROAD_W = {"main": 1.8, "sec": 1.0}


def dependents(db: Session) -> dict[str, float]:
    """asset_id → weighted number of assets whose service depends on it (one level + half of the second level)."""
    edges = db.query(Dependency).all()
    kids: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for e in edges:
        kids[e.parent_asset_id].append((e.child_asset_id, e.weight))
    out = {}
    for p, ch in kids.items():
        total = sum(w for _, w in ch)
        for c, w in ch:
            total += 0.5 * sum(w2 for _, w2 in kids.get(c, [])) * w
        out[p] = total
    return out


def breakdown(asset_type: str, category: str, street_class: str, criticality: str, n_dependents: float, month: int | None = None) -> dict:
    s = get_settings()
    safety_f, env_f, rep_f = COF_FACTORS.get(category, (1.0, 0.2, 1.0))
    crit = CRIT_W.get(criticality, 1.0); road = ROAD_W.get(street_class, 1.0)
    planned = float(s.cost_planned.get(asset_type, 650))
    financial = planned * (s.emergency_multiplier - 1)
    service = consequence_units_of(asset_type) * road * crit * s.consequence_sar_per_unit + n_dependents * s.dependency_service_sar
    safety = s.cof_safety_sar * crit * safety_f
    environment = s.cof_environment_sar * env_f
    reputation = s.cof_reputation_sar * road * rep_f
    boost = 1.0
    if category == "pumping" and month in s.flood_season_months:
        boost = s.flood_readiness_boost
    total = (financial + service + safety + environment + reputation) * boost
    return dict(financial=round(financial), service=round(service), safety=round(safety), environment=round(environment), reputation=round(reputation),
                season_boost=boost, total=round(total), planned_cost=planned, n_dependents=round(n_dependents, 1))
