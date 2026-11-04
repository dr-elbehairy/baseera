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
                 symptoms=[s for s in symptoms_for(c) if s["category"] == c],
                 channels=[dict(code=ch, ar=cv[1], unit=cv[2], source=cv[4]) for ch, cv in CHANNELS.items() if cv[0] == c]) for c, v in CATEGORIES.items()]


# ----------------------------------------------------------------------------- v0.4: sensing, diagnosis, parts, consequences
# telemetry channel → (category, label_ar, unit, direction of degradation: +1 rising / -1 falling, source)
CHANNELS: dict[str, tuple[str, str, str, int, str]] = {
    "vibration_mms": ("pumping", "اهتزاز المضخة", "مم/ث", +1, "iot_pulse"), "motor_temp_c": ("pumping", "حرارة محرك المضخة", "°م", +1, "iot_pulse"),
    "flow_ratio": ("pumping", "نسبة التدفق إلى التصميم", "%", -1, "scada"), "insulation_mohm": ("pumping", "مقاومة العزل", "MΩ", -1, "scada"),
    "drive_current_a": ("elevators", "تيار محرك الجر", "أمبير", +1, "iot_pulse"), "door_cycle_s": ("elevators", "زمن دورة الأبواب", "ث", +1, "controller"),
    "trips_per_day": ("elevators", "توقفات لوحة التحكم يوميًا", "عدد", +1, "controller"), "leveling_mm": ("elevators", "خطأ التسوية", "مم", +1, "controller"),
    "crack_mm": ("pavement", "عرض التشقق (كاميرا المركبة)", "مم", +1, "vehicle_cam"), "settlement_mm": ("pavement", "الهبوط (InSAR/المركبة)", "مم", +1, "vehicle_cam"),
    "driver_current_a": ("lighting", "تيار مشغّل الإنارة", "أمبير", -1, "smart_meter"), "lamp_hours": ("lighting", "ساعات تشغيل المصباح", "ساعة", +1, "cms"),
}
# failure mode → (parts_ar, checklist_ar, hours)
PARTS: dict[str, tuple[str, str, float]] = {
    "led_driver": ("مشغّل LED بديل", "قياس تيار المشغّل، فحص الحرارة، استبدال المشغّل، اختبار التشغيل", 1.0), "lamp_eol": ("مصباح هالوجين/صوديوم", "استبدال المصباح، فحص القاعدة", 0.5),
    "cabinet": ("قاطع + مرحّل تحكم", "فحص القواطع والتوصيلات، قياس الأحمال على الدوائر، تنظيف الخزانة", 3.0), "cable_joint": ("وصلة كابل + مواد عزل", "كشف الوصلة، اختبار العزل بعد التجفيف، إعادة العزل", 2.5),
    "solar_battery": ("بطارية + فحص منظم الشحن", "قياس جهد البطارية والشحن، تنظيف اللوح، استبدال البطارية", 1.5), "collision": ("عمود/قاعدة بحسب الضرر", "تأمين الموقع، تقييم الضرر، إصلاح أو استبدال", 4.0),
    "bearing_wear": ("محمل كروي ×2 + مانع تسرب", "قياس الاهتزاز قبل/بعد، استبدال المحامل، محاذاة العمود، اختبار التشغيل", 6.0), "seal_leak": ("مانع تسرب ميكانيكي", "تفريغ، استبدال المانع، اختبار ضغط", 4.0),
    "motor_winding": ("إعادة لف أو محرك بديل", "قياس مقاومة العزل، فحص الملفات، استبدال المحرك", 8.0), "panel_fault": ("قاطع + كونتاكتور + مرحّل", "فحص اللوحة حراريًا، استبدال المكوّن، اختبار التسلسل", 3.0),
    "intake_blockage": ("شبكة مدخل", "تنظيف المدخل، فحص الصمام العكسي، اختبار التدفق", 2.0),
    "door_mechanism": ("مشغّل باب + حساس أمان", "ضبط المسار، استبدال المشغّل، معايرة الحساس", 3.0), "drive_motor": ("محرك جر أو فرامل", "قياس التيار والحرارة، فحص الفرامل، استبدال", 8.0),
    "controller": ("لوحة تحكم / مرحّل", "تحميل سجل الأعطال، استبدال المكوّن، اختبار الرحلات", 4.0), "rope_wear": ("حبال/سلاسل + بكرات", "قياس قطر الحبل، استبدال الحبال، شد ومعايرة", 10.0),
    "sensor": ("حساس حدي / مفتاح", "اختبار الإشارات، استبدال الحساس، معايرة التسوية", 1.5),
    "subsidence": ("رمل مضغوط + بلاط", "إزالة البلاط، إعادة الردم والدك، إعادة التبليط", 12.0), "tile_failure": ("بلاط + مونة", "إزالة التالف، تسوية، تبليط", 6.0),
    "drainage": ("شبكة مصرف + تنظيف", "تنظيف المصرف، إعادة تسوية الميل، اختبار بالماء", 4.0), "impact": ("بردورة/بلاط", "تقييم الضرر، إصلاح", 3.0),
}
# evidence weights: symptom or channel-anomaly → mode (diagnosis)
EVIDENCE: dict[str, dict[str, float]] = {
    "flicker": {"led_driver": 1.0}, "cycling": {"lamp_eol": 1.0}, "dim": {"solar_battery": 0.8, "lamp_eol": 0.3}, "partial_trip": {"cabinet": 1.0}, "intermittent": {"cable_joint": 1.0},
    "vibration": {"bearing_wear": 1.0}, "overheating": {"motor_winding": 0.9, "bearing_wear": 0.3}, "low_flow": {"intake_blockage": 1.0}, "leak": {"seal_leak": 1.0},
    "tripping": {"panel_fault": 0.8, "motor_winding": 0.4}, "blockage": {"intake_blockage": 1.0},
    "door_slow": {"door_mechanism": 1.0}, "jerk": {"drive_motor": 0.7, "rope_wear": 0.5}, "leveling": {"rope_wear": 0.6, "sensor": 0.6}, "trip": {"controller": 0.7, "sensor": 0.5}, "alarm": {"controller": 1.0},
    "crack": {"tile_failure": 0.7, "subsidence": 0.5}, "settlement": {"subsidence": 1.0}, "tile_loose": {"tile_failure": 1.0}, "pooling": {"drainage": 1.0}, "edge_damage": {"impact": 1.0},
    "vibration_mms": {"bearing_wear": 1.0}, "motor_temp_c": {"motor_winding": 1.0}, "flow_ratio": {"intake_blockage": 1.0}, "insulation_mohm": {"motor_winding": 1.0},
    "drive_current_a": {"drive_motor": 1.0}, "door_cycle_s": {"door_mechanism": 1.0}, "trips_per_day": {"controller": 1.0}, "leveling_mm": {"rope_wear": 0.6, "sensor": 0.6},
    "crack_mm": {"tile_failure": 0.8, "subsidence": 0.4}, "settlement_mm": {"subsidence": 1.0}, "driver_current_a": {"led_driver": 1.0}, "lamp_hours": {"lamp_eol": 1.0},
}
# consequence factors per category: (safety, environment, reputation) multipliers; service comes from consequence_units + dependency graph
COF_FACTORS: dict[str, tuple[float, float, float]] = {"lighting": (1.0, 0.2, 1.0), "pumping": (3.0, 2.5, 1.5), "elevators": (2.5, 0.2, 1.8), "pavement": (1.5, 0.3, 1.2)}
# SESI weights per category: heat, dust, humidity, season, rain
SESI_W: dict[str, tuple[float, float, float, float, float]] = {"lighting": (0.55, 0.20, 0.10, 0.05, 0.10), "pumping": (0.25, 0.25, 0.15, 0.10, 0.25),
                                                                "elevators": (0.35, 0.15, 0.10, 0.35, 0.05), "pavement": (0.20, 0.10, 0.10, 0.20, 0.40)}
