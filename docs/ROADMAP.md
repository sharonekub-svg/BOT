# Implementation Roadmap

## Phase 1 — Foundation (shipped in this repo)

- [x] Async FastAPI backend, PostgreSQL (asyncpg), Redis pub/sub bridge, Docker Compose
- [x] Gamma + CLOB scanners with pagination, order-book refresh, snapshot history, retention pruning
- [x] Anomaly detection (price z-score, volume ratio, liquidity collapse)
- [x] Edge engine (ensemble fair value, EV, Kelly, 0–100 Edge Score) — pure & unit-tested
- [x] Arbitrage: binary complement, multi-outcome baskets, implication violations
- [x] Claude analysis engine (prompt caching, strict JSON schema, refusal handling, token accounting)
- [x] Context gathering: NewsAPI, Reddit public JSON, X API v2; CoinGecko/Binance reference clients
- [x] Risk manager (per-trade/market/category/total caps, daily-loss halt, drawdown circuit breaker)
- [x] Execution: paper broker (market + resting limit), live CLOB broker scaffold, stops, hedges, rebalance
- [x] Telegram alerts with Redis-backed cooldowns
- [x] Relationship graph + cascade simulation
- [x] ML: calibrated GBM on resolved history; AI/ML/market calibration scoring
- [x] Backtester + full metrics (Sharpe, Sortino, DD, CAGR, win rate, PF, EV accuracy)
- [x] Next.js dark dashboard (KPIs, rankings, positions, allocation, risk, heatmap, live WS feed)
- [x] 120 unit/integration tests, demo data seeder, docs

## Phase 2 — Hardening (recommended next)

- [ ] **Alembic migrations** (replace create_all for schema evolution)
- [ ] Polymarket **CLOB WebSocket** market channel for tick-level updates between scans
- [ ] Persist anomaly detector state (survive worker restarts without warmup)
- [ ] Order lifecycle reconciliation for live mode (poll open orders, partial fills, cancels)
- [ ] AuthN/Z on the API (API keys or OIDC) + rate limiting before any public exposure
- [ ] Prometheus metrics + Grafana dashboards; Sentry error tracking
- [ ] CI pipeline (lint, tests, image build) and staged deploys

## Phase 3 — Alpha expansion

- [ ] Resolution-source watchers (official feeds, oracle data) for event-driven re-analysis
- [ ] Cross-venue comparison (Kalshi, betting exchanges) for inter-venue divergence signals
- [ ] LLM-extracted entity linking → richer event-chain edges in the graph
- [ ] Order-book microstructure features (imbalance, depth slope) in the ML model
- [ ] Maker strategies: passive quoting inside the spread for fee-free venues
- [ ] Walk-forward backtesting + parameter sweeps; strategy registry persisted in DB

## Phase 4 — Scale

- [ ] Split workers into dedicated services (scanner / ai / execution) with a task queue
- [ ] TimescaleDB hypertables for snapshots; columnar analytics store for research
- [ ] Multi-account / multi-bankroll support with per-book risk envelopes
- [ ] Shadow-mode A/B: run candidate models against production signals before promotion
