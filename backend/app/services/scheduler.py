"""Recurring jobs: EOD price refreshes (IST & ET aware), FX, weekly recommendations.

Price/FX jobs run without the keyring (public data only). The recommendation
job needs decryption and silently skips when the keyring is locked — start the
app with PF_PASSPHRASE set for fully unattended operation.
"""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..crypto.keys import key_manager
from ..db import SessionLocal
from ..models.auth import AuditLog
from .marketdata.service import market_data_service

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")

scheduler = BackgroundScheduler()


def _audit(action: str, detail: str) -> None:
    with SessionLocal() as db:
        db.add(AuditLog(actor="scheduler", action=action, detail=detail))
        db.commit()


def refresh_indian_prices() -> None:
    with SessionLocal() as db:
        report = market_data_service.refresh_all(db, country="IN")
    _audit("market.refresh_in",
           f"instruments={report.refreshed} bars={report.bars_upserted} failures={len(report.failures)}")


def refresh_us_prices() -> None:
    with SessionLocal() as db:
        report = market_data_service.refresh_all(db, country="US")
    _audit("market.refresh_us",
           f"instruments={report.refreshed} bars={report.bars_upserted} failures={len(report.failures)}")


def refresh_fx() -> None:
    with SessionLocal() as db:
        added = market_data_service.refresh_fx(db)
    _audit("market.refresh_fx", f"bars={added}")


def run_recommendations() -> None:
    if not key_manager.unlocked:
        log.warning("Recommendation run skipped: keyring locked (set PF_PASSPHRASE for unattended runs)")
        _audit("reco.skipped", "keyring locked")
        return
    from .recommendations.engine import run_recommendation_engine

    with SessionLocal() as db:
        count = run_recommendation_engine(db)
    _audit("reco.run", f"recommendations={count}")


def start_scheduler() -> None:
    if scheduler.running:
        return
    # NSE/BSE close 15:30 IST; refresh after settlement of EOD data.
    scheduler.add_job(refresh_indian_prices, CronTrigger(
        day_of_week="mon-fri", hour=18, minute=30, timezone=IST), id="refresh_in")
    # US markets close 16:00 ET.
    scheduler.add_job(refresh_us_prices, CronTrigger(
        day_of_week="mon-fri", hour=17, minute=30, timezone=ET), id="refresh_us")
    scheduler.add_job(refresh_fx, CronTrigger(
        day_of_week="mon-fri", hour=19, minute=0, timezone=IST), id="refresh_fx")
    # Weekly digest: Sunday evening IST, before the week opens.
    scheduler.add_job(run_recommendations, CronTrigger(
        day_of_week="sun", hour=18, minute=0, timezone=IST), id="weekly_reco")
    scheduler.start()
    log.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
