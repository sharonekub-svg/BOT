# Polymarket Edge

An automated prediction-market trading platform for **Polymarket**: it scans every active market in near-real-time, detects pricing inefficiencies and arbitrage, asks Claude for probability estimates grounded in news/social context, sizes positions with fractional Kelly under hard risk limits, executes (paper by default, live optional), and reports everything on a dark real-time dashboard.

> ⚠️ **Use responsibly.** This is research/portfolio tooling, not financial advice. Prediction-market trading can lose money quickly; backtests and AI estimates are not guarantees. Live trading is **off by default** (`TRADING_MODE=paper`, `AUTO_TRADE_ENABLED=false`). Confirm prediction-market trading is legal in your jurisdiction before enabling live mode.

---

## What it does

| Subsystem | Capability |
|---|---|
| **Market scanner** | Pages every active market from the Gamma API each cycle, refreshes CLOB order books for the top-N liquid markets, stores full price/liquidity/volume history, detects price jumps, volume spikes, and liquidity drops (rolling z-scores) |
| **Edge engine** | Implied vs fair probability (confidence-weighted ensemble of AI + ML + market anchor), expected value, full-Kelly sizing, composite **Edge Score 0–100** |
| **Arbitrage** | Binary complement (YES+NO < $1), multi-outcome event baskets (long & short), cross-market implication violations |
| **AI analysis (Claude)** | News/Reddit/X context gathering → structured probability estimate, confidence, bullish/bearish signal, reasoning, key factors, contradiction detection, per-source sentiment — via the Anthropic API with prompt caching and strict JSON output |
| **Risk management** | Fractional Kelly with hard caps, per-trade/market/category/total exposure limits, daily-loss halt, max-drawdown circuit breaker, stop-losses, auto-hedging, liquidity participation caps |
| **Execution** | Market & limit orders, paper broker (default) or live Polymarket CLOB via `py-clob-client`, position accounting, rebalancing |
| **Dashboard** | Next.js + TypeScript + Tailwind + Recharts + WebSockets: equity & P&L, edge rankings, open positions, allocation, risk utilization, arbitrage, live event feed, market heatmap |
| **Alerts** | Telegram: high-edge signals, new arbitrage, risk warnings, large moves, high-confidence AI calls — with cooldown/dedup via Redis |
| **Backtesting** | Event-driven simulator over stored history: Sharpe, Sortino, max drawdown, CAGR, win rate, profit factor, EV accuracy (Brier + directional hit rate) |
| **Machine learning** | Gradient boosting + isotonic calibration on resolved-market history; AI vs ML vs market vs outcome calibration scoring |
| **Relationship graph** | Same-event edges + return-correlation discovery (hidden correlations), cascade simulation of probability shocks across linked markets |

## Architecture

```
                        ┌────────────────────────────────────────────────┐
                        │                 WORKER PROCESS                 │
   Polymarket Gamma ───▶│  Scanner ──▶ Anomaly detector                  │
   Polymarket CLOB  ───▶│     │                                          │
                        │     ▼                                          │
   News API ──┐         │  Edge engine ◀── ML model (calibrated GBM)     │
   Reddit ────┼────────▶│     │        ◀── Claude analysis (Anthropic)   │
   X/Twitter ─┘         │     ▼                                          │
   CoinGecko/Binance ──▶│  Signals + Arbitrage ──▶ Risk manager          │
   (reference data)     │                              │                 │
                        │                              ▼                 │
                        │  Telegram alerts ◀── Execution engine ──▶ CLOB │
                        └───────┬───────────────────────┬────────────────┘
                                │ Redis pub/sub         │ SQLAlchemy (async)
                                ▼                       ▼
                        ┌──────────────┐        ┌──────────────┐
                        │    Redis     │        │  PostgreSQL  │
                        └──────┬───────┘        └──────┬───────┘
                               │                       │
                        ┌──────┴───────────────────────┴───────┐
                        │            FASTAPI (REST + WS)       │
                        └──────────────────┬───────────────────┘
                                           │ HTTP / WebSocket
                                  ┌────────┴────────┐
                                  │ Next.js dashboard│
                                  └─────────────────┘
```

Full details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/API.md](docs/API.md) · [docs/DATABASE.md](docs/DATABASE.md) · [docs/ROADMAP.md](docs/ROADMAP.md)

## Quickstart (Docker)

```bash
git clone <this repo> && cd BOT
cp .env.example .env          # fill in keys you have (all optional to boot)
docker compose up --build -d

# optional: load synthetic demo data so the dashboard isn't empty
docker compose exec api python -m scripts.seed_demo
```

