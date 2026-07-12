from app.services.recommendations.technicals import (
    crossover,
    momentum_12_1,
    pct_from_52w_extremes,
    rsi,
    sma,
    sma_series,
)


def test_sma():
    assert sma([1, 2, 3, 4, 5], 5) == 3
    assert sma([1, 2, 3], 5) is None
    series = sma_series([1, 2, 3, 4], 2)
    assert series == [None, 1.5, 2.5, 3.5]


def test_rsi_all_gains_is_100():
    closes = list(range(1, 40))
    assert rsi([float(c) for c in closes]) == 100.0


def test_rsi_mixed_within_bounds():
    closes = [100 + ((-1) ** i) * (i % 7) for i in range(60)]
    value = rsi([float(c) for c in closes])
    assert value is not None and 0 <= value <= 100


def test_rsi_insufficient_data():
    assert rsi([1.0, 2.0, 3.0]) is None


def test_golden_cross_detected():
    # 250 flat bars, then a sharp rally: 50-DMA crosses above 200-DMA.
    # The cross is a single-bar event, so scan every slice length.
    closes = [100.0] * 250 + [100 + 3 * i for i in range(60)]
    found = any(crossover(closes[: 250 + n]) == "golden" for n in range(1, 60))
    assert found


def test_death_cross_detected():
    closes = [100.0 + 3 * i for i in range(250)] + [800 - 8 * i for i in range(80)]
    found = any(crossover(closes[: 250 + n]) == "death" for n in range(1, 80))
    assert found


def test_52w_extremes():
    closes = [float(x) for x in range(100, 352)]  # rising: last = 351 is the high
    result = pct_from_52w_extremes(closes)
    assert result is not None
    below_high, above_low = result
    assert below_high == 0.0
    assert above_low > 100


def test_momentum_12_1():
    closes = [100.0] * 300
    assert momentum_12_1(closes) == 0.0
    rising = [100.0 + i for i in range(300)]
    assert momentum_12_1(rising) > 0
    assert momentum_12_1([1.0] * 100) is None
