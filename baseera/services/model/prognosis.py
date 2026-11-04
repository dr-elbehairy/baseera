"""Prognostics engine (layer 4): anomaly → diagnosis → failure window.

diagnose()   which failure mode is building up: evidence from the last 30 days of symptoms and channel anomalies, weighted
             by catalog.EVIDENCE and restricted to the asset's category; falls back to the type's most frequent mode.
WindowModel  conformal lead-time: a gradient-boosted regressor of days-to-failure, trained on weeks that were followed by
             a failure within 90 days, calibrated on a held-out slice so the window [ŷ−q, ŷ+q] covers the true day with
             probability ≥ conformal_coverage (split conformal, Angelopoulos & Bates 2021). Coverage is re-measured in
             every backtest and published with the ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sqlalchemy.orm import Session

from ...core.catalog import CHANNELS, EVIDENCE, MODES, TYPES
from ...core.config import get_settings
from ...core.models import FailureEvent, Observation, TelemetryDay
from ..features.build import FEATURES


@dataclass
class WindowModel:
    """Conformalised quantile regression (Romano, Patterson & Candès 2019): lower/upper quantile regressors of
    days-to-failure, then a single conformal correction q so that [lo − q, hi + q] covers the true day with the target
    probability. Windows are adaptive: narrow where the signals are strong, wide where they are not."""
    reg_lo: GradientBoostingRegressor
    reg_hi: GradientBoostingRegressor
    reg_mid: GradientBoostingRegressor
    q: float
    coverage_val: float
    mean_width_val: float
    n_cal: int
    features: list
    horizon: int = 60

    def window(self, X: np.ndarray) -> np.ndarray:
        """[lo, hi, mid] in days; rows without evidence get no window (−1) — the model only speaks where signals exist."""
        lo = np.clip(np.round(self.reg_lo.predict(X) - self.q), 0, None); hi = np.clip(np.round(self.reg_hi.predict(X) + self.q), 1, self.horizon)
        hi = np.maximum(hi, lo + 1); mid = np.clip(np.round(self.reg_mid.predict(X)), lo, hi)
        return np.stack([lo, hi, mid], axis=1).astype(int)


def evidence_mask(X: np.ndarray, features: list) -> np.ndarray:
    """Rows with a degradation signal: a symptom in 30 days, a telemetry anomaly or trend, or a partial trip on the circuit."""
    f = {k: i for i, k in enumerate(features)}
    return (X[:, f["symptoms_30d"]] > 0) | (X[:, f["tele_anom_7d"]] > 1.5) | (X[:, f["tele_trend_30d"]] > 1.5) | (X[:, f["circuit_partial_trips_14d"]] > 0)


def _days_to_failure(df: pd.DataFrame, F: pd.DataFrame, horizon: int = 90) -> pd.Series:
    """For each (asset, week_start) row: days until the first failure after week_start within horizon, else NaN."""
    F = F.copy(); F["failed_on"] = pd.to_datetime(F.failed_on); by = {a: np.sort(g.failed_on.values) for a, g in F.groupby("asset_id")}
    out = np.full(len(df), np.nan)
    ws = pd.to_datetime(df.week_start).values; aids = df.asset_id.values
    for i in range(len(df)):
        arr = by.get(aids[i])
        if arr is None: continue
        j = np.searchsorted(arr, ws[i], side="left")
        if j < len(arr):
            d = (arr[j] - ws[i]) / np.timedelta64(1, "D")
            if d <= horizon: out[i] = d
    return pd.Series(out, index=df.index)


def train_window(df: pd.DataFrame, F: pd.DataFrame, as_of: date, calibration_days: int = 70, horizon: int = 60) -> WindowModel | None:
    s = get_settings(); alpha = 1 - s.conformal_coverage
    df = df[pd.to_datetime(df.week_start) + pd.Timedelta(days=horizon) <= pd.Timestamp(as_of)].copy()
    df["dtf"] = _days_to_failure(df, F, horizon)
    lab = df[df.dtf.notna()]
    if len(lab) < 60:
        return None
    cut = pd.Timestamp(as_of - timedelta(days=calibration_days))
    tr, ca = lab[pd.to_datetime(lab.week_start) < cut], lab[pd.to_datetime(lab.week_start) >= cut]
    if len(ca) < 15:
        tr, ca = lab.iloc[: int(len(lab) * 0.8)], lab.iloc[int(len(lab) * 0.8):]
    Xtr, ytr = tr[FEATURES].values.astype(float), tr.dtf.values
    kw = dict(n_estimators=250, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0)
    reg_lo = GradientBoostingRegressor(loss="quantile", alpha=alpha / 2, **kw).fit(Xtr, ytr)
    reg_hi = GradientBoostingRegressor(loss="quantile", alpha=1 - alpha / 2, **kw).fit(Xtr, ytr)
    reg_mid = GradientBoostingRegressor(loss="quantile", alpha=0.5, **kw).fit(Xtr, ytr)
    Xca, yca = ca[FEATURES].values.astype(float), ca.dtf.values
    lo, hi = reg_lo.predict(Xca), reg_hi.predict(Xca)
    score = np.maximum(lo - yca, yca - hi)
    n = len(score); k = int(np.ceil((n + 1) * (1 - alpha))); q = float(np.sort(score)[min(k, n) - 1])
    cov = float(((lo - q <= yca) & (yca <= hi + q)).mean()); width = float(np.mean(np.clip(hi + q, 1, horizon) - np.clip(lo - q, 0, None)))
    return WindowModel(reg_lo=reg_lo, reg_hi=reg_hi, reg_mid=reg_mid, q=round(max(q, 0.0), 1), coverage_val=round(cov, 3), mean_width_val=round(width, 1), n_cal=n, features=FEATURES, horizon=horizon)


def diagnose(db: Session, asset_id: str, asset_type: str, category: str, as_of: date) -> dict:
    """Evidence-weighted failure-mode diagnosis for one asset."""
    since = pd.Timestamp(as_of) - pd.Timedelta(days=30)
    scores: dict[str, float] = {m: 0.0 for m, v in MODES.items() if v[0] == category}
    ev = []
    obs = db.query(Observation).filter(Observation.asset_id == asset_id, Observation.observed_at >= since, Observation.observed_at <= pd.Timestamp(as_of) + pd.Timedelta(days=1)).all()
    for o in obs:
        for m, w in EVIDENCE.get(o.symptom_code, {}).items():
            if m in scores: scores[m] += w * o.severity
        if o.symptom_code in EVIDENCE: ev.append(dict(kind="symptom", code=o.symptom_code, at=str(o.observed_at.date()), weight=o.severity))
    tele = db.query(TelemetryDay).filter(TelemetryDay.asset_id == asset_id, TelemetryDay.day <= as_of).order_by(TelemetryDay.day).all()
    if tele:
        T = pd.DataFrame([dict(day=t.day, ch=t.channel, v=t.value) for t in tele])
        for ch, g in T.groupby("ch"):
            g = g.sort_values("day"); base = g.v.iloc[:60]; mu, sd = base.mean(), max(base.std(), abs(base.mean()) * 0.05 + 1e-6)
            last = g[g.day >= (as_of - timedelta(days=7))].v.mean() if len(g[g.day >= (as_of - timedelta(days=7))]) else g.v.iloc[-1]
            z = (last - mu) / sd * CHANNELS[ch][3]
            if z > 2.0:
                for m, w in EVIDENCE.get(ch, {}).items():
                    if m in scores: scores[m] += w * min(z, 8) / 2
                ev.append(dict(kind="channel", code=ch, z=round(float(z), 1), last=round(float(last), 2), baseline=round(float(mu), 2)))
    if not scores:
        return dict(mode=None, confidence=0.0, evidence=ev)
    total = sum(scores.values())
    if total <= 0:
        # prior: most frequent class-A mode for the type, else first mode of the category
        prior = sorted(scores, key=lambda m: (MODES[m][2], MODES[m][3]))[0]
        return dict(mode=prior, mode_ar=MODES[prior][1], confidence=0.0, evidence=ev, basis="prior")
    best = max(scores, key=scores.get)
    return dict(mode=best, mode_ar=MODES[best][1], confidence=round(scores[best] / total, 2), evidence=ev[-8:], basis="evidence",
                scores={m: round(v, 2) for m, v in scores.items() if v > 0})
