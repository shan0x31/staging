"""Broker-export parsers: convert broker CSVs into generic-template rows.

Each parser yields dicts with the generic import columns
(date,type,symbol,name,exchange,asset_class,quantity,price,fees,amount,
currency,account,notes) so every format flows through the same validated
pipeline in importer.py. Formats are auto-detected from the header signature.

Supported:
- Zerodha Console tradebook (equity):
    symbol,isin,trade_date,exchange,segment,series,trade_type,auction,
    quantity,price,trade_id,order_id,order_execution_time
- Groww stock tradebook:
    Stock Name,ISIN,Trade Date,Exchange,Type,Quantity,Price
- US broker activity (Fidelity/Schwab style):
    Date/Run Date,Action,Symbol,Description,Quantity,Price,Fees/Commission,Amount
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import datetime


def _norm_headers(fieldnames: list[str]) -> list[str]:
    return [f.strip().lower().replace("($)", "").strip() for f in fieldnames]


def detect_format(fieldnames: list[str]) -> str:
    headers = set(_norm_headers(fieldnames))
    if {"symbol", "trade_type", "trade_date", "exchange"} <= headers:
        return "zerodha"
    if {"stock name", "type", "quantity", "price"} <= headers and (
            "trade date" in headers or "trade_date" in headers):
        return "groww"
    if "action" in headers and ("symbol" in headers) and (
            "date" in headers or "run date" in headers):
        return "us_broker"
    if {"date", "type", "account"} <= headers:
        return "generic"
    return "unknown"


def _reader(text: str) -> csv.DictReader:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames:
        reader.fieldnames = _norm_headers(list(reader.fieldnames))
    return reader


def _suffix_for_exchange(exchange: str) -> str:
    exchange = (exchange or "").strip().upper()
    if exchange == "BSE":
        return ".BO"
    return ".NS"  # NSE default for Indian brokers


def parse_zerodha(text: str, account: str = "Zerodha") -> Iterator[dict]:
    for row in _reader(text):
        trade_type = (row.get("trade_type") or "").strip().lower()
        if trade_type not in {"buy", "sell"}:
            continue  # ignore non-equity/auction rows
        exchange = (row.get("exchange") or "NSE").strip().upper()
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        yield {
            "date": (row.get("trade_date") or "").strip(),
            "type": trade_type,
            "symbol": symbol + _suffix_for_exchange(exchange),
            "name": symbol,
            "exchange": exchange,
            "asset_class": "equity",
            "quantity": row.get("quantity") or "",
            "price": row.get("price") or "",
            "fees": "",
            "amount": "",
            "currency": "INR",
            "account": account,
            "notes": (row.get("trade_id") and f"trade_id={row['trade_id']}") or "",
        }


def parse_groww(text: str, account: str = "Groww") -> Iterator[dict]:
    for row in _reader(text):
        trade_type = (row.get("type") or "").strip().lower()
        if trade_type not in {"buy", "sell"}:
            continue
        name = (row.get("stock name") or "").strip()
        # Groww exports the display name; the ISIN keeps identity stable and the
        # NSE symbol is user-editable later. Use name-derived placeholder symbol.
        isin = (row.get("isin") or "").strip()
        exchange = (row.get("exchange") or "NSE").strip().upper()
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            base = "".join(ch for ch in name.upper() if ch.isalnum())[:20] or isin or "UNKNOWN"
            symbol = base
        yield {
            "date": (row.get("trade date") or row.get("trade_date") or "").strip(),
            "type": trade_type,
            "symbol": symbol + _suffix_for_exchange(exchange),
            "name": name or symbol,
            "exchange": exchange,
            "asset_class": "equity",
            "quantity": row.get("quantity") or "",
            "price": row.get("price") or "",
            "fees": "",
            "amount": "",
            "currency": "INR",
            "account": account,
            "notes": isin and f"isin={isin}" or "",
        }


_US_ACTION_MAP = {
    "buy": "buy",
    "you bought": "buy",
    "reinvestment": "buy",
    "sell": "sell",
    "you sold": "sell",
    "dividend": "dividend",
    "dividend received": "dividend",
    "qualified dividend": "dividend",
    "cash dividend": "dividend",
}


def _map_us_action(action: str) -> str | None:
    action = action.strip().lower()
    for prefix, mapped in _US_ACTION_MAP.items():
        if action.startswith(prefix):
            return mapped
    return None


def _us_date(value: str) -> str:
    """US exports are MM/DD/YYYY; emit ISO so the generic date parser (which
    tries DD/MM first) cannot misread ambiguous days."""
    value = value.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value  # let the pipeline report the bad row


def parse_us_broker(text: str, account: str = "US Broker") -> Iterator[dict]:
    for row in _reader(text):
        action = row.get("action") or ""
        mapped = _map_us_action(action)
        if mapped is None:
            continue  # transfers, interest, journal entries
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        raw_date = _us_date(row.get("date") or row.get("run date") or "")
        fees = (row.get("fees & comm") or row.get("commission") or
                row.get("fees") or "").strip()
        amount = (row.get("amount") or "").strip().replace("$", "")
        qty = (row.get("quantity") or "").strip()
        # US sell rows often carry negative quantities; the ledger wants positive.
        if qty.startswith("-"):
            qty = qty[1:]
        out = {
            "date": raw_date,
            "type": mapped,
            "symbol": symbol,
            "name": (row.get("description") or symbol).strip(),
            "exchange": "OTHER",
            "asset_class": "equity",
            "quantity": qty if mapped in {"buy", "sell"} else "",
            "price": (row.get("price") or "").strip().replace("$", "")
                     if mapped in {"buy", "sell"} else "",
            "fees": fees.replace("$", "") if mapped in {"buy", "sell"} else "",
            "amount": amount.lstrip("-") if mapped == "dividend" else "",
            "currency": "USD",
            "account": account,
            "notes": "",
        }
        yield out


PARSERS = {
    "zerodha": parse_zerodha,
    "groww": parse_groww,
    "us_broker": parse_us_broker,
}
