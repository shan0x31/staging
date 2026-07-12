"""Pure technical-indicator functions over EOD close series (oldest first)."""
from __future__ import annotations


def sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def sma_series(closes: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    running = 0.0
    for i, c in enumerate(closes):
        running += c
        if i >= window:
            running -= closes[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder-smoothed RSI."""
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def crossover(closes: list[float], fast: int = 50, slow: int = 200,
              lookback: int = 5) -> str | None:
    """'golden' if fast SMA crossed above slow within `lookback` bars,
    'death' if it crossed below, else None."""
    if len(closes) < slow + lookback:
        return None
    f = sma_series(closes, fast)
    s = sma_series(closes, slow)
    for i in range(len(closes) - lookback, len(closes)):
        if f[i] is None or s[i] is None or f[i - 1] is None or s[i - 1] is None:
            continue
        if f[i - 1] <= s[i - 1] and f[i] > s[i]:
            return "golden"
        if f[i - 1] >= s[i - 1] and f[i] < s[i]:
            return "death"
    return None


def pct_from_52w_extremes(closes: list[float]) -> tuple[float, float] | None:
    """(pct below 52w high, pct above 52w low) for the latest close."""
    window = closes[-252:] if len(closes) >= 20 else None
    if not window:
        return None
    hi, lo = max(window), min(window)
    last = closes[-1]
    below_high = (hi - last) / hi * 100 if hi else 0.0
    above_low = (last - lo) / lo * 100 if lo else 0.0
    return below_high, above_low


def momentum_12_1(closes: list[float]) -> float | None:
    """12-month return excluding the most recent month (~21 bars), in %."""
    if len(closes) < 252:
        return None
    start, end = closes[-252], closes[-21]
    if start == 0:
        return None
    return (end - start) / start * 100
