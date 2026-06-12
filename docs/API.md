# API Design

Base URL: `http://localhost:8000`. Interactive docs at `/docs` (Swagger) and `/redoc`.
All endpoints are JSON; no auth in the default deployment (bind it behind your own proxy/auth if exposed).

## System

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe |
| GET | `/api/v1/status` | Version, mode flags, Redis connectivity, row counts |

## Markets

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/markets` | List active markets. Query: `search`, `category`, `sort` (`volume_24h`\|`liquidity`\|`one_day_change`\|`end_date`), `limit`, `offset` |
| GET | `/api/v1/markets/heatmap` | Top-N tiles for the heatmap (`limit`) |
| GET | `/api/v1/markets/categories` | Distinct categories |
| GET | `/api/v1/markets/{id}` | Market detail + latest AI analysis |
| GET | `/api/v1/markets/{id}/history` | Snapshot time series (`hours`, default 168) |
| GET | `/api/v1/markets/{id}/anomalies` | Recent detected anomalies |
| GET | `/api/v1/markets/{id}/analyses` | AI analysis history |

## Opportunities

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/opportunities` | Active signals ranked by edge score (`min_edge`, `limit`) |
| GET | `/api/v1/arbitrage` | Live arbitrage opportunities ranked by net edge |

Example opportunity row:

```json
{
  "signal_id": 412, "market_id": "0x6f…", "question": "Will the Fed cut rates…?",
  "direction": "buy_yes", "edge_score": 81.4,
  "implied_prob": 0.55, "fair_prob": 0.64, "expected_value": 0.143,
  "kelly_size": 0.051, "confidence": 0.72, "liquidity": 84210.0,
  "rationale": "fair 0.64 vs implied 0.55; EV +14.3%; estimates: ai=0.66(c0.8), ml=0.61(c0.5)",
  "components": {"mispricing": 0.6, "value": 0.48, "confidence": 0.72, "liquidity": 0.73, "time": 1.0, "anomaly": 0.0}
}
```

## Portfolio & trading

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/portfolio` | Equity, cash, exposure, P&L, drawdown |
| GET | `/api/v1/portfolio/history` | Equity curve points (`hours`) |
| GET | `/api/v1/positions` | Open positions, marked to market |
| POST | `/api/v1/positions/{id}/close` | Market-close a position |
| GET | `/api/v1/trades` | Trade history (`limit`) |
| POST | `/api/v1/trades` | Manual order — body below |
| GET | `/api/v1/risk` | Exposure breakdown, limit utilization, warnings, circuit-breaker state |
| POST | `/api/v1/risk/reset-circuit-breaker` | Manual reset after a max-drawdown halt |

`POST /api/v1/trades` body:

```json
{ "market_id": "0x6f…", "outcome": "YES", "side": "buy",
  "qty": 100, "order_type": "market", "limit_price": null }
```

`order_type: "limit"` requires `limit_price` (0–1). In paper mode limit orders rest in the broker and fill when the book crosses.

## Analytics

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/analytics/performance` | Sharpe, Sortino, max DD, CAGR, win rate, profit factor from live portfolio history |
| GET | `/api/v1/analytics/calibration` | Brier scores: ML vs AI vs market vs outcomes + reliability buckets |
| POST | `/api/v1/analytics/backtests` | Run a backtest over stored resolved-market history |
| GET | `/api/v1/analytics/backtests` | Past runs |
| GET | `/api/v1/analytics/backtests/{id}` | Full result incl. equity curve |

`POST /api/v1/analytics/backtests` body (all optional):

```json
{ "name": "fade-test", "strategy": "mean_reversion",
  "starting_bankroll": 10000, "kelly_multiplier": 0.25,
  "max_risk_pct": 2.0, "fee_rate": 0.0, "max_markets": 500 }
```

Strategies shipped: `mean_reversion`, `longshot_fade` (add more in `app/backtest/strategies.py`).

## Relationship graph

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/graph` | Nodes + edges of the relationship graph |
| GET | `/api/v1/graph/correlations` | Hidden correlations (strong, non-same-event pairs) |
| GET | `/api/v1/graph/cascade/{market_id}?shock=0.1` | Simulated probability cascade from a shock |

## WebSocket

`ws://localhost:8000/ws/feed` — server pushes JSON events:

```json
{ "type": "ai_analysis", "ts": "2026-06-12T10:21:08+00:00",
  "data": { "market_id": "0x6f…", "prob": 0.64, "confidence": 0.72, "signal": "bullish" } }
```

Event types: `scan_complete`, `anomaly`, `signals_updated`, `arbitrage_found`, `ai_analysis`, `trade`, `portfolio`, `protections`, `graph_updated`. Clients may send `"ping"` and receive `{"type": "pong"}`.
