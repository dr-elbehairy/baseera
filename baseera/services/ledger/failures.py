"""Derive confirmed failures from what the municipality already records: emergency work orders (and, as a fallback,
'dark' reports that never got a work order). failed_on = the earliest signal date. Runs before feature building."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from ...core.models import FailureEvent, Report, WorkOrder


def derive_failures(db: Session, run_tag: str = "live") -> int:
    existing = {f.wo_id for f in db.query(FailureEvent.wo_id).filter(FailureEvent.run_tag == run_tag, FailureEvent.wo_id.isnot(None))}
    existing_reports = {f.report_id for f in db.query(FailureEvent.report_id).filter(FailureEvent.run_tag == run_tag, FailureEvent.report_id.isnot(None))}
    n = 0
    reports = {r.report_id: r for r in db.query(Report).all()}
    for wo in db.query(WorkOrder).filter(WorkOrder.kind == "emergency").all():
        if wo.wo_id in existing:
            continue
        rep = reports.get(wo.report_id) if wo.report_id else None
        failed_on = min(wo.opened_at.date(), rep.reported_at.date()) if rep else wo.opened_at.date()
        closed = wo.closed_at or (rep.closed_at if rep else None)
        days_dark = max(0, (closed.date() - failed_on).days) if closed else None
        db.add(FailureEvent(asset_id=wo.asset_id, failed_on=failed_on, failure_mode=wo.fault_code, wo_id=wo.wo_id,
                            report_id=rep.report_id if rep else None, days_dark=days_dark, run_tag=run_tag))
        if rep:
            existing_reports.add(rep.report_id)
        n += 1
    # dark reports without any work order within 14 days → still a failure (unserved)
    wo_by_asset: dict[str, list] = {}
    for wo in db.query(WorkOrder).all():
        wo_by_asset.setdefault(wo.asset_id, []).append(wo.opened_at)
    for rep in db.query(Report).filter(Report.report_type == "dark", Report.asset_id.isnot(None)).all():
        if rep.report_id in existing_reports:
            continue
        served = any(abs((t - rep.reported_at).days) <= 14 for t in wo_by_asset.get(rep.asset_id, []))
        if served:
            continue
        days_dark = max(0, (rep.closed_at.date() - rep.reported_at.date()).days) if rep.closed_at else None
        db.add(FailureEvent(asset_id=rep.asset_id, failed_on=rep.reported_at.date(), failure_mode=None, report_id=rep.report_id,
                            days_dark=days_dark, run_tag=run_tag))
        existing_reports.add(rep.report_id)
        n += 1
    db.commit()
    return n
