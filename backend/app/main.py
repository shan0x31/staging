from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.crud_routes import (
    accounts_router,
    instruments_router,
    manual_assets_router,
    transactions_router,
)
from .api.market_routes import router as market_router
from .api.portfolio_routes import router as portfolio_router
from .auth.routes import router as auth_router
from .config import settings
from .crypto.keys import key_manager
from .db import SessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.passphrase:
        with SessionLocal() as db:
            if key_manager.is_initialized(db):
                key_manager.unlock(db, settings.passphrase)
    if settings.scheduler_enabled:
        from .services.scheduler import start_scheduler

        start_scheduler()
    yield
    if settings.scheduler_enabled:
        from .services.scheduler import stop_scheduler

        stop_scheduler()
    key_manager.lock()


def create_app() -> FastAPI:
    app = FastAPI(title="Personal Finance Platform", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    app.include_router(accounts_router)
    app.include_router(instruments_router)
    app.include_router(transactions_router)
    app.include_router(manual_assets_router)
    app.include_router(portfolio_router)
    app.include_router(market_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
