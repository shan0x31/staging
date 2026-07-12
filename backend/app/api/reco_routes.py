from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models.auth import AuditLog, Setting, User
from ..models.reco import Recommendation
from ..services.recommendations.engine import DISCLAIMER, run_recommendation_engine
from .deps import require_unlocked

router = APIRouter(prefix="/recommendations", tags=["recommendations"])
settings_router = APIRouter(prefix="/settings", tags=["settings"])


class RecoOut(BaseModel):
    id: int
    run_id: str
    created_at: datetime
    kind: str
    category: str
    severity: str
    symbol: str | None
    title: str
    rationale: str
    data: dict | None
    dismissed: bool


class RecoRunOut(BaseModel):
    run_id: str | None
    generated: int
    disclaimer: str


def _to_out(r: Recommendation) -> RecoOut:
    return RecoOut(
        id=r.id, run_id=r.run_id, created_at=r.created_at, kind=r.kind,
        category=r.category, severity=r.severity,
        symbol=r.instrument.symbol if r.instrument else None,
        title=r.title, rationale=r.rationale, data=r.data, dismissed=r.dismissed,
    )


@router.get("", response_model=list[RecoOut])
def list_recommendations(
    latest_only: bool = True,
    include_dismissed: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_unlocked),
):
    stmt = (select(Recommendation)
            .options(joinedload(Recommendation.instrument))
            .order_by(desc(Recommendation.created_at), Recommendation.id))
    rows = db.execute(stmt).scalars().all()
    if latest_only and rows:
        latest_run = rows[0].run_id
        rows = [r for r in rows if r.run_id == latest_run]
    if not include_dismissed:
        rows = [r for r in rows if not r.dismissed]
    return [_to_out(r) for r in rows]


@router.post("/run", response_model=RecoRunOut)
def trigger_run(db: Session = Depends(get_db), _: User = Depends(require_unlocked)):
    count = run_recommendation_engine(db)
    db.add(AuditLog(actor="web", action="reco.run", detail=f"generated={count}"))
    db.commit()
    latest = db.execute(
        select(Recommendation.run_id).order_by(desc(Recommendation.created_at))
    ).scalars().first()
    return RecoRunOut(run_id=latest, generated=count, disclaimer=DISCLAIMER)


@router.post("/{reco_id}/dismiss", response_model=RecoOut)
def dismiss(reco_id: int, db: Session = Depends(get_db), _: User = Depends(require_unlocked)):
    reco = db.get(Recommendation, reco_id)
    if reco is None:
        raise HTTPException(404, "Recommendation not found")
    reco.dismissed = True
    db.commit()
    return _to_out(reco)


# -- settings ------------------------------------------------------------------

ALLOWED_SETTINGS = {"target_allocation", "privacy_mode"}


class SettingIn(BaseModel):
    value: dict | list | str | int | float | bool | None


@settings_router.get("")
def get_settings(db: Session = Depends(get_db), _: User = Depends(require_unlocked)) -> dict:
    rows = db.execute(select(Setting)).scalars().all()
    return {row.key: json.loads(row.value_json) for row in rows}


@settings_router.put("/{key}")
def put_setting(key: str, body: SettingIn, db: Session = Depends(get_db),
                _: User = Depends(require_unlocked)) -> dict:
    if key not in ALLOWED_SETTINGS:
        raise HTTPException(422, f"Unknown setting {key!r}; allowed: {sorted(ALLOWED_SETTINGS)}")
    row = db.get(Setting, key)
    payload = json.dumps(body.value)
    if row is None:
        db.add(Setting(key=key, value_json=payload))
    else:
        row.value_json = payload
    db.commit()
    return {key: body.value}
