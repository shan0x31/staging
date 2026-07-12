# Personal Finance Platform

A privacy-first, self-hosted personal finance platform focused on **Indian (NSE/BSE) and US
equities**, with mutual funds, FDs, gold and other asset classes alongside. It tracks market
data on a schedule, runs an explainable **recommendation engine**, and lets you **discuss your
portfolio with Claude using your Claude subscription** (via MCP — no API billing).

> **Not investment advice.** All recommendations are rule-generated informational signals.
> This software is not a SEBI-registered adviser or a fiduciary.

See [PLAN.md](PLAN.md) for the full architecture and roadmap.

## Features

- **Transaction ledger** → FIFO lots, average cost (fees capitalized), realized/unrealized
  P&L, dividends, splits/bonuses, XIRR — INR/USD aware with automatic FX conversion.
- **CSV import** with account/instrument auto-creation, duplicate detection, and per-row
  error reporting (template downloadable in the UI).
- **Market data on a schedule**: NSE/BSE + US equities and USD/INR via Yahoo (EOD),
  Indian MF NAVs via AMFI — refreshed weekdays at 18:30 IST / 17:30 ET.
- **Recommendation engine** (weekly + on-demand): concentration and allocation-drift
  warnings, currency exposure, India LTCG/STCG boundary flags, tax-loss-harvesting
  candidates, 50/200-DMA crosses, RSI, 52-week extremes, 12-1 momentum. Every finding
  carries its rationale and the numbers behind it.
- **Claude chat via MCP**: read-only tools over your portfolio, with **privacy mode ON by
  default** — Claude sees percentages and signals, never absolute amounts, until you flip
  the switch in Settings.
- **Web dashboard** (light/dark): net worth, allocations, movers, holdings, recommendations.

## Security model

| Layer | Mechanism |
|---|---|
| At rest | Field-level **AES-256-GCM** on quantities, prices, amounts, notes, account numbers, recommendation content. Envelope scheme: passphrase → **Argon2id** → master key → wraps a random data-encryption key. Passphrase is never stored; a stolen DB/backup is unreadable without it. |
| In transit | HTTPS via Caddy (Let's Encrypt for real domains, internal CA for localhost); DB unexposed on a private compose network. |
| Third parties | Market-data requests carry **tickers only** — never quantities, costs, or identity. Price refresh reads only public tables and works with the vault locked. |
| Claude/MCP | Privacy mode (default ON) strips absolute values; every MCP tool call is audit-logged. |
| Access | Argon2id password hashing, bearer sessions with expiry, login rate limiting, lock/unlock (lock wipes the key from memory), audit log. |

**Honest limits:** this protects against DB/backup theft, network snooping, and third-party
data sharing. It cannot protect a fully compromised running host (an attacker with root while
the vault is unlocked can read memory). Add OS-level disk encryption (LUKS/FileVault) and
encrypted off-site backups (`pg_dump | age`) for depth.

Losing the encryption passphrase makes encrypted data **unrecoverable by design**.

## Quick start (Docker)

```bash
cp .env.example .env        # set POSTGRES_PASSWORD (and optionally PF_PASSPHRASE, DOMAIN)
docker compose up -d --build
```

Open <https://localhost> (accept the self-signed cert for localhost), create your vault
(username + password + encryption passphrase), then import a CSV from the Transactions page
and hit *Refresh market data* in Settings.

If `PF_PASSPHRASE` is empty, unlock the vault in the UI after each restart; scheduled
recommendation runs are skipped while locked (price refresh still works — public data only).

## Chat with Claude (subscription, no API key)

The backend ships an MCP server exposing read-only portfolio tools
(`get_portfolio_summary`, `get_holdings`, `get_recommendations`, `search_transactions`,
`get_market_snapshot`).

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "personal-finance": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/path/to/repo/backend",
      "env": { "PF_PASSPHRASE": "<encryption passphrase>" }
    }
  }
}
```

Then ask Claude things like *“How concentrated is my portfolio?”*, *“What did last week's
recommendation run flag?”*, *“Which holdings are near their 52-week high?”*. With privacy
mode ON (default) Claude sees weights and signals, not amounts.

## CSV import template

Header: `date,type,symbol,name,exchange,asset_class,quantity,price,fees,amount,currency,account,notes`

| type | required fields | notes |
|---|---|---|
| buy / sell | quantity, price (+fees) | |
| dividend / fee / deposit / withdrawal | amount | |
| split | quantity = multiplier (5 for 1:5) | adjusts existing lots |
| bonus | quantity = shares received | zero-cost lot |

Symbols are provider-ready: `RELIANCE.NS` (NSE), `TCS.BO` (BSE), `AAPL` (US),
`MF:120503` (AMFI scheme code for Indian mutual funds).

## Development

```bash
# backend (Python 3.11+)
cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev,mcp]"
.venv/bin/pytest                                # 68 tests
.venv/bin/uvicorn app.main:app --reload         # http://localhost:8000

# frontend
cd frontend && npm install && npm run dev       # http://localhost:5173 (proxies /api -> :8000)
```

SQLite is the zero-config default for development (`backend/data/pf.db`); the compose stack
uses Postgres. Field-level encryption is identical on both.

## Repository layout

```
backend/app/crypto/           envelope encryption (Argon2id + AES-256-GCM column types)
backend/app/auth/             password auth, sessions, rate limiting, lock/unlock
backend/app/models/           SQLAlchemy models (encrypted sensitive columns)
backend/app/services/         portfolio math, CSV import, market data, scheduler,
                              recommendation engine, MCP data views
backend/app/api/              REST routers
backend/app/mcp_server.py     MCP stdio server for Claude
frontend/src/                 React app (dashboard, holdings, transactions, recos, settings)
docker-compose.yml            db + api + web (Caddy TLS)
```
