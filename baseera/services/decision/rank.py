"""Decision engine — one declared rule, no hidden model.

risk_sar   = p_fail × [ planned_cost × (emergency_multiplier − 1) + consequence_units × consequence_sar ]
priority   = risk_sar × intervention_efficacy ÷ planned_cost          (risk removed per riyal)
list       = assets with p_fail ≥ alert_probability, by priority, until crew capacity;
             critical assets (crossing / hospital / school / cabinet) above the threshold displace the weakest non-critical item.
action     = inspect (p < 0.35) · service (0.35–0.70) · replace (≥ 0.70 or beyond design life)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ...core.catalog import consequence_units_of, design_life, is_node
from ...core.config import get_settings

CRIT_W = {"none": 1.0, "mosque": 1.6, "school": 2.0, "crossing": 2.4, "hospital": 3.0}
ROAD_W = {"main": 1.8, "sec": 1.0}
ACTION_AR = {"inspect": "فحص", "service": "صيانة", "replace": "استبدال"}
GROUP_AR = {"symptoms": "أعراض مرصودة على الأصل", "network": "انقطاعات جزئية على نفس الدائرة", "weather": "الحرارة والأمطار",
            "history": "سجل الأعطال السابقة", "asset": "عمر الأصل ونوعه", "telemetry": "إشارات الحساسات (شذوذ واتجاه)", "environment": "الإجهاد البيئي SESI والعمر المكافئ", "graph": "الاعتماديات (ما يتأثر بعطله)"}


@dataclass
class RankedAsset:
    asset_id: str
    p_fail: float
    risk_sar: float
    priority: float
    action: str
    critical: bool
    reason: str


def consequence_units(street_class: str, criticality: str, kind: str, asset_type: str = "LED") -> float:
    return ROAD_W.get(street_class, 1.0) * CRIT_W.get(criticality, 1.0) * consequence_units_of(asset_type)


def planned_cost(asset_type: str) -> float:
    return float(get_settings().cost_planned.get(asset_type, 650))


def is_critical(street_class: str, criticality: str, kind: str, asset_type: str = "LED") -> bool:
    return is_node(asset_type) or criticality in {"crossing", "hospital", "school"}


def action_for(p: float, age_y: float, asset_type: str) -> str:
    if p >= 0.70 or age_y > design_life(asset_type):
        return "replace"
    if p >= 0.35:
        return "service"
    return "inspect"


def reason_line(explanation: dict | None, last_symptom: str | None, days_since_fail: float | None) -> str:
    parts = []
    if explanation:
        top = sorted(explanation.items(), key=lambda kv: -kv[1])[:2]
        parts += [GROUP_AR.get(g, g) for g, v in top if v > 0.005]
    if last_symptom:
        parts.append(f"آخر علامة: {last_symptom}")
    if days_since_fail is not None and days_since_fail < 999:
        parts.append(f"آخر عطل قبل {int(days_since_fail)} يومًا")
    return " · ".join(parts) or "احتمال مرتفع بحسب النموذج"


def score_frame(df: pd.DataFrame) -> pd.DataFrame:
    """df needs: asset_id, p_fail, asset_type, street_class, criticality, kind, age_y. Adds risk_sar, priority, action, critical."""
    s = get_settings()
    out = df.copy()
    cost = out.asset_type.map(planned_cost)
    if "cof_total" in out.columns:   # v0.4: multi-dimensional, interconnected consequences from decision/cof.py
        out["risk_sar"] = out.p_fail * out.cof_total
    else:
        cof = [consequence_units(r, c, k, t) for r, c, k, t in zip(out.street_class, out.criticality, out.kind, out.asset_type)]
        out["risk_sar"] = out.p_fail * (cost * (s.emergency_multiplier - 1) + pd.Series(cof, index=out.index) * s.consequence_sar_per_unit)
    out["priority"] = out.risk_sar * s.intervention_efficacy / cost
    out["action"] = [action_for(p, a, t) for p, a, t in zip(out.p_fail, out.age_y, out.asset_type)]
    out["critical"] = [is_critical(r, c, k, t) for r, c, k, t in zip(out.street_class, out.criticality, out.kind, out.asset_type)]
    return out


def build_list(scored: pd.DataFrame, capacity: int | None = None) -> pd.DataFrame:
    """Returns the ranked weekly list (rank 1..capacity)."""
    s = get_settings(); K = capacity or s.crew_jobs_per_week
    cand = scored[scored.p_fail >= s.alert_probability].sort_values("priority", ascending=False)
    chosen = cand.head(K).copy()
    left = cand.iloc[K:]
    crit_left = left[left.critical]
    if len(crit_left):
        non_crit = chosen[~chosen.critical].sort_values("priority")
        swaps = min(len(crit_left), len(non_crit))
        if swaps:
            chosen = pd.concat([chosen.drop(non_crit.index[:swaps]), crit_left.head(swaps)])
    chosen = chosen.sort_values("priority", ascending=False).reset_index(drop=True)
    chosen["rank"] = range(1, len(chosen) + 1)
    return chosen
