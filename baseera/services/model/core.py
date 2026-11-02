"""Model service: train (temporal split + isotonic calibration + promotion gates), score, explain, registry.

train()  → ModelVersion row + joblib artifact; promoted only if every gate passes (or force=True).
score()  → Prediction rows for one week start, using the promoted version; risk/priority via the decision engine.
explain()→ group-level contributions (symptoms / network / weather / history / asset) by reference substitution —
           dependency-free and stable, the same method as the PoC.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.models import Asset, ModelVersion, Prediction
from ..decision.rank import GROUP_AR, score_frame
from ..features.build import FEATURES, frame

GROUPS = {"symptoms": ["symptoms_14d", "symptoms_30d", "max_sev_30d"], "network": ["circuit_partial_trips_14d", "cabinet_fails_365d"],
          "weather": ["tmax_14d", "tmax_fcst_7d", "rain_7d", "rain_30d", "dust_30d", "heat_load_120d"],
          "history": ["days_since_last_fail", "fails_365d"], "asset": ["age_y", "type_code", "main_road", "is_cabinet", "crit_w", "cabinet_age_y"]}


@dataclass
class Bundle:
    clf: HistGradientBoostingClassifier
    iso: IsotonicRegression
    features: list[str]
    reference: np.ndarray

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.iso.predict(self.clf.predict_proba(X)[:, 1])


def _asset_frame(db: Session) -> pd.DataFrame:
    return pd.DataFrame([dict(asset_id=a.asset_id, asset_code=a.asset_code, asset_type=a.asset_type, kind=a.kind, street_class=a.street_class,
                              criticality=a.criticality) for a in db.query(Asset).filter(Asset.active.is_(True)).all()])


def load_bundle(mv: ModelVersion) -> Bundle:
    return joblib.load(mv.artifact_path)


def promoted(db: Session) -> ModelVersion | None:
    return db.query(ModelVersion).filter(ModelVersion.promoted.is_(True)).order_by(ModelVersion.created_at.desc()).first()


def train(db: Session, as_of: date, calibration_days: int = 70, name: str = "hgb-isotonic", force: bool = False,
          approved_by: str | None = None) -> ModelVersion:
    """Temporal protocol: train on labelled weeks before (as_of − calibration_days), calibrate + validate on the last
    calibration_days of labelled weeks. Gates are evaluated on the calibration/validation slice."""
    s = get_settings()
    df = frame(db, labelled_only=True)
    if df.empty:
        raise RuntimeError("no labelled feature rows; run build-features with an as_of after the horizon")
    df = df[df.week_start + timedelta(days=s.horizon_days) <= as_of]
    cut = as_of - timedelta(days=calibration_days)
    tr, va = df[df.week_start < cut], df[df.week_start >= cut]
    if len(va) == 0 or va.label.sum() == 0:
        raise RuntimeError("validation slice has no positive labels; widen calibration_days or as_of")
    X_tr, y_tr = tr[FEATURES].values.astype(float), tr.label.values.astype(int)
    X_va, y_va = va[FEATURES].values.astype(float), va.label.values.astype(int)
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                                         random_state=0).fit(X_tr, y_tr)
    raw_va = clf.predict_proba(X_va)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip").fit(raw_va, y_va)
    p_va = iso.predict(raw_va)
    auc = float(roc_auc_score(y_va, p_va)); brier = float(brier_score_loss(y_va, p_va))
    imp, group_imp = _group_permutation_importance(clf, iso, X_va, y_va, auc)
    tot = sum(group_imp.values()); share = (max(group_imp.values()) / tot) if tot > 0 else 0.0
    top_feat = max(group_imp, key=group_imp.get)
    # PFR gate on validation: a capacity-limited weekly list from the model vs. the age rule
    pfr_model, pfr_age = _validation_pfr(db, va.assign(p_fail=p_va), s.lead_default)
    prev = promoted(db)
    gates = {"auc": {"value": auc, "min": s.gate_min_auc, "pass": auc >= s.gate_min_auc},
             "brier_not_worse": {"value": brier, "prev": (prev.metrics.get("brier") if prev else None),
                                 "pass": (prev is None) or brier <= prev.metrics.get("brier", 1.0) + 0.002},
             "pfr_gain_over_age": {"value": pfr_model - pfr_age, "min": s.gate_min_pfr_gain_over_age, "pass": (pfr_model - pfr_age) >= s.gate_min_pfr_gain_over_age},
             "single_group_share": {"value": share, "max": s.gate_max_single_group_share, "group": top_feat, "groups": group_imp,
                                    "pass": share <= s.gate_max_single_group_share}}
    ok = all(g["pass"] for g in gates.values())
    os.makedirs(s.model_dir, exist_ok=True)
    mv = ModelVersion(name=name, trained_from=tr.week_start.min() if len(tr) else cut, trained_to=va.week_start.max(), features=FEATURES,
                      metrics={"auc": auc, "brier": brier, "pfr_at_L_validation": pfr_model, "pfr_age_rule_validation": pfr_age,
                               "n_train": int(len(tr)), "n_validation": int(len(va)), "positives_validation": int(y_va.sum()),
                               "base_rate_validation": float(y_va.mean()), "importance": {f: float(v) for f, v in zip(FEATURES, imp)}},
                      gates=gates, promoted=bool(ok or force), approved_by=approved_by, artifact_path="")
    db.add(mv); db.flush()
    mv.artifact_path = os.path.join(s.model_dir, f"{mv.model_version_id}.joblib")
    joblib.dump(Bundle(clf=clf, iso=iso, features=FEATURES, reference=np.median(X_tr, axis=0)), mv.artifact_path)
    if mv.promoted and prev is not None and prev.model_version_id != mv.model_version_id:
        prev.promoted = False
    db.commit()
    return mv


def _group_permutation_importance(clf, iso, X: np.ndarray, y: np.ndarray, auc_full: float, repeats: int = 3) -> tuple[np.ndarray, dict]:
    """Permutation importance per feature and per feature *group* (all columns of a group permuted together).
    Group level is what the leakage gate reads: correlated features inside a group would otherwise hide each other."""
    rng = np.random.default_rng(0)
    def auc_of(Xp): return roc_auc_score(y, iso.predict(clf.predict_proba(Xp)[:, 1]))
    per_feat = np.zeros(len(FEATURES))
    for j in range(len(FEATURES)):
        d = []
        for _ in range(repeats):
            Xp = X.copy(); Xp[:, j] = rng.permutation(Xp[:, j]); d.append(auc_full - auc_of(Xp))
        per_feat[j] = max(0.0, float(np.mean(d)))
    groups = {}
    for g, cols in GROUPS.items():
        idx = [FEATURES.index(c) for c in cols]; d = []
        for _ in range(repeats):
            Xp = X.copy()
            for j in idx: Xp[:, j] = rng.permutation(Xp[:, j])
            d.append(auc_full - auc_of(Xp))
        groups[g] = max(0.0, float(np.mean(d)))
    return per_feat, groups


def _validation_pfr(db: Session, va: pd.DataFrame, L: int) -> tuple[float, float]:
    """PFR@L on the validation weeks for the model list vs the age-rule list, with the same crew capacity."""
    from ..ledger.pfr import leads_for_failures
    from ...core.models import FailureEvent
    s = get_settings()
    A = _asset_frame(db)
    weeks = sorted(va.week_start.unique())
    model_lists, age_lists = {}, {}
    age_order = va.drop_duplicates("asset_id").sort_values("age_y", ascending=False).asset_id.tolist()
    ptr = 0
    for w in weeks:
        g = va[va.week_start == w].merge(A, on="asset_id")
        sc = score_frame(g)
        top = sc[sc.p_fail >= s.alert_probability].sort_values("priority", ascending=False).head(s.crew_jobs_per_week)
        model_lists[w] = set(top.asset_id)
        age_lists[w] = set(age_order[(ptr % len(age_order)):(ptr % len(age_order)) + s.crew_jobs_per_week]); ptr += s.crew_jobs_per_week
    lo, hi = weeks[0], weeks[-1] + timedelta(days=s.horizon_days)
    fails = [(f.asset_id, f.failed_on) for f in db.query(FailureEvent).filter(FailureEvent.failed_on >= lo, FailureEvent.failed_on < hi).all()]
    if not fails:
        return 0.0, 0.0
    lm = leads_for_failures(fails, model_lists); la = leads_for_failures(fails, age_lists)
    return float(np.mean([l >= L for l in lm])), float(np.mean([l >= L for l in la]))


def explain_row(b: Bundle, x: np.ndarray) -> dict:
    base = float(b.predict(x[None])[0]); out = {}
    for g, cols in GROUPS.items():
        idx = [b.features.index(c) for c in cols if c in b.features]
        xx = x.copy(); xx[idx] = b.reference[idx]
        out[g] = round(base - float(b.predict(xx[None])[0]), 4)
    return out


def score(db: Session, week_start: date, mv: ModelVersion | None = None, run_tag: str = "live", explain_top: int = 50) -> pd.DataFrame:
    mv = mv or promoted(db)
    if mv is None:
        raise RuntimeError("no promoted model; run train first")
    b = load_bundle(mv)
    df = frame(db, weeks=[week_start])
    if df.empty:
        raise RuntimeError(f"no feature rows for week {week_start}; run build-features")
    A = _asset_frame(db)
    df = df.merge(A, on="asset_id")
    X = df[b.features].values.astype(float)
    df["p_fail"] = b.predict(X)
    sc = score_frame(df)
    order = np.argsort(-sc.priority.values)[:explain_top]
    expl = {sc.asset_id.iloc[i]: explain_row(b, X[i]) for i in order}
    db.execute(delete(Prediction).where(Prediction.week_start == week_start, Prediction.run_tag == run_tag, Prediction.model_version_id == mv.model_version_id))
    db.bulk_insert_mappings(Prediction, [dict(asset_id=r.asset_id, week_start=week_start, model_version_id=mv.model_version_id, p_fail=float(r.p_fail),
                                              risk_sar=float(r.risk_sar), priority=float(r.priority), explanation=expl.get(r.asset_id), run_tag=run_tag)
                                         for r in sc.itertuples()])
    db.commit()
    sc["explanation"] = sc.asset_id.map(expl)
    sc["model_version_id"] = mv.model_version_id
    return sc
