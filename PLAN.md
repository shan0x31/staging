# Personal Finance Platform — Build Plan

A privacy-first personal finance platform covering multiple asset classes, with a primary
focus on **Indian (NSE/BSE) and US equity** tracking and a **recommendation engine** that runs
on a recurring schedule. Users can discuss their portfolio with **Claude via their existing
subscription (no API billing)**.

---

## 1. Vision & Scope

| Capability | In scope | Notes |
|---|---|---|
| Stock tracking (IN + US) | ✅ Primary | NSE, BSE, NYSE, NASDAQ |
| Other asset classes | ✅ Secondary | Mutual funds (IN), ETFs, FDs, gold, EPF/PPF, cash, crypto (optional), real estate (manual) |
| Portfolio upload/import | ✅ | Broker CSV/Excel imports + manual entry + generic template |
| Market data tracking | ✅ | Scheduled EOD refresh; intraday optional later |
| Recommendation engine | ✅ | Quant/rule-based signals + portfolio health, on a cron schedule |
| Chat with Claude about investments | ✅ | Via Claude subscription (MCP connector), **not** metered API |
| Trade execution | ❌ | Read-only platform; no order placement in v1 |
| Multi-user SaaS | ❌ (default) | Single-user self-hosted first; architecture leaves the door open |

**Compliance stance:** the platform generates *informational signals*, not investment advice.
Every recommendation surface carries a disclaimer (not SEBI-registered / not a fiduciary).

---

## 2. Guiding Constraints

1. **Financial data must never leak.**
   - Encrypted at rest (field-level AES-256-GCM envelope encryption on sensitive columns + encrypted DB volume).
   - Encrypted in transit (TLS for every hop, including DB connections).
   - Market-data lookups send **tickers only** — never quantities, costs, or identity.
   - "Privacy mode" for Claude chats: share allocations as percentages, withhold absolute ₹/$ amounts.
2. **Claude via subscription, not API.** The user chats in claude.ai / Claude Desktop / Claude mobile,
   which connects to the platform through a **local MCP server** exposing portfolio tools. No
   Anthropic API key, no per-token billing.
3. **India + US first-class.** Dual currency (INR/USD), dual tax regimes, dual market calendars
   (IST & ET), Indian instruments (MF NAVs via AMFI) alongside US ones.
4. **Self-hosted, single user by default.** Runs via Docker Compose on the user's machine/home
   server/VPS. Simplest possible trust boundary: your data never sits on someone else's SaaS.

---

