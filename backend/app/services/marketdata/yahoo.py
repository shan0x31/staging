"""Yahoo Finance chart API adapter.

Covers US listings (AAPL), NSE (RELIANCE.NS), BSE (TCS.BO), and FX (USDINR=X)
with free EOD/delayed data. No API key; a browser-ish User-Agent is required.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx

from .base import Bar

log = logging.getLogger(__name__)

_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) pf-platform/0.1"}


class YahooProvider:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(headers=_HEADERS, timeout=20)

    def get_daily_bars(self, symbol: str, days: int = 400) -> list[Bar]:
        range_param = "2y" if days > 365 else ("1y" if days > 90 else "3mo")
        resp = self._client.get(
            f"{_BASE}{symbol}",
            params={"range": range_param, "interval": "1d", "events": "div,split"},
        )
        resp.raise_for_status()
        payload = resp.json()
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            error = (payload.get("chart") or {}).get("error")
            log.warning("Yahoo returned no data for %s: %s", symbol, error)
            return []
        node = result[0]
        timestamps = node.get("timestamp") or []
        quote = ((node.get("indicators") or {}).get("quote") or [{}])[0]
        bars: list[Bar] = []
        for i, ts in enumerate(timestamps):
            close = (quote.get("close") or [None])[i] if i < len(quote.get("close") or []) else None
            if close is None:
                continue  # holiday/partial row
            bar_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
            bars.append(Bar(
                bar_date=bar_date,
                close=float(close),
                open=_at(quote.get("open"), i),
                high=_at(quote.get("high"), i),
                low=_at(quote.get("low"), i),
                volume=_at(quote.get("volume"), i),
            ))
        return bars


def _at(seq: list | None, i: int) -> float | None:
    if not seq or i >= len(seq) or seq[i] is None:
        return None
    return float(seq[i])
