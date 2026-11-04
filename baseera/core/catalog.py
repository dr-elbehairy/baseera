"""Asset catalogue: the four urban-asset categories of the challenge (lighting, pumping stations, elevators, pavements),
their asset types, symptom vocabularies, failure modes (with class and warning lead L) and economics.

Everything category-specific in the platform reads from here; nothing else hard-codes a type. Lighting is the pilot
category (full physics in the simulator and field calibration); the other three are supported end to end (ingestion,
features, model, decision, ledger, apps) and ship with a simplified simulation until municipal exports arrive.
"""
from __future__ import annotations

# type → (category, label_ar, kind, design_life_y, planned_cost_sar, consequence_units, network_node)
TYPES: dict[str, tuple[str, str, str, float, float, float, bool]] = {
    # lighting
    "LED": ("lighting", "عمود إنارة LED", "pole", 12.0, 650, 1.0, False),
    "HAL": ("lighting", "عمود إنارة هالوجين/صوديوم", "pole", 8.0, 220, 1.0, False),
    "SOL": ("lighting", "عمود إنارة شمسي", "pole", 8.0, 900, 1.0, False),
    "CAB": ("lighting", "خزانة تغذية", "cabinet", 20.0, 6500, 40.0, True),
    # pumping stations (storm/drainage)
    "PMP": ("pumping", "مضخة تصريف", "pump", 15.0, 18000, 60.0, False),
    "PNL": ("pumping", "لوحة تحكم محطة ضخ", "panel", 15.0, 9000, 80.0, True),
    "VLV": ("pumping", "صمام/بوابة تصريف", "valve", 20.0, 4000, 25.0, False),
    # elevators & escalators on pedestrian bridges / public facilities
    "ELV": ("elevators", "مصعد معبر مشاة", "elevator", 20.0, 12000, 45.0, False),
    "ESC": ("elevators", "سلم متحرك", "escalator", 18.0, 15000, 35.0, False),
    "LFT": ("elevators", "رافعة ذوي الإعاقة", "lift", 15.0, 7000, 50.0, False),
    # pavements & pedestrian crossings
    "PAV": ("pavement", "مقطع رصيف", "segment", 25.0, 3500, 6.0, False),
    "RMP": ("pavement", "منحدر ذوي الإعاقة", "ramp", 20.0, 2500, 12.0, False),
    "CRS": ("pavement", "معبر مشاة", "crossing", 15.0, 5000, 15.0, False),
}

CATEGORIES: dict[str, dict] = {
    "lighting": dict(ar="الإنارة", status="pilot", status_ar="التجربة الحالية (فيزياء كاملة ومعايرة ميدانية)", code_prefix=("LP", "CB")),
    "pumping": dict(ar="محطات الضخ", status="ready", status_ar="جاهزة: استيعاب ونموذج وقرار وسجل؛ محاكاة مبسّطة حتى وصول بيانات الجهة", code_prefix=("PS",)),
    "elevators": dict(ar="المصاعد والسلالم المتحركة", status="ready", status_ar="جاهزة: استيعاب ونموذج وقرار وسجل؛ محاكاة مبسّطة حتى وصول بيانات الجهة", code_prefix=("EL",)),
    "pavement": dict(ar="الأرصفة والمعابر", status="ready", status_ar="جاهزة: استيعاب ونموذج وقرار وسجل؛ محاكاة مبسّطة حتى وصول بيانات الجهة", code_prefix=("PV",)),
}

# symptom code → (category or "*", label_ar)
SYMPTOMS: dict[str, tuple[str, str]] = {
    "flicker": ("lighting", "وميض"), "cycling": ("lighting", "إشعال وانطفاء متكرر"), "dim": ("lighting", "إضاءة خافتة"),
    "partial_trip": ("lighting", "انقطاع جزئي على الدائرة"), "intermittent": ("lighting", "انقطاع متقطع"),
    "vibration": ("pumping", "اهتزاز غير طبيعي"), "overheating": ("pumping", "ارتفاع حرارة المحرك"), "low_flow": ("pumping", "تدفق ضعيف"),
    "leak": ("pumping", "تسرب"), "tripping": ("pumping", "فصل متكرر للقاطع"), "blockage": ("pumping", "انسداد جزئي"),
    "door_slow": ("elevators", "بطء/تعثر الأبواب"), "jerk": ("elevators", "اهتزاز أو ارتجاج أثناء الحركة"), "leveling": ("elevators", "خطأ في التسوية عند التوقف"),
    "trip": ("elevators", "توقف مؤقت وإعادة تشغيل"), "alarm": ("elevators", "إنذار من لوحة التحكم"),
    "crack": ("pavement", "تشققات"), "settlement": ("pavement", "هبوط/تموّج"), "tile_loose": ("pavement", "بلاط مفكوك"),
    "pooling": ("pavement", "تجمع مياه"), "edge_damage": ("pavement", "تلف الحواف/البردورة"),
    "noise": ("*", "صوت/طنين غير طبيعي"), "heat": ("*", "حرارة غير طبيعية"), "rust": ("*", "صدأ/تآكل"), "tilt": ("*", "ميل/انحراف"), "other": ("*", "أخرى"),
}

