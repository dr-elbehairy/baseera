"""Human-readable description of every ingestion pipeline: fields, Arabic labels, examples, templates. Drives the data panel."""
from __future__ import annotations

import io

import pandas as pd

from .pipelines.core import ORDER, PIPELINES

# pipeline → ordered fields: (name, label_ar, required, example, help_ar)
FIELDS: dict[str, list[tuple[str, str, bool, str, str]]] = {
    "cabinets": [("cabinet_code", "رمز الخزانة", True, "CB-01", "يُطبَّع تلقائيًا: cb-1 → CB-01"), ("lon", "خط الطول", True, "46.7012", "داخل المملكة"),
                 ("lat", "خط العرض", True, "24.8031", "داخل المملكة"), ("install_date", "تاريخ التركيب", False, "2019-03-15", "YYYY-MM-DD")],
    "assets": [("asset_code", "رمز الأصل", True, "LP-10001", "يُطبَّع تلقائيًا: lp10001 → LP-10001"), ("asset_type", "نوع الأصل", True, "LED", "LED | HAL | SOL | CAB"),
               ("kind", "الصنف", False, "pole", "pole | cabinet"), ("street_class", "تصنيف الشارع", False, "main", "main | sec"),
               ("criticality", "الحرج", False, "school", "none | mosque | school | crossing | hospital"), ("lon", "خط الطول", True, "46.7021", ""),
               ("lat", "خط العرض", True, "24.8044", ""), ("install_date", "تاريخ التركيب", False, "2021-06-01", "YYYY-MM-DD"),
               ("cabinet_code", "رمز الخزانة", False, "CB-01", "يجب أن تكون الخزانة محمّلة أولًا"), ("owner_entity", "الجهة المالكة", False, "municipality", "")],
    "weather": [("day", "اليوم", True, "2026-06-01", "YYYY-MM-DD"), ("tmax_c", "الحرارة العظمى (م°)", True, "44.5", "-5 إلى 55"),
                ("rain_mm", "الأمطار (مم)", False, "0", ""), ("dust", "غبار", False, "0", "0 أو 1"), ("sector", "القطاع", False, "default", "")],
    "reports": [("external_ref", "مرجع البلاغ في 940/نظام الجهة", False, "R-2026-000123", "يمنع التكرار عند إعادة الرفع"),
                ("reported_at", "وقت البلاغ", True, "2026-06-01 21:40", "تاريخ ووقت"), ("report_type", "نوع البلاغ", False, "dark", "dark | flicker | damage | other"),
                ("channel", "القناة", False, "citizen", "citizen | patrol | contractor"), ("asset_code", "رمز الأصل", False, "LP-10001", "أو الإحداثيات أدناه"),
                ("lon", "خط الطول", False, "46.7021", "عند غياب الرمز: أقرب أصل ضمن نصف قطر المطابقة"), ("lat", "خط العرض", False, "24.8044", ""),
                ("closed_at", "وقت الإغلاق", False, "2026-06-03 10:00", ""), ("reporter", "هوية المبلّغ", False, "0555xxxxxx", "لا تُخزَّن؛ تُحوَّل إلى بصمة مملّحة (PDPL)")],
    "work_orders": [("external_ref", "رقم أمر العمل", False, "WO-2026-0456", "يمنع التكرار"), ("asset_code", "رمز الأصل", True, "LP-10001", ""),
                    ("kind", "النوع", True, "emergency", "emergency | planned"), ("opened_at", "وقت الفتح", True, "2026-06-02 08:00", ""),
                    ("closed_at", "وقت الإغلاق", False, "2026-06-02 15:30", ""), ("fault_code", "رمز العطل", False, "led_driver", "lamp_eol | led_driver | cabinet | cable_joint | solar_battery | collision"),
                    ("cost_sar", "التكلفة (ر.س)", False, "1300", ""), ("report_ref", "مرجع البلاغ المرتبط", False, "R-2026-000123", "")],
    "observations": [("asset_code", "رمز الأصل", True, "LP-10001", ""), ("observed_at", "وقت الرصد", True, "2026-06-01 22:10", ""),
                     ("symptom_code", "العلامة", True, "flicker", "flicker | cycling | dim | partial_trip | intermittent | noise | heat | rust | tilt | other"),
                     ("severity", "الشدة", False, "2", "1..3"), ("source", "المصدر", False, "technician_qr", "technician_qr | patrol | citizen"),
                     ("observer_id", "معرّف الراصد", False, "T-07", ""), ("note", "ملاحظة", False, "", ""), ("client_ref", "مرجع العميل", False, "", "يمنع التكرار")],
}
LABEL_AR = {"cabinets": "الخزانات", "assets": "الأصول (الأعمدة والخزانات)", "weather": "الطقس اليومي", "reports": "البلاغات (940 / الجهة)",
            "work_orders": "أوامر العمل", "observations": "العلامات المرصودة"}
