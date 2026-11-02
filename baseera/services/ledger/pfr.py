"""PFR@L — the official metric, computed by one function for the backtest and for live operation.

lead(failure)        = failed_on − week_start of the earliest list (within a 45-day window before the failure) that
                       contained the asset; −1 if never listed.
had_warning_at_L     = lead ≥ L   (L per failure mode, default when the mode is unknown)
PFR@L(month)         = mean(had_warning_at_L) over the confirmed failures of the month
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.models import FailureEvent, ListItem, WeeklyList

WINDOW_DAYS = 45


def leads_for_failures(fails: list[tuple[str, date]], lists: dict[date, set[str]]) -> list[int]:
    """fails: [(asset_id, failed_on)]; lists: {week_start: {asset_id}} → lead days per failure (−1 = no warning)."""
    weeks = sorted(lists)
    out = []
    for asset_id, failed_on in fails:
        lead = -1
        for w in weeks:
            if w > failed_on or (failed_on - w).days > WINDOW_DAYS:
                continue
            if asset_id in lists[w]:
                lead = (failed_on - w).days
                break
        out.append(lead)
    return out


def lists_from_db(db: Session, run_tag: str, lo: date, hi: date, statuses: tuple[str, ...] | None = None) -> dict[date, set[str]]:
    q = (db.query(WeeklyList.week_start, ListItem.asset_id, ListItem.status).join(ListItem, ListItem.list_id == WeeklyList.list_id)
         .filter(WeeklyList.run_tag == run_tag, WeeklyList.week_start >= lo - timedelta(days=WINDOW_DAYS), WeeklyList.week_start <= hi))
    out: dict[date, set[str]] = {}
    for w, a, st in q.all():
        if statuses and st not in statuses:
            continue
        out.setdefault(w, set()).add(a)
    return out


def L_for(mode: str | None) -> int:
    s = get_settings()
    return int(s.lead_by_mode.get(mode or "", s.lead_default))


def annotate_leads(db: Session, run_tag: str = "live", lo: date | None = None, hi: date | None = None) -> int:
    """Fill lead_days / had_warning_at_L on failure events of the run_tag. In live mode only approved/done items count
    as a warning (a proposed list the supervisor never looked at is not a warning); the backtest counts proposed lists."""
    q = db.query(FailureEvent).filter(FailureEvent.run_tag == run_tag)
    if lo: q = q.filter(FailureEvent.failed_on >= lo)
    if hi: q = q.filter(FailureEvent.failed_on <= hi)
    fails = q.all()
    if not fails:
        return 0
    lo_d, hi_d = min(f.failed_on for f in fails), max(f.failed_on for f in fails)
    statuses = None if run_tag == "backtest" else ("approved", "done", "overridden")
    lists = lists_from_db(db, run_tag, lo_d, hi_d, statuses)
    leads = leads_for_failures([(f.asset_id, f.failed_on) for f in fails], lists)
    for f, ld in zip(fails, leads):
        f.lead_days = None if ld < 0 else ld
        f.had_warning_at_L = (ld >= L_for(f.failure_mode))
    db.commit()
    return len(fails)


def pfr_at_L(fails: list[FailureEvent], L: int | None = None) -> float | None:
    """L=None → each failure's own L (by mode)."""
    if not fails:
        return None
    hits = 0
    for f in fails:
        ld = -1 if f.lead_days is None else f.lead_days
        hits += int(ld >= (L if L is not None else L_for(f.failure_mode)))
    return round(hits / len(fails), 4)
