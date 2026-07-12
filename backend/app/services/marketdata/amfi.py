"""Indian mutual fund NAVs via mfapi.in (free mirror of AMFI data).

Symbols use the form MF:<amfi_scheme_code>, e.g. MF:120503.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .base import Bar

log = logging.getLogger(__name__)

_BASE = "https://api.mfapi.in/mf/"


class AmfiProvider:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=20)

    def get_daily_bars(self, symbol: str, days: int = 400) -> list[Bar]:
        if not symbol.startswith("MF:"):
            raise ValueError(f"AMFI symbols look like MF:<code>, got {symbol!r}")
        code = symbol[3:]
        resp = self._client.get(f"{_BASE}{code}")
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data") or []
        bars: list[Bar] = []
        for row in rows[:days]:  # newest first
            try:
                nav_date = datetime.strptime(row["date"], "%d-%m-%Y").date()
                bars.append(Bar(bar_date=nav_date, close=float(row["nav"])))
            except (KeyError, ValueError):
                continue
        bars.reverse()  # oldest first, matching other providers
        return bars
