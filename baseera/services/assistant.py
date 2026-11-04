"""Baseera assistant (layer 7): explains decisions in Arabic with the platform's own numbers and generates work orders.

Deterministic by design: every sentence is built from stored predictions, consequences, windows and constraints, so the
explanation is auditable. If BASEERA_ANTHROPIC_API_KEY is set, the same facts are handed to a language model for a more
natural answer; the facts, not the model, remain the source of truth.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.catalog import CATEGORIES, MODES, PARTS, TYPES
from ..core.config import get_settings
from ..core.models import Asset, ListItem, Prediction, WeeklyList, WorkOrder
from .decision.calendar import constraints_for, week_banner
from .decision.optimize import TIER_AR
from .decision.rank import ACTION_AR, GROUP_AR
from .ingest.base import normalise_code
from .ledger.pfr import L_for
from .model.prognosis import diagnose

CODE_RE = re.compile(r"\b(LP|CB|PS|EL|PV)[- ]?0*(\d+)\b", re.I)


def _wk(db: Session) -> date | None:
    return db.query(func.max(WeeklyList.week_start)).filter(WeeklyList.run_tag == "live").scalar()


def facts(db: Session, asset: Asset, wk: date | None = None) -> dict:
    wk = wk or _wk(db)
    p = db.query(Prediction).filter_by(asset_id=asset.asset_id, week_start=wk, run_tag="live").order_by(Prediction.p_fail.desc()).first() if wk else None
    item = None
    if wk:
        wl = db.query(WeeklyList).filter_by(week_start=wk, run_tag="live").first()
        if wl: item = next((i for i in wl.items if i.asset_id == asset.asset_id), None)
    cof = (p.cof or {}) if p else {}
    s = get_settings(); planned = float(s.cost_planned.get(asset.asset_type, 650))
    return dict(code=asset.asset_code, type=asset.asset_type, type_ar=TYPES[asset.asset_type][1], category=asset.category, category_ar=CATEGORIES[asset.category]["ar"],
                street=asset.street_class, crit=asset.criticality, week=str(wk) if wk else None,
                p=(round(p.p_fail, 3) if p else None), risk=(round(p.risk_sar) if p else None), cof=cof, planned_cost=planned,
                return_per_riyal=(round(p.risk_sar * s.intervention_efficacy / planned, 2) if p else None),
                window=((p.window_lo, p.window_hi) if p and p.window_lo is not None else None), tier=(p.tier if p else None),
                mode=(p.mode_pred if p else None), mode_ar=(MODES[p.mode_pred][1] if p and p.mode_pred in MODES else None),
                L=(L_for(p.mode_pred) if p else None), explanation=(p.explanation or {}) if p else {},
                item=(dict(rank=item.rank, action=item.action, action_ar=ACTION_AR.get(item.action), status=item.status, route=item.route, seq=item.seq, grouped=item.grouped,
                           safe_window=item.safe_window, item_id=item.item_id) if item else None))


def explain(db: Session, code: str) -> dict:
    a = db.query(Asset).filter_by(asset_code=normalise_code(code)).first()
    if not a:
        return dict(answer=f"لا أجد أصلًا بالرمز {code}.", facts=None)
    f = facts(db, a)
    if f["p"] is None:
        return dict(answer=f"{f['code']} ({f['type_ar']}) لا يحمل تنبؤًا لهذا الأسبوع بعد؛ أعد الحساب أولًا.", facts=f)
    top = sorted(f["explanation"].items(), key=lambda kv: -kv[1])[:2]
    why = "، ".join(GROUP_AR.get(g, g) for g, v in top if v > 0.005) or "النموذج"
    cof = f["cof"]; parts = []
    for k, ar in (("service", "انقطاع الخدمة"), ("safety", "السلامة"), ("financial", "علاوة الطارئ"), ("environment", "البيئة"), ("reputation", "السمعة")):
        if cof.get(k): parts.append(f"{ar} {cof[k]:,}")
    win = f"ونافذة العطل المتوقعة بين اليوم {f['window'][0]} و{f['window'][1]} بثقة {int(get_settings().conformal_coverage*100)}%" if f["window"] else "ولا نافذة زمنية بعد (بيانات غير كافية)"
    mode = f" النمط المرجّح: {f['mode_ar']} (المهلة اللازمة {f['L']} أيام)." if f["mode_ar"] else ""
    tier = TIER_AR.get(f["tier"], f["tier"] or "")
    item = f["item"]
    sched = (f"مُدرج في قائمة الأسبوع بالمرتبة {item['rank']} ({item['action_ar']}) ضمن المسار {item['route']} بالتسلسل {item['seq']}"
             + ("، أُضيف تجميعًا جغرافيًا بتكلفة تنقل شبه صفرية" if item["grouped"] else "") + f"؛ النافذة الآمنة: {item['safe_window']}." if item else "غير مُدرج في قائمة هذا الأسبوع (دون الطاقة أو الميزانية).")
    ans = (f"{f['code']} ({f['type_ar']}، {f['category_ar']}): احتمال العطل خلال 14 يومًا {f['p']*100:.0f}% بسبب {why}، {win}.{mode} "
           f"العواقب المكافئة {cof.get('total', 0):,} ريال ({'، '.join(parts)}" + (f"؛ ×{cof['season_boost']} موسم الأمطار" if cof.get("season_boost", 1) != 1 else "") + f")، "
           f"فالخطورة {f['risk']:,} ريال، والعائد لكل ريال تدخل {f['return_per_riyal']} (تكلفة التدخل المخطط {f['planned_cost']:,.0f}). الفئة: {tier}. {sched}")
    return dict(answer=ans, facts=f)


def compare(db: Session, code_a: str, code_b: str) -> dict:
    ea, eb = explain(db, code_a), explain(db, code_b)
    fa, fb = ea["facts"], eb["facts"]
    if not fa or not fb or fa["p"] is None or fb["p"] is None:
        return dict(answer=ea["answer"] + "\n" + eb["answer"], facts=[fa, fb])
    first, second = (fa, fb) if (fa["return_per_riyal"] or 0) >= (fb["return_per_riyal"] or 0) else (fb, fa)
    ans = (f"يُقدَّم {first['code']} على {second['code']} لأن العائد لكل ريال {first['return_per_riyal']} مقابل {second['return_per_riyal']}: "
           f"الخطورة {first['risk']:,} مقابل {second['risk']:,} ريال رغم أن الاحتمال {first['p']*100:.0f}% مقابل {second['p']*100:.0f}%. "
           f"الفارق يأتي من العواقب: {first['code']} عواقبه {first['cof'].get('total',0):,} ريال (الخدمة {first['cof'].get('service',0):,}، السلامة {first['cof'].get('safety',0):,}) "
           f"بينما {second['code']} عواقبه {second['cof'].get('total',0):,}. الاحتمال وحده مضلّل؛ الخطورة = الاحتمال × العواقب.")
    return dict(answer=ans, facts=[fa, fb])


def week_summary(db: Session) -> dict:
    wk = _wk(db)
    if not wk:
        return dict(answer="لا قائمة أسبوع بعد.", facts=None)
    wl = db.query(WeeklyList).filter_by(week_start=wk, run_tag="live").first()
    items = wl.items; by_tier = {}
    for i in items: by_tier[i.tier or "planned"] = by_tier.get(i.tier or "planned", 0) + 1
    risk = sum(i.risk_sar for i in items); grouped = sum(1 for i in items if i.grouped); routes = len({i.route for i in items if i.route})
    s = get_settings()
    ans = (f"أسبوع {wk}: {len(items)} مهمة في {routes} مسارات ({grouped} منها بالتجميع الجغرافي)، خطورة مُعالَجة {risk:,.0f} ريال. "
           + "، ".join(f"{TIER_AR[t]} {n}" for t, n in sorted(by_tier.items(), key=lambda kv: list(TIER_AR).index(kv[0]) if kv[0] in TIER_AR else 9))
           + f". الطاقة {wl.capacity} تدخل، الميزانية {s.weekly_budget_sar:,.0f} ريال. " + " ".join(week_banner(wk)))
    return dict(answer=ans, facts=dict(week=str(wk), n=len(items), by_tier=by_tier, routes=routes, grouped=grouped, risk=risk))


def answer(db: Session, question: str) -> dict:
    codes = [f"{m.group(1).upper()}-{int(m.group(2))}" for m in CODE_RE.finditer(question or "")]
    codes = [c.replace("CB-", "CB-") for c in codes]
    if len(codes) >= 2:
        res = compare(db, codes[0], codes[1])
    elif len(codes) == 1:
        res = explain(db, codes[0])
    else:
        res = week_summary(db)
    res["mode"] = "template"
    s = get_settings()
    if s.anthropic_api_key:
        try:
            import httpx
            prompt = (f"أنت مساعد منصة بصيرة للصيانة التنبؤية. أجب بالعربية الفصحى المختصرة اعتمادًا حصريًا على الحقائق التالية (JSON) دون اختلاق أرقام:\n"
                      f"{json.dumps(res.get('facts'), ensure_ascii=False, default=str)}\nالإجابة القالبية: {res['answer']}\nالسؤال: {question}")
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=30, headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                           json={"model": s.anthropic_model, "max_tokens": 600, "messages": [{"role": "user", "content": prompt}]})
            if r.status_code == 200:
                res["answer"] = "".join(b.get("text", "") for b in r.json().get("content", [])) or res["answer"]; res["mode"] = "llm"
        except Exception:
            pass
    return res


def create_work_order(db: Session, item_id: str, by: str) -> WorkOrder:
    """Planned work order from a list item: diagnosis, parts, checklist, safe window, hours — ready for the technician app."""
    item = db.get(ListItem, item_id)
    if not item:
        raise ValueError("item not found")
    existing = db.query(WorkOrder).filter_by(item_id=item_id).first()
    if existing:
        return existing
    a = db.get(Asset, item.asset_id); wl = item.weekly_list
    p = db.query(Prediction).filter_by(asset_id=a.asset_id, week_start=wl.week_start, run_tag="live").first()
    d = diagnose(db, a.asset_id, a.asset_type, a.category, wl.week_start)
    mode = d.get("mode") or (p.mode_pred if p else None)
    parts, checklist, hours = PARTS.get(mode, ("بحسب الفحص", "فحص عام وتوثيق بالصور", 2.0))
    con = constraints_for(wl.week_start, a.category, item.tier or "planned")
    s = get_settings()
    details = dict(asset=a.asset_code, type_ar=TYPES[a.asset_type][1], category_ar=CATEGORIES[a.category]["ar"], location=dict(lon=a.lon, lat=a.lat, street=a.street_class, crit=a.criticality),
                   tier=item.tier, tier_ar=TIER_AR.get(item.tier or "planned"), action=item.action, action_ar=ACTION_AR.get(item.action),
                   diagnosis=dict(mode=mode, mode_ar=(MODES[mode][1] if mode in MODES else None), confidence=d.get("confidence"), evidence=d.get("evidence", [])),
                   p_fail=(round(p.p_fail, 3) if p else None), window=((p.window_lo, p.window_hi) if p and p.window_lo is not None else None),
                   risk_sar=round(item.risk_sar), parts=parts, checklist=[c.strip() for c in checklist.split("،")], hours=hours,
                   safe_window=item.safe_window or con["safe_window"], constraints=con["notes"], route=item.route, seq=item.seq, generated_by=by,
                   generated_at=datetime.utcnow().isoformat(), text=None)
    details["text"] = (f"أمر عمل مخطط — {a.asset_code} ({details['type_ar']})\nالفئة: {details['tier_ar']} · الإجراء: {details['action_ar']}\n"
                       f"التشخيص المتوقع: {details['diagnosis']['mode_ar'] or 'فحص'}" + (f" (ثقة {int((d.get('confidence') or 0)*100)}%)" if d.get("confidence") else "") +
                       (f"\nنافذة العطل: اليوم {details['window'][0]}–{details['window'][1]}" if details["window"] else "") +
                       f"\nقطع الغيار: {parts}\nالخطوات: " + " ← ".join(details["checklist"]) + f"\nالوقت المقدر: {hours} ساعة\nالنافذة الآمنة: {details['safe_window']}" +
                       ("\n" + " · ".join(con["notes"]) if con["notes"] else ""))
    wo = WorkOrder(asset_id=a.asset_id, kind="planned", opened_at=datetime.utcnow(), fault_code=mode, cost_sar=float(s.cost_planned.get(a.asset_type, 650)),
                   source="baseera", item_id=item_id, details=details)
    db.add(wo); db.commit()
    return wo
