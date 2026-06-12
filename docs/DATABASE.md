# Database Schema

PostgreSQL in production (async SQLAlchemy / asyncpg); the same models run on SQLite for tests. Tables are created by `scripts/init_db.py` / app startup (`Base.metadata.create_all`). For schema evolution beyond v1, introduce Alembic (see ROADMAP).

## Entity overview

```
markets 1───* market_snapshots          (price/liquidity/volume history)
markets 1───* market_events             (anomalies)
markets 1───* signals                   (edge-engine output)
markets 1───* ai_analyses               (Claude output)
markets 1───* trades *───1 signals      (optional link)
markets 1───* positions
markets 1───* ml_predictions            (AI vs ML vs market vs outcome)
markets *───* markets via market_relationships (graph edges)
portfolio_snapshots                     (equity curve)
arbitrage_opportunities                 (multi-market: ids in JSON)
backtest_runs · ml_models · news_items
```

## Tables

### `markets`
PK `id` = Polymarket `conditionId` (string). One row per binary market.

| Column | Type | Notes |
|---|---|---|
| id | varchar(80) PK | conditionId |
| gamma_id, slug, category, event_id, event_title | varchar/text | Gamma metadata; `event_id` groups multi-outcome events |
| question | text | |
| neg_risk | bool | true for mutually-exclusive event outcomes |
| outcomes, clob_token_ids | JSON | `["Yes","No"]`, `[yes_token, no_token]` |
| end_date | timestamptz | resolution deadline |
| active, closed | bool | scan state |
| resolved_outcome | varchar(40) | "Yes"/"No" once resolved |
| yes_price, best_bid, best_ask, spread | float | latest quote (denormalized for ranking queries) |
| liquidity, volume_24h, volume_total, one_day_change | float | |
| created_at, updated_at | timestamptz | server defaults |

### `market_snapshots`
Append-only history; index `(market_id, ts)`. Columns: `market_id` FK, `ts`, `yes_price`, `best_bid`, `best_ask`, `spread`, `liquidity`, `volume_24h`. Pruned past `SNAPSHOT_RETENTION_DAYS`.

### `market_events`
Anomalies. `kind ∈ {price_jump, volume_spike, liquidity_drop}`, `severity` 0–1, `payload` JSON (z-score / ratios).

### `signals`
Edge-engine output. `source ∈ {edge_engine, ai, arbitrage}`, `direction ∈ {buy_yes, buy_no}`, `edge_score` 0–100 (indexed), `implied_prob`, `fair_prob`, `expected_value` (ROI), `kelly_size` (bankroll fraction), `confidence`, `rationale` text, `components` JSON, `status ∈ {active, executed, expired, dismissed}`. The previous active signal for a market is expired on every edge cycle.

### `ai_analyses`
One row per Claude call: `model`, `probability_estimate`, `confidence`, `signal ∈ {bullish, bearish, neutral}`, `reasoning`, `key_factors` JSON, `contradictions` JSON, `news_sentiment`/`social_sentiment` (−1..1), `sources_considered` JSON, `input_tokens`/`output_tokens` (cost tracking).

### `trades`
`mode ∈ {paper, live}`, `side ∈ {buy, sell}`, `outcome ∈ {YES, NO}`, `order_type ∈ {market, limit}`, `qty`, `limit_price`, `fill_price`, `notional`, `fee`, `status ∈ {pending, open, filled, cancelled, rejected}`, `order_id` (broker), `reason ∈ {entry, stop_loss, hedge, rebalance, manual, manual_close, close}`, `signal_id` FK nullable.

### `positions`
One open row per (market, outcome): `qty`, `avg_price` (re-averaged on buys), `realized_pnl` (accumulated on sells), `status ∈ {open, closed}`, `opened_at`, `closed_at`, optional `stop_loss_price`.

### `portfolio_snapshots`
Equity curve: `ts`, `equity`, `cash`, `exposure`, `unrealized_pnl`, `realized_pnl_today`, `peak_equity`, `drawdown` (fraction), `open_positions`. Written by the risk loop (30s) and on every fill.

### `arbitrage_opportunities`
`kind ∈ {binary_complement, multi_outcome_long, multi_outcome_short, cross_market}`, `market_ids` JSON, `legs` JSON (`[{market_id, question, outcome, side, price}]`), `gross_edge`/`net_edge` per $1 basket, `size_cap`, `status ∈ {active, expired}` (all actives expired and re-detected each scan).

### `market_relationships`
Graph edges, fully replaced on each graph rebuild: `market_a`, `market_b`, `kind ∈ {same_event, correlated, anti_correlated}`, `coefficient` (−1..1), `confidence`, `updated_at`. Index `(market_a, market_b)`.

### `ml_predictions`
Calibration ledger: `model_name`, `model_prob`, `ai_prob`, `market_prob`, `outcome` (1/0/null until resolution — labeled by the scanner's resolution detector).

### `ml_models`
Registry: `name`, `version` (monotonic), `trained_at`, `n_samples`, `metrics` JSON (brier, log_loss, baseline_brier), `path` (joblib artifact).

### `backtest_runs`
`name`, `strategy`, `params` JSON, `status`, `metrics` JSON (sharpe/sortino/max_drawdown/cagr/win_rate/profit_factor/ev_accuracy), `equity_curve` JSON (`[[iso_ts, equity], …]`, capped at 2000 points).

### `news_items`
Archived headlines fetched for AI context: `source`, `title`, `url`, `published_at`, `fetched_at`, `summary`, `matched_market_ids` JSON.