HELP_AR = {"cabinets": "تُحمَّل أولًا لأن الأصول تُربط بها.", "assets": "سجل الأصول من نظام الجهة أو المقاول؛ الرفع المتكرر يحدّث لا يكرّر.",
           "weather": "من الهيئة العامة للأرصاد أو أي مصدر يومي؛ قطاع واحد يكفي في البداية.",
           "reports": "تصدير بلاغات الإنارة؛ البلاغ بلا رمز أصل يُطابَق مكانيًا.", "work_orders": "أوامر الطوارئ هي مصدر أحداث العطل في السجل.",
           "observations": "عادةً تأتي من تطبيق الفني؛ هذا المسار للاستيراد الجماعي من جولات سابقة."}


def describe() -> list[dict]:
    return [dict(name=n, label=LABEL_AR[n], help=HELP_AR[n], order=i + 1,
                 fields=[dict(name=f, label=l, required=r, example=e, help=h) for f, l, r, e, h in FIELDS[n]]) for i, n in enumerate(ORDER)]


def template_csv(name: str) -> str:
    cols = [f for f, *_ in FIELDS[name]]; ex = {f: e for f, _, _, e, _ in FIELDS[name]}
    df = pd.DataFrame([ex], columns=cols)
    buf = io.StringIO(); df.to_csv(buf, index=False); return buf.getvalue()


def read_table(filename: str, content: bytes) -> pd.DataFrame:
    """CSV or Excel → DataFrame of strings (the pipelines coerce types)."""
    low = filename.lower()
    if low.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(io.BytesIO(content), dtype=str)
    else:
        txt = content.decode("utf-8-sig", errors="replace")
        df = pd.read_csv(io.StringIO(txt), dtype=str, keep_default_na=False, sep=None, engine="python")
    df.columns = [str(c).strip() for c in df.columns]
    return df.fillna("")


def preview(db, name: str, df: pd.DataFrame, limit: int = 20) -> dict:
    """Dry run: schema validation + asset/cabinet matching on every row, nothing written."""
    from collections import Counter
    from pydantic import ValidationError
    from .base import RowError
    pipe = PIPELINES[name](db)
    expected = [f for f, *_ in FIELDS[name]]; required = [f for f, _, r, *_ in FIELDS[name] if r]
    missing = [c for c in required if c not in df.columns]; unknown = [c for c in df.columns if c not in expected]
    reasons = Counter(); bad = []
    sp = db.begin_nested()
    try:
        for i, raw in enumerate(df.to_dict("records")):
            try:
                row = pipe.schema(**raw); pipe.handle(row, raw); db.flush()
            except (ValidationError, RowError, ValueError) as e:
                msg = _short(e); reasons[msg] += 1
                if len(bad) < 50: bad.append(dict(row=i + 2, reason=msg))
            except Exception as e:  # integrity etc.
                msg = str(e)[:160]; reasons[msg] += 1
                if len(bad) < 50: bad.append(dict(row=i + 2, reason=msg))
    finally:
        sp.rollback(); db.rollback()
    n = len(df); n_bad = sum(reasons.values())
    return dict(pipeline=name, rows=n, ok=n - n_bad, quarantined=n_bad, missing_required=missing, unknown_columns=unknown, columns=list(df.columns),
                sample=df.head(limit).to_dict("records"), reasons=[dict(reason=r, n=c) for r, c in reasons.most_common(12)], bad_rows=bad)


def _short(e) -> str:
    from pydantic import ValidationError
    if isinstance(e, ValidationError):
        er = e.errors()[0]; loc = ".".join(str(x) for x in er.get("loc", ())); msg = er.get("msg", "")
        return f"{loc}: {msg}"[:160]
    return str(e)[:160]
