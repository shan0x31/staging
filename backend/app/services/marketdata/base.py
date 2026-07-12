from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class Bar:
    bar_date: date
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


class QuoteProvider(Protocol):
    """Pluggable EOD quote source. Implementations must only ever be sent
    instrument symbols — never quantities, costs, or user identity."""

    def get_daily_bars(self, symbol: str, days: int = 400) -> list[Bar]: ...
