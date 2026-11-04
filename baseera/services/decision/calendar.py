"""Saudi operating constraints applied to every scheduled job: summer heat ban for outdoor work, Ramadan hours,
Hajj freeze window (freeze non-urgent work, finish preventive work on elevators/facilities before), flood season readiness."""
from __future__ import annotations

from datetime import date

from ...core.config import get_settings

OUTDOOR = {"lighting", "pavement"}


def _in(win, d: date) -> bool:
    try:
        a, b = (date.fromisoformat(x) for x in win); return a <= d <= b
    except Exception:
        return False


def constraints_for(week_start: date, category: str, tier: str) -> dict:
    s = get_settings(); notes = []; window = "8:00–16:00"
    if week_start.month in s.heat_ban_months and category in OUTDOOR:
        window = "6:00–11:00 صباحًا أو 16:00–19:00 مساءً"; notes.append(f"حظر العمل تحت الشمس {s.heat_ban_hours} (قرار وزارة الموارد البشرية)")
    elif category in ("pumping",):
        window = "6:00–9:00 صباحًا (خارج ذروة التصريف)"
    elif category == "elevators":
        window = "6:00–9:00 صباحًا (قبل ذروة الاستخدام)"
    if _in(s.ramadan_window, week_start):
        window = "بعد الإفطار 21:00–01:00"; notes.append("ساعات عمل رمضان")
    if _in(s.hajj_freeze_window, week_start):
        if tier in ("planned", "monitor"):
            notes.append("نافذة تجميد الأعمال (الحج): يؤجَّل غير العاجل")
        else:
            notes.append("نافذة الحج: يُنفَّذ العاجل فقط بتصريح")
    if week_start.month in s.flood_season_months and category == "pumping":
        notes.append(f"موسم الأمطار: أولوية جاهزية محطات الضخ (×{s.flood_readiness_boost})")
    return dict(safe_window=window, notes=notes, frozen=(_in(s.hajj_freeze_window, week_start) and tier in ("planned", "monitor")))


def week_banner(week_start: date) -> list[str]:
    s = get_settings(); out = []
    if week_start.month in s.heat_ban_months: out.append(f"حظر العمل الخارجي {s.heat_ban_hours}: المهام الخارجية صباحًا ومساءً")
    if _in(s.ramadan_window, week_start): out.append("أسبوع رمضاني: ساعات عمل ليلية")
    if _in(s.hajj_freeze_window, week_start): out.append("نافذة تجميد الأعمال في موسم الحج: العاجل فقط")
    if week_start.month in s.flood_season_months: out.append("موسم الأمطار: جاهزية محطات الضخ مقدَّمة")
    return out
