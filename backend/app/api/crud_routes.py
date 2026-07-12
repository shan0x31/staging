"""CRUD routers for accounts, instruments, transactions, manual assets."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.auth import AuditLog, User
from ..models.portfolio import Account, Instrument, ManualAsset, Transaction
from ..services.importer import import_generic_csv
from .deps import require_unlocked
from .schemas import (
    AccountIn, AccountOut, ImportSummary, InstrumentIn, InstrumentOut,
    ManualAssetIn, ManualAssetOut, TransactionIn, TransactionOut,
)

accounts_router = APIRouter(prefix="/accounts", tags=["accounts"])
instruments_router = APIRouter(prefix="/instruments", tags=["instruments"])
transactions_router = APIRouter(prefix="/transactions", tags=["transactions"])
manual_assets_router = APIRouter(prefix="/manual-assets", tags=["manual-assets"])


# -- accounts -----------------------------------------------------------------

@accounts_router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), _: User = Depends(require_unlocked)):
    return db.execute(select(Account).order_by(Account.name)).scalars().all()


@accounts_router.post("", response_model=AccountOut, status_code=201)
def create_account(body: AccountIn, db: Session = Depends(get_db),
                   _: User = Depends(require_unlocked)):
    if db.execute(select(Account).where(Account.name == body.name)).first():
        raise HTTPException(409, "Account name already exists")
    acct = Account(**body.model_dump())
    db.add(acct)
    db.commit()
    return acct


@accounts_router.put("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountIn, db: Session = Depends(get_db),
                   _: User = Depends(require_unlocked)):
    acct = db.get(Account, account_id)
    if acct is None:
        raise HTTPException(404, "Account not found")
    for k, v in body.model_dump().items():
        setattr(acct, k, v)
    db.commit()
    return acct


@accounts_router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db),
                   _: User = Depends(require_unlocked)):
    acct = db.get(Account, account_id)
    if acct is None:
        raise HTTPException(404, "Account not found")
    n_txn = db.execute(select(func.count(Transaction.id))
                       .where(Transaction.account_id == account_id)).scalar_one()
    if n_txn:
        raise HTTPException(409, f"Account has {n_txn} transactions; delete them first")
    db.delete(acct)
    db.commit()


# -- instruments ----------------------------------------------------------------

@instruments_router.get("", response_model=list[InstrumentOut])
def list_instruments(q: str | None = None, db: Session = Depends(get_db),
                     _: User = Depends(require_unlocked)):
    stmt = select(Instrument).order_by(Instrument.symbol)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(Instrument.symbol.ilike(pattern) | Instrument.name.ilike(pattern))
    return db.execute(stmt).scalars().all()


@instruments_router.post("", response_model=InstrumentOut, status_code=201)
def create_instrument(body: InstrumentIn, db: Session = Depends(get_db),
                      _: User = Depends(require_unlocked)):
    if db.execute(select(Instrument).where(Instrument.symbol == body.symbol)).first():
        raise HTTPException(409, "Symbol already exists")
    inst = Instrument(**body.model_dump())
    db.add(inst)
    db.commit()
    return inst


@instruments_router.put("/{instrument_id}", response_model=InstrumentOut)
def update_instrument(instrument_id: int, body: InstrumentIn, db: Session = Depends(get_db),
                      _: User = Depends(require_unlocked)):
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(404, "Instrument not found")
    for k, v in body.model_dump().items():
        setattr(inst, k, v)
    db.commit()
    return inst


# -- transactions -----------------------------------------------------------------

@transactions_router.get("", response_model=list[TransactionOut])
def list_transactions(
    instrument_id: int | None = None,
    account_id: int | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_unlocked),
):
    stmt = select(Transaction).order_by(Transaction.trade_date.desc(), Transaction.id.desc())
    if instrument_id:
        stmt = stmt.where(Transaction.instrument_id == instrument_id)
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    return db.execute(stmt.limit(limit).offset(offset)).scalars().all()


@transactions_router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(body: TransactionIn, db: Session = Depends(get_db),
                       _: User = Depends(require_unlocked)):
    if db.get(Account, body.account_id) is None:
        raise HTTPException(404, "Account not found")
    if body.instrument_id is not None and db.get(Instrument, body.instrument_id) is None:
        raise HTTPException(404, "Instrument not found")
    if body.type in {"buy", "sell"} and (body.quantity is None or body.price is None):
        raise HTTPException(422, f"{body.type} requires quantity and price")
    txn = Transaction(**body.model_dump())
    db.add(txn)
    db.commit()
    return txn


@transactions_router.delete("/{txn_id}", status_code=204)
def delete_transaction(txn_id: int, db: Session = Depends(get_db),
                       _: User = Depends(require_unlocked)):
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    db.delete(txn)
    db.commit()


@transactions_router.post("/import", response_model=ImportSummary)
async def import_csv(file: UploadFile, skip_duplicates: bool = True,
                     db: Session = Depends(get_db), _: User = Depends(require_unlocked)):
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large (10 MB limit)")
    result = import_generic_csv(db, content, skip_duplicates=skip_duplicates)
    db.add(AuditLog(actor="web", action="import.csv",
                    detail=f"batch={result.batch_id} imported={result.imported} "
                           f"dupes={result.skipped_duplicates} errors={len(result.errors)}"))
    db.commit()
    return ImportSummary(batch_id=result.batch_id, imported=result.imported,
                         skipped_duplicates=result.skipped_duplicates, errors=result.errors)


# -- manual assets -----------------------------------------------------------------

@manual_assets_router.get("", response_model=list[ManualAssetOut])
def list_manual_assets(db: Session = Depends(get_db), _: User = Depends(require_unlocked)):
    return db.execute(select(ManualAsset).order_by(ManualAsset.name)).scalars().all()


@manual_assets_router.post("", response_model=ManualAssetOut, status_code=201)
def create_manual_asset(body: ManualAssetIn, db: Session = Depends(get_db),
                        _: User = Depends(require_unlocked)):
    asset = ManualAsset(**body.model_dump())
    db.add(asset)
    db.commit()
    return asset


@manual_assets_router.put("/{asset_id}", response_model=ManualAssetOut)
def update_manual_asset(asset_id: int, body: ManualAssetIn, db: Session = Depends(get_db),
                        _: User = Depends(require_unlocked)):
    asset = db.get(ManualAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    for k, v in body.model_dump().items():
        setattr(asset, k, v)
    db.commit()
    return asset


@manual_assets_router.delete("/{asset_id}", status_code=204)
def delete_manual_asset(asset_id: int, db: Session = Depends(get_db),
                        _: User = Depends(require_unlocked)):
    asset = db.get(ManualAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    db.delete(asset)
    db.commit()
