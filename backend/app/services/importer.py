"""CSV import into the transaction ledger.

Generic template columns (header required, case-insensitive):
  date,type,symbol,name,exchange,asset_class,quantity,price,fees,amount,currency,account,notes

- date: YYYY-MM-DD or DD-MM-YYYY or DD/MM/YYYY
- type: buy|sell|dividend|split|bonus|fee|deposit|withdrawal
- symbol: provider-ready (RELIANCE.NS, AAPL, MF:120503). Optional for deposit/withdrawal.
- account: created on the fly if unknown.
Unknown instruments are created with the row's name/exchange/asset_class/currency.
"""
from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.portfolio import TXN_TYPES, Account, Instrument, Transaction

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d")


@dataclass
class ImportResult:
    batch_id: str
    imported: int = 0
    skipped_duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    detected_format: str = "generic"


def _parse_date(value: str) -> date:
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date: {value!r}")


def _dec(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.replace(",", "").strip())
    except InvalidOperation:
        raise ValueError(f"Bad number: {value!r}") from None


def _get_or_create_account(db: Session, name: str, currency: str) -> Account:
    acct = db.execute(select(Account).where(Account.name == name)).scalars().first()
    if acct is None:
        country = "US" if currency == "USD" else "IN"
        acct = Account(name=name, currency=currency or "INR", country=country)
        db.add(acct)
        db.flush()
    return acct


def _infer_country_exchange(symbol: str, exchange: str) -> tuple[str, str]:
    if exchange:
        return ("IN" if exchange.upper() in {"NSE", "BSE", "AMFI"} else "US", exchange.upper())
    if symbol.endswith(".NS"):
        return "IN", "NSE"
    if symbol.endswith(".BO"):
        return "IN", "BSE"
    if symbol.startswith("MF:"):
        return "IN", "AMFI"
    return "US", "OTHER"


def _get_or_create_instrument(db: Session, row: dict) -> Instrument:
    symbol = row["symbol"].strip()
    inst = db.execute(select(Instrument).where(Instrument.symbol == symbol)).scalars().first()
    if inst is None:
        country, exchange = _infer_country_exchange(symbol, row.get("exchange", "").strip())
        currency = row.get("currency", "").strip().upper() or ("INR" if country == "IN" else "USD")
        inst = Instrument(
            symbol=symbol,
            name=row.get("name", "").strip() or symbol,
            exchange=exchange,
            asset_class=(row.get("asset_class", "").strip().lower() or
                         ("mutual_fund" if symbol.startswith("MF:") else "equity")),
            currency=currency,
            country=country,
        )
        db.add(inst)
        db.flush()
    return inst


def _is_duplicate(db: Session, account_id: int, instrument_id: int | None,
                  trade_date: date, txn_type: str,
                  quantity: Decimal | None, price: Decimal | None,
                  amount: Decimal | None) -> bool:
    candidates = db.execute(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.instrument_id == instrument_id,
            Transaction.trade_date == trade_date,
            Transaction.type == txn_type,
        )
    ).scalars().all()
    for c in candidates:  # encrypted fields compared post-decryption
        if c.quantity == quantity and c.price == price and c.amount == amount:
            return True
    return False


def import_csv(db: Session, content: bytes | str, fmt: str | None = None,
               skip_duplicates: bool = True, account: str | None = None) -> ImportResult:
    """Import any supported CSV. Broker formats (Zerodha/Groww/US-broker) are
    auto-detected from the header signature and normalized into generic rows."""
    from .broker_formats import PARSERS, detect_format

    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    header_reader = csv.reader(io.StringIO(text))
    try:
        headers = next(header_reader)
    except StopIteration:
        return ImportResult(batch_id="", errors=["Empty file"])

    detected = fmt or detect_format(headers)
    if detected == "unknown":
        return ImportResult(batch_id="", errors=[
            "Unrecognized CSV format. Use the generic template or a supported "
            "broker export (Zerodha tradebook, Groww tradebook, US broker activity)."])
    if detected == "generic":
        result = import_generic_csv(db, text, skip_duplicates=skip_duplicates)
        result.detected_format = "generic"
        return result

    parser = PARSERS[detected]
    rows = parser(text, account=account) if account else parser(text)
    result = ImportResult(batch_id=str(uuid.uuid4()), detected_format=detected)
    _import_rows(db, rows, result, skip_duplicates)
    return result


def import_generic_csv(db: Session, content: bytes | str,
                       skip_duplicates: bool = True) -> ImportResult:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return ImportResult(batch_id="", errors=["Empty file"])
    reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]
    required = {"date", "type", "account"}
    missing = required - set(reader.fieldnames)
    if missing:
        return ImportResult(batch_id="", errors=[f"Missing columns: {sorted(missing)}"])

    result = ImportResult(batch_id=str(uuid.uuid4()))
    _import_rows(db, reader, result, skip_duplicates)
    return result


def _import_rows(db: Session, rows, result: ImportResult, skip_duplicates: bool) -> None:
    for lineno, row in enumerate(rows, start=2):
        try:
            txn_type = (row.get("type") or "").strip().lower()
            if txn_type not in TXN_TYPES:
                raise ValueError(f"Unknown type {txn_type!r}")
            trade_date = _parse_date(row.get("date") or "")
            currency = (row.get("currency") or "").strip().upper()
            account = _get_or_create_account(db, (row.get("account") or "").strip() or "Default",
                                             currency)
            instrument = None
            if (row.get("symbol") or "").strip():
                instrument = _get_or_create_instrument(db, row)
            elif txn_type not in {"deposit", "withdrawal", "fee"}:
                raise ValueError(f"type {txn_type!r} requires a symbol")

            quantity, price = _dec(row.get("quantity")), _dec(row.get("price"))
            fees, amount = _dec(row.get("fees")), _dec(row.get("amount"))

            if txn_type in {"buy", "sell"} and (not quantity or price is None):
                raise ValueError(f"{txn_type} requires quantity and price")
            if txn_type in {"dividend", "fee", "deposit", "withdrawal"} and amount is None:
                raise ValueError(f"{txn_type} requires amount")
            if txn_type in {"split", "bonus"} and not quantity:
                raise ValueError(f"{txn_type} requires quantity")

            if skip_duplicates and _is_duplicate(
                    db, account.id, instrument.id if instrument else None,
                    trade_date, txn_type, quantity, price, amount):
                result.skipped_duplicates += 1
                continue

            db.add(Transaction(
                account_id=account.id,
                instrument_id=instrument.id if instrument else None,
                type=txn_type,
                trade_date=trade_date,
                quantity=quantity,
                price=price,
                fees=fees,
                amount=amount,
                notes=(row.get("notes") or "").strip() or None,
                import_batch=result.batch_id,
            ))
            result.imported += 1
        except ValueError as exc:
            result.errors.append(f"line {lineno}: {exc}")
    db.commit()
