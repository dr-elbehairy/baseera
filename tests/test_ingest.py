"""Layer 1 — validation, matching, quarantine, idempotency, PDPL hashing."""
from __future__ import annotations

from baseera.core.db import session_scope
from baseera.core.models import Asset, Observation, Quarantine, Report
from baseera.services.ingest.base import normalise_code, reporter_hash
from baseera.services.ingest.pipelines.core import ReportPipeline, AssetPipeline


def test_code_normalisation():
    assert normalise_code(" lp-10001 ") == "LP-10001"
    assert normalise_code("LP10001") == "LP-10001"
    assert normalise_code("lp_010001") == "LP-10001"
    assert normalise_code("cb-3") == "CB-03"
    assert normalise_code(None) == ""


def test_reporter_identity_is_hashed_not_stored():
    h = reporter_hash("0500000001")
    assert h and len(h) == 64 and "0500000001" not in h
    assert reporter_hash("") is None


def test_simulated_seed_went_through_pipelines(db_ready):
    runs = db_ready["runs"]
    assert runs["assets"]["quarantined"] == 0 and runs["assets"]["ok"] == 164 + 270  # 160 poles + 4 cabinets + 40 pumping + 30 elevators + 200 pavement
    assert runs["reports"]["ok"] > 0
    # ~30% of simulated reports carry no code and must be matched spatially (≤ 25 m)
    with session_scope() as db:
        spatial = db.query(Report).filter_by(match_method="spatial").count()
        total = db.query(Report).count()
        assert 0.15 < spatial / total < 0.45
        assert db.query(Report).filter(Report.reporter_hash.is_(None)).count() == 0


def test_bad_rows_are_quarantined_with_reason(db_ready):
    with session_scope() as db:
        before = db.query(Quarantine).count()
        run = ReportPipeline(db).run([
            dict(external_ref="T-1", reported_at="2026-01-05 10:00", report_type="dark", asset_code="ZZ-999"),          # unknown code, no coords
            dict(external_ref="T-2", reported_at="2026-01-05 10:00", report_type="dark", lon=46.9, lat=24.9),           # far from any asset
            dict(external_ref="T-3", reported_at="not a date", report_type="dark", asset_code="LP-10001"),              # bad datetime
            dict(external_ref="T-4", reported_at="2026-01-05 10:00", report_type="spaceship", asset_code="LP-10001"),  # bad enum
        ])
        assert run.n_in == 4 and run.n_ok == 0 and run.n_quarantined == 4
        reasons = [q.reason for q in db.query(Quarantine).order_by(Quarantine.row_id.desc()).limit(4)]
        assert any("unknown asset code" in r for r in reasons) and any("no asset within" in r for r in reasons)
        assert db.query(Quarantine).count() == before + 4
        assert db.query(Report).filter(Report.external_ref.in_(["T-1", "T-2", "T-3", "T-4"])).count() == 0


def test_ingest_is_idempotent_and_flicker_becomes_observation(db_ready):
    with session_scope() as db:
        a = db.query(Asset).filter_by(asset_code="LP-10001").first()
        n_obs = db.query(Observation).filter_by(asset_id=a.asset_id, source="citizen").count()
        row = dict(external_ref="T-FL-1", reported_at="2026-01-06 21:00", report_type="flicker", asset_code="LP-10001", reporter="0555")
        r1 = ReportPipeline(db).run([row]); r2 = ReportPipeline(db).run([row])
        assert r1.n_ok == 1 and r2.n_ok == 1
        assert db.query(Report).filter_by(external_ref="T-FL-1").count() == 1
        assert db.query(Observation).filter_by(asset_id=a.asset_id, source="citizen").count() == n_obs + 1


def test_asset_outside_kingdom_rejected(db_ready):
    with session_scope() as db:
        run = AssetPipeline(db).run([dict(asset_code="LP-99999", asset_type="LED", lon=2.3, lat=48.8)])
        assert run.n_quarantined == 1