# failure mode → (category, label_ar, class A/B/C, lead L days)
MODES: dict[str, tuple[str, str, str, int]] = {
    "led_driver": ("lighting", "تدهور مشغّل LED حراريًا", "A", 7), "lamp_eol": ("lighting", "نهاية عمر مصباح هالوجين/صوديوم", "A", 3),
    "cabinet": ("lighting", "عطل خزانة تغذية", "B", 14), "cable_joint": ("lighting", "عطل كابل/وصلة بعد الأمطار", "B", 7),
    "solar_battery": ("lighting", "تراجع بطارية عمود شمسي", "B", 7), "collision": ("lighting", "صدمة مركبة أو تخريب", "C", 2),
    "bearing_wear": ("pumping", "تآكل محامل المضخة", "A", 10), "seal_leak": ("pumping", "تسرب مانع التسرب", "A", 7),
    "motor_winding": ("pumping", "عطل ملفات المحرك", "B", 14), "panel_fault": ("pumping", "عطل لوحة التحكم", "B", 14),
    "intake_blockage": ("pumping", "انسداد المدخل", "B", 3),
    "door_mechanism": ("elevators", "عطل آلية الأبواب", "A", 7), "drive_motor": ("elevators", "عطل محرك الجر", "B", 14),
    "controller": ("elevators", "عطل وحدة التحكم", "B", 14), "rope_wear": ("elevators", "تآكل الحبال/السلاسل", "A", 21),
    "sensor": ("elevators", "عطل حساس/مفتاح حدي", "B", 3),
    "subsidence": ("pavement", "هبوط القاعدة", "A", 30), "tile_failure": ("pavement", "تكسر/تفكك البلاط", "A", 14),
    "drainage": ("pavement", "فشل التصريف", "B", 14), "impact": ("pavement", "ضرر خارجي (مركبات/أعمال)", "C", 2),
}

ASSET_TYPES = set(TYPES)
SYMPTOM_CODES = set(SYMPTOMS)
MODE_CODES = set(MODES)
TYPE_CODE = {t: i for i, t in enumerate(TYPES)}
CATEGORY_CODE = {c: i for i, c in enumerate(CATEGORIES)}
MODE_AR = {m: v[1] for m, v in MODES.items()}
MODE_CLASS = {m: v[2] for m, v in MODES.items()}
SYMPTOM_AR = {s: v[1] for s, v in SYMPTOMS.items()}


def category_of(asset_type: str) -> str:
    return TYPES[asset_type.upper()][0]


def kind_of(asset_type: str) -> str:
    return TYPES[asset_type.upper()][2]


def design_life(asset_type: str) -> float:
    return TYPES.get(asset_type, TYPES["LED"])[3]


def default_costs() -> dict[str, float]:
    return {t: float(v[4]) for t, v in TYPES.items()}


def consequence_units_of(asset_type: str) -> float:
    return TYPES.get(asset_type, TYPES["LED"])[5]


def is_node(asset_type: str) -> bool:
    return TYPES.get(asset_type, TYPES["LED"])[6]


def default_leads() -> dict[str, int]:
    return {m: v[3] for m, v in MODES.items()}


def symptoms_for(category: str | None) -> list[dict]:
    return [dict(code=c, ar=ar, category=cat) for c, (cat, ar) in SYMPTOMS.items() if category is None or cat in (category, "*")]


def describe() -> list[dict]:
    return [dict(key=c, ar=v["ar"], status=v["status"], status_ar=v["status_ar"],
                 types=[dict(code=t, ar=tv[1], kind=tv[2], design_life_y=tv[3], cost_planned=tv[4]) for t, tv in TYPES.items() if tv[0] == c],
                 modes=[dict(code=m, ar=mv[1], cls=mv[2], L=mv[3]) for m, mv in MODES.items() if mv[0] == c],
                 symptoms=[s for s in symptoms_for(c) if s["category"] == c]) for c, v in CATEGORIES.items()]
