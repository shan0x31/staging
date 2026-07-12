from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest

from app.models.market import FxRate, PriceBar
from app.models.portfolio import Instrument
from app.services.marketdata.amfi import AmfiProvider
from app.services.marketdata.service import MarketDataService
from app.services.marketdata.yahoo import YahooProvider

# Recent dates so the service's retention cutoff keeps them.
D1, D2, D3 = (date.today() - timedelta(days=n) for n in (4, 3, 2))


def _ts(d: date) -> int:
    return int(datetime.combine(d, time(10), tzinfo=timezone.utc).timestamp())


def yahoo_payload(symbol="RELIANCE.NS"):
    return {
        "chart": {
            "result": [{
                "meta": {"symbol": symbol},
                "timestamp": [_ts(D1), _ts(D2), _ts(D3)],
                "indicators": {"quote": [{
                    "open": [100.0, 102.0, None],
                    "high": [105.0, 106.0, None],
                    "low": [99.0, 101.0, None],
                    "close": [104.0, 105.5, None],  # None = holiday row
                    "volume": [1000, 1100, None],
                }]},
            }],
            "error": None,
        }
    }


AMFI_PAYLOAD = {
    "meta": {"scheme_name": "Test Fund"},
    "status": "SUCCESS",
    "data": [
        {"date": D3.strftime("%d-%m-%Y"), "nav": "102.5000"},
        {"date": D2.strftime("%d-%m-%Y"), "nav": "101.0000"},
        {"date": D1.strftime("%d-%m-%Y"), "nav": "100.0000"},
    ],
}


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_yahoo_provider_parses_bars():
    def handler(request):
        assert "RELIANCE.NS" in str(request.url)
        return httpx.Response(200, json=yahoo_payload())

    bars = YahooProvider(client=mock_client(handler)).get_daily_bars("RELIANCE.NS")
    assert len(bars) == 2  # None close skipped
    assert bars[0].bar_date == D1
    assert bars[0].close == 104.0
    assert bars[1].volume == 1100


def test_yahoo_provider_handles_unknown_symbol():
    def handler(request):
        return httpx.Response(200, json={"chart": {"result": None, "error": {"code": "Not Found"}}})

    assert YahooProvider(client=mock_client(handler)).get_daily_bars("NOPE.XX") == []


def test_amfi_provider_parses_navs():
    def handler(request):
        assert str(request.url).endswith("/mf/120503")
        return httpx.Response(200, json=AMFI_PAYLOAD)

    bars = AmfiProvider(client=mock_client(handler)).get_daily_bars("MF:120503")
    assert [b.close for b in bars] == [100.0, 101.0, 102.5]  # oldest first
    assert bars[0].bar_date == D1


def test_amfi_rejects_non_mf_symbol():
    with pytest.raises(ValueError):
        AmfiProvider(client=mock_client(lambda r: httpx.Response(200))).get_daily_bars("AAPL")


@pytest.fixture()
def svc():
    def yahoo_handler(request):
        url = str(request.url)
        if "USDINR=X" in url:
            payload = yahoo_payload("USDINR=X")
            payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [83.1, 83.4, None]
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json=yahoo_payload())

    def amfi_handler(request):
        return httpx.Response(200, json=AMFI_PAYLOAD)

    return MarketDataService(
        yahoo=YahooProvider(client=mock_client(yahoo_handler)),
        amfi=AmfiProvider(client=mock_client(amfi_handler)),
    )


def test_refresh_all_routes_by_symbol_and_upserts(db_session, svc):
    db_session.add_all([
        Instrument(symbol="RELIANCE.NS", name="Reliance", country="IN"),
        Instrument(symbol="MF:120503", name="Test Fund", country="IN",
                   asset_class="mutual_fund", exchange="AMFI"),
    ])
    db_session.commit()

    report = svc.refresh_all(db_session)
    assert report.refreshed == 2
    assert report.failures == []
    assert report.bars_upserted == 5  # 2 yahoo + 3 amfi

    # idempotent: second run adds nothing
    report2 = svc.refresh_all(db_session)
    assert report2.bars_upserted == 0

    n = db_session.query(PriceBar).count()
    assert n == 5


def test_refresh_fx(db_session, svc):
    added = svc.refresh_fx(db_session)
    assert added == 2
    rates = db_session.query(FxRate).order_by(FxRate.rate_date).all()
    assert rates[-1].rate == 83.4
    assert svc.refresh_fx(db_session) == 0  # idempotent


def test_one_bad_symbol_does_not_sink_batch(db_session):
    def handler(request):
        if "BAD" in str(request.url):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=yahoo_payload())

    service = MarketDataService(yahoo=YahooProvider(client=mock_client(handler)),
                                amfi=AmfiProvider(client=mock_client(handler)))
    db_session.add_all([
        Instrument(symbol="BAD.NS", name="Bad", country="IN"),
        Instrument(symbol="GOOD.NS", name="Good", country="IN"),
    ])
    db_session.commit()
    report = service.refresh_all(db_session)
    assert report.refreshed == 1
    assert len(report.failures) == 1 and "BAD.NS" in report.failures[0]