## 3. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                        User's machine / VPS                        │
│                                                                    │
│  ┌───────────┐   HTTPS/TLS   ┌──────────────────────────────────┐  │
│  │  Web UI   │◄─────────────►│         FastAPI backend          │  │
│  │ (React)   │               │  ┌────────────┐ ┌─────────────┐  │  │
│  └───────────┘               │  │ Portfolio  │ │ Import      │  │  │
│                              │  │ core       │ │ (CSV/XLSX)  │  │  │
│  ┌───────────┐    MCP        │  ├────────────┤ ├─────────────┤  │  │
│  │ Claude    │◄─────────────►│  │ Recommend- │ │ Market data │  │  │
│  │ Desktop / │  (stdio or    │  │ ation      │ │ service     │──┼──┼──► Quote providers
│  │ claude.ai │  streamable   │  │ engine     │ │ (pluggable) │  │  │    (tickers only,
│  └───────────┘   HTTP+auth)  │  ├────────────┤ └─────────────┘  │  │     over TLS)
│                              │  │ Scheduler (APScheduler cron)  │  │
│                              │  └───────────────────────────────┘  │
│                              │        Crypto layer (AES-256-GCM    │
│                              │        envelope encryption)         │
│                              └────────────────┬─────────────────┘  │
│                                               │ TLS                │
│                                      ┌────────▼────────┐           │
│                                      │ PostgreSQL      │           │
│                                      │ (encrypted      │           │
│                                      │  fields+volume) │           │
│                                      └─────────────────┘           │
└────────────────────────────────────────────────────────────────────┘
```

### Components

1. **FastAPI backend (Python)** — REST API for the UI, houses all business logic. Python chosen
   for its finance ecosystem (pandas, yfinance, ta-lib alternatives) powering the
   recommendation engine.
2. **React + Vite frontend** — dashboard (net worth, allocation, P&L), holdings views,
   import wizard, recommendations feed, settings.
3. **Market data service** — pluggable provider interface. Default: free EOD sources
   (Yahoo Finance for US + NSE `.NS`/BSE `.BO` symbols; AMFI/mfapi.in for Indian MF NAVs;
   exchangerate.host for USD/INR). Optional adapters later: Zerodha Kite Connect, Upstox,
   Finnhub, Alpha Vantage.
4. **Import service** — parsers for broker exports (Zerodha Console holdings/tradebook, Groww,
   US brokers' CSVs) plus a documented generic CSV/XLSX template. Everything lands in a
   normalized transaction ledger.
5. **Portfolio core** — transaction ledger → holdings, average cost (FIFO lots), realized/
   unrealized P&L, XIRR, allocation by asset class/sector/geography/currency.
6. **Recommendation engine** (see §5).
7. **Scheduler** — APScheduler in-process cron: EOD price refresh after market close (IST and
   ET aware), recommendation runs (default weekly + on-demand), backup jobs.
8. **MCP server** — exposes read-only tools (`get_portfolio_summary`, `get_holdings`,
   `get_recommendations`, `get_performance`, `search_transactions`) so Claude (on the user's
   subscription) can discuss the portfolio. Privacy mode filter applied at this boundary.
9. **Crypto layer** — every sensitive field passes through here before touching disk (see §6).

---

## 4. Data Model (core tables)

- `accounts` — broker/bank/AMC accounts (name, type, currency, country). Account numbers encrypted.
- `instruments` — ticker, exchange, ISIN, asset class, sector, currency. (Public info — not encrypted.)
- `transactions` — buy/sell/dividend/split/bonus/fee; qty, price, date, account. **Encrypted.**
- `holdings` (materialized) — instrument, qty, avg cost, lots. **Encrypted.**
- `prices` — EOD OHLC cache per instrument. (Public info.)
- `fx_rates` — USD/INR history.
- `recommendations` — run id, timestamp, signal type, instrument, rationale, severity. **Encrypted.**
- `manual_assets` — FDs, real estate, EPF/PPF with valuation history. **Encrypted.**
- `settings`, `audit_log`, `schema_migrations`.

Ledger-first design: holdings are always derivable from transactions, so imports are
idempotent and corrections are replayable.

---

## 5. Recommendation Engine

Two layers, both explainable (every output carries its rationale + the data it used):

**A. Portfolio-health rules (highest value, runs first)**
- Allocation drift vs user's target allocation → rebalancing suggestions.
- Concentration risk: single stock > X% of equity, sector > Y%, single-country tilt.
- Currency exposure: INR/USD split vs target.
- Idle cash drag; overlapping mutual funds (same top holdings).
- Tax awareness: India LTCG/STCG holding-period flags (12-month equity boundary),
  tax-loss-harvesting candidates near FY end (India: Jan–Mar; US: Nov–Dec, wash-sale warning).

**B. Instrument-level quant signals**
- Trend: 50/200-DMA crossovers, price vs 52-week range.
- Momentum/mean-reversion: RSI(14) overbought/oversold, 12-1 momentum rank.
- Valuation context where data is available: P/E vs instrument's own 5-yr band.
- Benchmark-relative performance: holding vs NIFTY 50 / S&P 500 over 3/6/12 months.

**Scheduling:** default weekly full run (Sunday evening IST) + daily lightweight alerts
(price moves > threshold, 52-week breaks, DMA crosses on held stocks). All runs persisted to
the `recommendations` feed; optionally rendered into a narrative digest by Claude when the
user opens a chat (subscription-side, so narration costs nothing extra).

**Explicit non-goal:** no black-box "buy this stock" calls. Signals + reasoning, user decides.

---

## 6. Security Design

**Transit**
- Web UI ↔ backend: HTTPS only (self-signed or Let's Encrypt via Caddy reverse proxy in compose).
- Backend ↔ Postgres: TLS (`sslmode=require`) even on localhost network.
- Backend ↔ market data: HTTPS, tickers only — no portfolio quantities ever leave the box.
- MCP: stdio transport for Claude Desktop (never leaves the machine); if remote access from
  claude.ai is wanted, streamable-HTTP behind TLS + bearer auth token.

**At rest — envelope encryption**
- Master key derived from a user passphrase via **Argon2id** at app unlock (never stored),
  or supplied via OS keyring / key file for unattended scheduled runs.
- Per-table **data-encryption keys (DEKs)**, wrapped by the master key (rotation = re-wrap
  DEKs, not re-encrypt all rows).
- Sensitive columns encrypted with **AES-256-GCM** (authenticated encryption, per-row nonce)
  at the application layer — DB compromise alone reveals nothing about positions.
- Postgres volume additionally encrypted (LUKS on self-host, or provider disk encryption).
- Backups: `pg_dump` piped through `age` encryption; restore drill documented.

**Access**
- Single-user auth: Argon2id-hashed password + optional TOTP 2FA; short-lived session tokens;
  rate-limited login; auto-lock after inactivity.
- Audit log of every read/write to sensitive tables and every MCP tool call.
- Privacy mode (default **on** for MCP): Claude sees percentages, ratios, and signal
  rationales — not absolute amounts — unless the user flips the setting.

**Threat model honesty:** this protects against DB/backup theft, network snooping, and
third-party data sharing. It cannot protect against full compromise of the running host —
documented plainly rather than overpromised.

---

## 7. Recommended Features (beyond the ask)

Suggested additions, roughly by value:

1. **Capital-gains tax report** — India FY-wise STCG/LTCG statement (with ₹1.25L LTCG
   exemption tracking) and US-style realized-gains report. Huge tax-season time-saver.
2. **Dividend tracker** — received + upcoming ex-dates for held stocks, dividend yield on cost.
3. **Corporate-actions handling** — splits/bonuses auto-adjust lots (critical for Indian stocks).
4. **Benchmark comparison** — portfolio XIRR vs NIFTY 50, S&P 500, and a blended benchmark.
5. **Goal tracking** — link holdings to goals (retirement, house), project with expected returns.
6. **Alerts** — price/threshold/signal alerts via email or ntfy/Telegram push.
7. **Watchlists** — track non-held stocks; recommendation engine can screen them too.
8. **Privacy mode** (described above) — recommended to build in v1, it's the data-leak firewall.
9. **Encrypted backup/export** — one-click encrypted archive; plain-CSV export for portability.
10. **What-if simulator** — model a buy/sell and preview allocation + tax impact (later phase).

---

## 8. Phased Roadmap

| Phase | Deliverable | Contents |
|---|---|---|
| **0** | Scaffold | Repo layout, Docker Compose (API+DB+Caddy), migrations, auth, crypto layer with tests |
| **1** | Portfolio core | Instruments, transactions ledger, holdings math (FIFO/XIRR), manual entry, generic CSV import |
| **2** | Market data + dashboard | Provider interface, Yahoo/AMFI adapters, EOD scheduler, FX, dashboard UI (net worth, allocation, P&L) |
| **3** | Broker imports | Zerodha/Groww parsers + one US broker; corporate actions |
| **4** | Recommendation engine | Portfolio-health rules, quant signals, scheduled runs, recommendations feed UI |
| **5** | Claude via MCP | MCP server + tools, privacy mode, Claude Desktop/claude.ai connector setup docs |
| **6** | Hardening | 2FA, audit log, encrypted backups, tax reports, alerts |

Each phase lands as working, tested software — the platform is usable from Phase 2 onward.

---

## 9. Open Questions

1. **Deployment model** — single-user self-hosted (recommended) or multi-user cloud?
2. **Claude integration path** — MCP connector into Claude apps (recommended, pure
   subscription) vs. embedded chat UI (needs Agent SDK + subscription OAuth, more moving parts)?
3. **Market data** — start free/EOD (Yahoo + AMFI, recommended) or wire a broker API
   (Zerodha Kite ₹500/mo, real-time) from day one?
4. **Tech stack confirmation** — Python FastAPI + React (recommended) vs. full TypeScript/Next.js?
