from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.auth import User
from ..services.reports import capital_gains_report, dividends_report, fy_of_date_india
from .deps import require_unlocked

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/capital-gains")
def capital_gains(
    year: int = Query(..., ge=2000, le=2100,
                      description="FY start year for fy_in (2025 = Apr'25-Mar'26); calendar year for calendar_us"),
    basis: str = Query("fy_in", pattern="^(fy_in|calendar_us)$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_unlocked),
):
    try:
        return capital_gains_report(db, year, basis)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/dividends")
def dividends(
    year: int = Query(..., ge=2000, le=2100),
    basis: str = Query("fy_in", pattern="^(fy_in|calendar_us)$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_unlocked),
):
    try:
        return dividends_report(db, year, basis)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/periods")
def available_periods(db: Session = Depends(get_db), _: User = Depends(require_unlocked)):
    """FY/calendar options for the UI selector, derived from the ledger span."""
    from sqlalchemy import func, select

    from ..models.portfolio import Transaction

    first, last = db.execute(
        select(func.min(Transaction.trade_date), func.max(Transaction.trade_date))
    ).one()
    if first is None:
        return {"fy_in": [], "calendar_us": []}
    fys = list(range(fy_of_date_india(first), fy_of_date_india(last) + 1))
    years = list(range(first.year, last.year + 1))
    return {"fy_in": fys[::-1], "calendar_us": years[::-1]}