CHANNEL_AR = {c: v[1] for c, v in CHANNELS.items()}


def channels_for(category: str) -> list[str]:
    return [c for c, v in CHANNELS.items() if v[0] == category]


# ----------------------------------------------------------------------------- glossary: every code the platform shows, with its Arabic meaning
CLASS_AR = {"A": ("أ · قابل للاستباق", "له نُذُر قابلة للرصد وفترة P–F أطول من المهلة اللازمة L: صيانة تنبؤية مجدولة آليًا"),
            "B": ("ب · قابل للرصد بمهلة قصيرة", "له نُذُر لكن فترة P–F أقصر من L: تجهيز مسبق للقطع أو حماية آلية أو تقليص L"),
            "C": ("ج · عشوائي أو خفي", "لا نُذُر قابلة للرصد بالتقنيات المتاحة: احتياطية أو فحص دوري أو التشغيل حتى العطل أو تعديل تصميمي")}
TIER_DEF = {"immediate": ("فوري", "خطورة عالية ويوم العطل المتوقع داخل مهلة التدخل L: تدخل خلال 24–48 ساعة"),
            "urgent": ("عاجل", "خطورة عالية ونافذة العطل خلال الشهر، أو ضمن أعلى 3% خطورة: جدولة خلال 7 أيام"),
            "planned": ("مخطط", "فوق عتبة الإنذار بخطورة متوسطة أو نافذة أبعد: الدورة القادمة مع التجميع الجغرافي"),
            "monitor": ("مراقبة", "خطورة منخفضة: مراقبة مستمرة دون تدخل")}
