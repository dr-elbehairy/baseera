"""Runtime parameters the field calibrates from the admin panel.

The Settings object (config.py) carries the .env defaults. Overrides saved in sys_setting are applied onto the cached
Settings instance at startup and after every change, so every service keeps reading get_settings() unchanged.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .config import get_settings
from .models import Setting

# key → (label_ar, group, type, help_ar). Only these keys can be overridden from the UI.
EDITABLE: dict[str, tuple[str, str, str, str]] = {
    "horizon_days": ("أفق التنبؤ (يوم)", "النموذج", "int", "النموذج يتنبأ بالعطل خلال هذا العدد من الأيام"),
    "lead_default": ("مهلة الإنذار الافتراضية L (يوم)", "القياس", "int", "تُستخدم عندما يكون نمط العطل غير معروف"),
    "lead_by_mode": ("مهلة الإنذار لكل نمط عطل", "القياس", "dict_int", "عدد الأيام التي يحتاجها الطاقم لمنع كل نمط عطل، لكل فئات الأصول (الإنارة، الضخ، المصاعد، الأرصفة)"),
    "crew_jobs_per_week": ("طاقة الطاقم الأسبوعية (تدخل)", "التشغيل", "int", "عدد التدخلات المخططة التي يستوعبها طاقم القطاع أسبوعيًا"),
    "alert_probability": ("عتبة الإنذار (احتمال)", "التشغيل", "float", "لا يدخل الأصل القائمة تحت هذا الاحتمال"),
    "emergency_multiplier": ("مضاعف تكلفة الطارئ", "الاقتصاد", "float", "تكلفة الإصلاح الطارئ ÷ تكلفة الإصلاح المخطط"),
    "consequence_sar_per_unit": ("كلفة العواقب لكل وحدة (ر.س)", "الاقتصاد", "float", "الكلفة الاجتماعية/السلامة لعمود مظلم في شارع فرعي"),
    "intervention_efficacy": ("فعالية التدخل", "الاقتصاد", "float", "نسبة الأعطال القابلة للتنبؤ التي يمنعها التدخل في وقته"),
    "match_radius_m": ("نصف قطر المطابقة المكانية (م)", "الاستيعاب", "float", "لبلاغ بلا رمز أصل: أقرب أصل ضمن هذه المسافة"),
    "cost_planned": ("تكلفة التدخل المخطط لكل نوع (ر.س)", "الاقتصاد", "dict_num", "لكل نوع أصل في الفئات الأربع"),
    "gate_min_auc": ("بوابة AUC الدنيا", "بوابات النموذج", "float", "لا يُرقَّى إصدار تحتها"),
    "gate_min_pfr_gain_over_age": ("بوابة التفوق على قاعدة العمر", "بوابات النموذج", "float", "PFR@L(النموذج) − PFR@L(قاعدة العمر) على شريحة التحقق"),
    "gate_max_single_group_share": ("بوابة أقصى حصة لمجموعة خصائص", "بوابات النموذج", "float", "حماية من التسريب: مجموعة واحدة لا تفسر أكثر من هذه الحصة"),
}


def _coerce(key: str, v):
    t = EDITABLE[key][2]
    if t == "int":
        return int(v)
    if t == "float":
        return float(v)
    if t == "dict_int":
        return {str(k): int(x) for k, x in dict(v).items()}
    if t == "dict_num":
        return {str(k).upper(): float(x) for k, x in dict(v).items()}
    return v


def apply_overrides(db: Session) -> dict:
    """Load sys_setting rows onto the cached Settings instance. Returns the applied overrides."""
    s = get_settings(); applied = {}
    for row in db.query(Setting).all():
        if row.key in EDITABLE:
            val = _coerce(row.key, row.value["v"])
            object.__setattr__(s, row.key, val); applied[row.key] = val
    return applied


def defaults() -> dict:
    from .config import Settings
    d = Settings(_env_file=None)
    return {k: getattr(d, k) for k in EDITABLE}


def current(db: Session) -> list[dict]:
    s = get_settings(); over = {r.key: r for r in db.query(Setting).all()}; dflt = defaults()
    out = []
    for k, (label, group, typ, help_) in EDITABLE.items():
        out.append(dict(key=k, label=label, group=group, type=typ, help=help_, value=getattr(s, k), default=dflt[k],
                        overridden=k in over, updated_at=(over[k].updated_at.isoformat() if k in over else None),
                        updated_by=(over[k].updated_by if k in over else None)))
    return out


def set_many(db: Session, values: dict, by: str) -> dict:
    changed = {}
    for k, v in values.items():
        if k not in EDITABLE:
            raise ValueError(f"unknown or read-only parameter: {k}")
        val = _coerce(k, v)
        row = db.get(Setting, k) or Setting(key=k, value={"v": val})
        changed[k] = {"before": getattr(get_settings(), k), "after": val}
        row.value, row.updated_by = {"v": val}, by
        db.add(row)
    db.commit()
    apply_overrides(db)
    return changed


def reset(db: Session, keys: list[str] | None = None) -> None:
    q = db.query(Setting)
    if keys:
        q = q.filter(Setting.key.in_(keys))
    q.delete(synchronize_session=False); db.commit()
    s = get_settings(); d = defaults()
    for k in (keys or list(EDITABLE)):
        object.__setattr__(s, k, d[k])
