"""Arabic assistant: explain a decision, compare two assets, summarise the week, generate a work order."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.models import User, WorkOrder
from ...core.security import audit, require
from ...services import assistant as A

router = APIRouter(prefix="/assistant", tags=["assistant"])


class Ask(BaseModel):
    question: str


@router.post("/ask")
def ask(body: Ask, db: Session = Depends(get_db), u: User = Depends(require())):
    return A.answer(db, body.question)


@router.get("/explain/{code}")
def explain(code: str, db: Session = Depends(get_db), u: User = Depends(require())):
    return A.explain(db, code)


@router.post("/work-order/{item_id}", status_code=201)
def work_order(item_id: str, db: Session = Depends(get_db), u: User = Depends(require("supervisor", "admin"))):
    try:
        wo = A.create_work_order(db, item_id, by=u.username)
    except ValueError as e:
        raise HTTPException(404, str(e))
    audit(db, u.username, "work_order.generate", "work_order", wo.wo_id, None, dict(item_id=item_id)); db.commit()
    return dict(wo_id=wo.wo_id, details=wo.details)


@router.get("/work-orders")
def work_orders(limit: int = 50, db: Session = Depends(get_db), u: User = Depends(require())):
    return [dict(wo_id=w.wo_id, opened_at=w.opened_at.isoformat(), details=w.details) for w in
            db.query(WorkOrder).filter(WorkOrder.item_id.isnot(None)).order_by(WorkOrder.opened_at.desc()).limit(limit).all()]