CODE_PREFIX = {"LP": "عمود إنارة (Light Pole)", "CB": "خزانة تغذية (Cabinet)", "PS": "أصل محطة ضخ (Pumping Station)", "EL": "مصعد/سلم متحرك/رافعة (Elevator)", "PV": "رصيف/منحدر/معبر (Pavement)"}
KIND_AR = {"pole": "عمود", "cabinet": "خزانة تغذية", "pump": "مضخة", "panel": "لوحة تحكم", "valve": "صمام", "elevator": "مصعد", "escalator": "سلم متحرك", "lift": "رافعة", "segment": "مقطع رصيف", "ramp": "منحدر", "crossing": "معبر مشاة"}
STREET_AR = {"main": "شارع رئيسي", "sec": "شارع فرعي"}
CRIT_AR = {"none": "بلا موقع حرج", "mosque": "قرب مسجد", "school": "قرب مدرسة", "crossing": "قرب معبر مشاة", "hospital": "قرب مستشفى"}
ACTION_DEF = {"inspect": ("فحص", "احتمال أقل من 35%: زيارة فحص وتسجيل العلامات"), "service": ("صيانة", "احتمال 35–70%: صيانة وقائية للمكوّن المرجّح"), "replace": ("استبدال", "احتمال ≥ 70% أو تجاوز العمر التصميمي: استبدال المكوّن/الأصل")}
STATUS_AR = {"proposed": "مقترح (بانتظار المشرف)", "approved": "معتمد", "overridden": "تجاوز بسبب مسجّل", "done": "منفّذ (أُغلقت الزيارة)", "skipped": "مُلغى بسبب مسجّل"}
SOURCE_AR = {"municipal": "تصدير الجهة (البلدية/الأمانة)", "contractor": "تصدير المقاول", "simulated": "محاكاة موسومة", "technician_qr": "تطبيق الفني (مسح QR)", "patrol": "جولة رقابية", "citizen": "بلاغ مواطن (940/بلدي)",
             "iot_pulse": "طقم «نبض» التحديثي (IoT)", "scada": "نظام SCADA", "controller": "وحدة تحكم المصعد", "vehicle_cam": "كاميرا مركبة البلدية", "smart_meter": "عداد ذكي", "cms": "نظام إدارة الإنارة المركزي", "ncm": "المركز الوطني للأرصاد", "baseera": "مولَّد من المنصة"}