- Dashboard: http://localhost:3000
- API docs (Swagger): http://localhost:8000/docs
- Health: http://localhost:8000/health

The worker container immediately starts scanning real Polymarket markets (public APIs, no keys needed). Within 2–3 scan cycles you'll see markets, snapshots, anomalies, and signals appear.

## Manual installation (development)

Requirements: Python 3.11+, Node 20+, PostgreSQL 16, Redis 7 (Redis optional — the app degrades gracefully without it).

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example ../.env                # edit DATABASE_URL etc.
python -m scripts.init_db
uvicorn app.main:app --reload --port 8000  # terminal 1: API
python -m app.workers.runner               # terminal 2: workers

# frontend
cd ../frontend
npm install
npm run dev                                # terminal 3: dashboard on :3000

# tests
cd ../backend && python -m pytest -q       # 120 tests, no network needed
```

Tip: set `RUN_WORKERS_IN_APP=true` to run the worker loops inside the API process (single-terminal dev).

## Configuration

Everything is environment-driven — see [.env.example](.env.example) for the complete annotated list. The keys that unlock features:

| Variable | Unlocks |
|---|---|
| `ANTHROPIC_API_KEY` | Claude AI analysis engine (`ANTHROPIC_MODEL` defaults to `claude-opus-4-8`) |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram alerting |
| `NEWSAPI_KEY` | News headlines in AI context |
| `TWITTER_BEARER_TOKEN` | X/Twitter sentiment in AI context |
| `POLYMARKET_PRIVATE_KEY` (+ `pip install py-clob-client`) | Live order routing (`TRADING_MODE=live`) |

Risk knobs (`MAX_RISK_PER_TRADE_PCT`, `MAX_DRAWDOWN_PCT`, `KELLY_FRACTION`, `MIN_EDGE_SCORE_TO_TRADE`, …) are all in `.env.example` with safe defaults. **The system never risks more than `MAX_RISK_PER_TRADE_PCT` of equity on a single trade**, and a tripped drawdown circuit breaker halts trading until manually reset (`POST /api/v1/risk/reset-circuit-breaker`).

## Going live (deliberately manual)

1. Run in paper mode until the pipeline, calibration report (`/api/v1/analytics/calibration`), and backtests look sane *to you*.
2. `pip install py-clob-client` in the backend image/venv.
3. Set `TRADING_MODE=live`, `POLYMARKET_PRIVATE_KEY`, and (if using a Polymarket proxy wallet) `POLYMARKET_PROXY_ADDRESS`.
4. Keep `AUTO_TRADE_ENABLED=false` first — execute manually via `POST /api/v1/trades` while you trust-build.
5. Only then flip `AUTO_TRADE_ENABLED=true`, with small `STARTING_BANKROLL`-relative limits.

## Project structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app (REST + WebSocket)
│   │   ├── config.py          # pydantic-settings (all env vars)
│   │   ├── db/                # async SQLAlchemy models + repositories
│   │   ├── datasources/       # Polymarket Gamma/CLOB, CoinGecko, Binance, News, Reddit, X, Trends
│   │   ├── scanner/           # market scanner + anomaly detection
│   │   ├── edge/              # edge engine + arbitrage (pure, unit-tested)
│   │   ├── ai/                # Claude engine, prompts, schemas, context gathering
│   │   ├── risk/              # Kelly sizing + risk manager
│   │   ├── execution/         # broker abstraction, paper + live brokers, engine
│   │   ├── alerts/            # Telegram + alert rules/cooldowns
│   │   ├── graph/             # market relationship graph + cascade simulation
│   │   ├── ml/                # features, calibrated model, evaluation
│   │   ├── backtest/          # event-driven backtester, metrics, strategies
│   │   ├── api/               # routers + WebSocket feed
│   │   └── workers/           # orchestrator loops + standalone runner
│   ├── scripts/               # init_db, seed_demo
│   └── tests/                 # unit + integration (pytest, in-memory DB)
├── frontend/                  # Next.js 14 + TS + Tailwind + Recharts dashboard
├── docs/                      # architecture, API, database schema, roadmap
├── docker-compose.yml         # postgres + redis + api + worker + frontend
└── .env.example
```

## License & attribution

Internal/portfolio project. Polymarket, Anthropic, NewsAPI, Reddit, X, CoinGecko, and Binance are subject to their own terms of service and rate limits — respect them.
