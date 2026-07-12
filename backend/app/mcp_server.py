"""MCP server: chat about your portfolio with Claude on your subscription.

Run:  PF_PASSPHRASE=... python -m app.mcp_server   (stdio transport)

Claude Desktop config (~/.config/Claude/claude_desktop_config.json):
{
  "mcpServers": {
    "personal-finance": {
      "command": "python", "args": ["-m", "app.mcp_server"],
      "cwd": "/path/to/backend",
      "env": {"PF_PASSPHRASE": "<encryption passphrase>"}
    }
  }
}

Privacy: tools apply privacy mode (see services/mcp_views.py) — Claude sees
percentages and signals, not absolute amounts, unless the user disables it.
All tool calls are audit-logged with actor="mcp".
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .config import settings
from .crypto.keys import key_manager
from .db import SessionLocal, init_db
from .models.auth import AuditLog
from .services import mcp_views as views

mcp = FastMCP(
    "personal-finance",
    instructions=(
        "Read-only access to the user's personal finance platform (Indian + US "
        "equities, mutual funds, other assets). Values may be privacy-filtered "
        "to percentages. Rule-generated recommendations are informational "
        "signals, not investment advice — always remind the user of this when "
        "discussing actions."),
)


def _run(action: str, fn) -> str:
    with SessionLocal() as db:
        if not key_manager.unlocked:
            return json.dumps({"error": "Keyring locked. Start the MCP server with "
                                        "PF_PASSPHRASE set to your encryption passphrase."})
        result = fn(db)
        db.add(AuditLog(actor="mcp", action=action))
        db.commit()
        return json.dumps(result, default=str)


@mcp.tool()
def get_portfolio_summary() -> str:
    """Portfolio overview: allocation percentages by asset class/currency/sector,
    XIRR, unrealized P&L %, position count. Absolute values only if the user
    disabled privacy mode."""
    return _run("mcp.summary", views.portfolio_summary_view)


@mcp.tool()
def get_holdings() -> str:
    """Current positions with portfolio weight %, unrealized P&L %, sector and
    currency. Quantities/costs included only if privacy mode is off."""
    return _run("mcp.holdings", views.holdings_view)


@mcp.tool()
def get_recommendations() -> str:
    """Latest recommendation-engine run: portfolio-health warnings, tax flags
    (India LTCG/STCG, loss harvesting), and technical signals with rationales."""
    return _run("mcp.recommendations", views.recommendations_view)


@mcp.tool()
def search_transactions(symbol: str = "", limit: int = 50) -> str:
    """Recent transactions (dates, types, symbols), optionally filtered by
    symbol, e.g. 'RELIANCE.NS'. Amounts included only if privacy mode is off."""
    return _run("mcp.transactions",
                lambda db: views.transactions_view(db, symbol or None, limit))


@mcp.tool()
def get_market_snapshot() -> str:
    """Latest day-change % for each held instrument (public market data)."""
    return _run("mcp.market", views.market_snapshot_view)


def main() -> None:
    init_db()
    if settings.passphrase:
        with SessionLocal() as db:
            if key_manager.is_initialized(db):
                key_manager.unlock(db, settings.passphrase)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