REPORT_TYPE_AR = {"dark": "انطفاء/توقف", "flicker": "وميض (علامة قبل العطل)", "damage": "ضرر ظاهر", "other": "أخرى"}
FINDING_AR = {"confirmed_degradation": "تدهور مؤكد وعولج", "no_issue": "لا مشكلة (إنذار غير مؤكد)", "already_failed": "كان معطلًا فعلًا (إنذار متأخر)", "inaccessible": "تعذّر الوصول"}
WO_KIND_AR = {"emergency": "طارئ (بعد العطل) — مصدر أحداث العطل في السجل", "planned": "مخطط (قبل العطل) — تولّده المنصة"}
METRIC_AR = {"PFR@L": "نسبة الأعطال التي سبقها إنذار (قائمة معتمدة) بمهلة ≥ L يومًا؛ L لكل نمط عطل",
             "L": "المهلة اللازمة للتدخل: توفير القطع + تجهيز الطاقم + التصاريح، لكل نمط عطل",
             "P–F": "الفترة بين أول نُذُر قابلة للرصد (P) والعطل الوظيفي (F)", "SESI": "مؤشر الإجهاد البيئي السعودي: حرارة (أرينيوس) + غبار + رطوبة/ملوحة + مواسم + أمطار → عمر مكافئ مستهلك",
             "AUC": "قدرة النموذج على ترتيب الأصول التي ستتعطل قبل التي لن تتعطل (1 = مثالي، 0.5 = عشوائي)", "Brier": "خطأ المعايرة: مدى مطابقة الاحتمال المعلن للواقع (أقل = أفضل)",
             "نافذة العطل": "المدى بالأيام الذي يقع فيه العطل بثقة 90% (انحدار كمّي مطابَق)", "التغطية": "نسبة الأعطال الفعلية التي وقعت داخل نافذتها المتنبأ بها",
             "الحد الأعلى النظري": "حصة الأعطال ذات أنماط قابلة للرصد (أ+ب): ما يمكن بلوغه لو رُكّبت الحساسات المناسبة", "الخطورة": "الاحتمال × العواقب المكافئة بالريال (علاوة الطارئ + الخدمة مع الاعتماديات + السلامة + البيئة + السمعة)",
             "العائد لكل ريال": "الخطورة المُزالة (× فعالية التدخل) ÷ تكلفة التدخل المخطط", "z": "انحراف قراءة الحساس عن خط أساس الأصل نفسه بوحدات الانحراف المعياري؛ z > 2 شذوذ"}


def glossary() -> dict:
    return dict(code_prefixes=[dict(code=k, ar=v) for k, v in CODE_PREFIX.items()],
                kinds=[dict(code=k, ar=v) for k, v in KIND_AR.items()], streets=[dict(code=k, ar=v) for k, v in STREET_AR.items()],
                criticality=[dict(code=k, ar=v) for k, v in CRIT_AR.items()], classes=[dict(code=k, ar=v[0], desc=v[1]) for k, v in CLASS_AR.items()],
                tiers=[dict(code=k, ar=v[0], desc=v[1]) for k, v in TIER_DEF.items()], actions=[dict(code=k, ar=v[0], desc=v[1]) for k, v in ACTION_DEF.items()],
                statuses=[dict(code=k, ar=v) for k, v in STATUS_AR.items()], sources=[dict(code=k, ar=v) for k, v in SOURCE_AR.items()],
                report_types=[dict(code=k, ar=v) for k, v in REPORT_TYPE_AR.items()], findings=[dict(code=k, ar=v) for k, v in FINDING_AR.items()],
                work_order_kinds=[dict(code=k, ar=v) for k, v in WO_KIND_AR.items()], metrics=[dict(code=k, ar=v) for k, v in METRIC_AR.items()],
                channels=[dict(code=c, ar=v[1], unit=v[2], category=v[0], category_ar=CATEGORIES[v[0]]["ar"], source=v[4], source_ar=SOURCE_AR.get(v[4], v[4]), direction=("يرتفع عند التدهور" if v[3] > 0 else "ينخفض عند التدهور")) for c, v in CHANNELS.items()],
                parts=[dict(mode=m, mode_ar=MODES[m][1], parts=v[0], checklist=v[1], hours=v[2]) for m, v in PARTS.items() if m in MODES])
