# Architecture

## Processes

The platform runs as two long-lived processes plus the dashboard:

| Process | Entry | Responsibility |
|---|---|---|
| **API** | `uvicorn app.main:app` | REST + WebSocket. Read-mostly; manual trades and backtests are the only writes it initiates. |
| **Worker** | `python -m app.workers.runner` | All pipelines: scan → edge → arbitrage → AI → risk → execution → alerts, plus graph/ML/housekeeping. |
| **Dashboard** | `next start` | Pure client of the API. |

For development the worker can be embedded in the API process (`RUN_WORKERS_IN_APP=true`).

Inter-process events flow through **Redis pub/sub** (`polymarket_edge:feed`); within a process they flow through the in-process `EventBus`. The API's WebSocket manager subscribes to both and dedupes, so the live feed works in every topology. If Redis is down, everything still functions — caching no-ops and the feed only carries in-process events.

## Worker loops (orchestrator)

| Loop | Interval | What it does |
|---|---|---|
| `scan` | `SCAN_INTERVAL_SECONDS` (60s) | Gamma pagination → CLOB books (top-N) → upsert markets → append snapshots → anomaly detection → resolution detection → **edge cycle** → **arbitrage cycle** |
| `ai` | 5× scan interval | Picks the most interesting markets (volume, movement, liquidity, not analyzed within cooldown), gathers news/Reddit/X context, calls Claude, stores `AIAnalysis` + `PredictionRecord`, alerts on high conviction |
| `risk` | 30s | Portfolio snapshot, stop-losses, auto-hedges, circuit-breaker evaluation, risk alerts |
| `trade` | scan interval | When `AUTO_TRADE_ENABLED`: executes top signals through the risk gate, marks them `executed`, rebalances oversized markets |
| `graph` | `GRAPH_REFRESH_MINUTES` (60m) | Rebuilds the relationship graph from 72h of 10-minute-bucketed prices |
| `ml` | `ML_RETRAIN_HOURS` (24h) | Trains the calibrated GBM on resolved-market history when ≥ `ML_MIN_TRAINING_SAMPLES` |
| `housekeeping` | 6h | Prunes snapshots beyond retention, deletes stale expired signals |

Every loop catches and logs its own exceptions — one failing cycle never kills the worker.

## Edge score

`evaluate_market()` produces a 0–100 composite from six bounded components:

| Component | Weight | Saturation |
|---|---|---|
| Mispricing (\|fair − implied\|) | 0.28 | 15 percentage points |
| Expected value (ROI at executable price) | 0.20 | 30% ROI |
| Ensemble confidence (agreement-boosted) | 0.24 | — |
| Liquidity (log-scaled) | 0.14 | $100k |
| Time-to-resolution sweet spot (1–60 days) | 0.08 | — |
| Anomaly severity | 0.06 | — |

Fair probability is a confidence-weighted average where the market's implied price is the anchor (weight 1.0) and AI/ML estimates pull it away in proportion to their confidence. With no estimates and no anomaly, the score is capped at 25 — the engine refuses to call "edge" on price alone.

Direction picks the executable side: `buy_yes` at the YES ask when fair > implied, otherwise `buy_no` at `1 − bid`. Kelly is computed for that side and later multiplied by `KELLY_FRACTION` and capped by `MAX_RISK_PER_TRADE_PCT` in the sizing layer.

## Risk gate (order of checks)

1. Circuit breaker (max drawdown breached) → reject everything until manual reset
2. Daily loss limit → reject entries for the rest of the day
3. Edge score ≥ `MIN_EDGE_SCORE_TO_TRADE`
4. Liquidity ≥ `MIN_LIQUIDITY_TO_TRADE`
5. Open positions < `MAX_OPEN_POSITIONS`
6. Size = min(fractional Kelly, per-trade %, 5% of pool liquidity)
7. Clamp to remaining per-market / per-category / total exposure room and cash

## AI engine design

- **Stable system prompt** (no timestamps/market data) sent with `cache_control: ephemeral` → cacheable prefix; all volatile context lives in the user turn.
- **Structured output** enforced server-side via `output_config.format` (strict JSON schema: `additionalProperties: false`, all fields required, no numeric range constraints — ranges are clamped client-side by Pydantic).
- **Adaptive thinking** on; no sampling parameters (the default model rejects them).
- Refusals (`stop_reason == "refusal"`) and API errors degrade to "no estimate" — the edge engine then runs market+ML only.
- Concurrency bounded by a semaphore; spend bounded by `AI_MAX_ANALYSES_PER_CYCLE` and a per-market cooldown.

## Relationship graph

Nodes are markets. Edges:

- `same_event` (coefficient −1): structural, from Gamma event grouping — one outcome rising implies siblings falling.
- `correlated` / `anti_correlated`: Pearson correlation of aligned 10-minute price *returns* (≥ 12 aligned points, |ρ| ≥ 0.6), bounded to the top-300 markets by volume to keep O(n²) tractable.

Uses: hidden-correlation discovery (`/api/v1/graph/correlations` filters out same-event pairs), cross-market arb candidates, and cascade simulation (`/api/v1/graph/cascade/{id}`) which BFS-propagates a probability shock with damping 0.6 up to depth 3.

## Failure model

| Dependency | Behavior when down |
|---|---|
| Gamma/CLOB | Scan logs a warning, returns empty; next cycle retries (exponential backoff inside the HTTP client) |
| Redis | Cache no-ops, alert cooldowns fall back to in-process dedup, feed bridge disabled |
| Anthropic | AI estimates skipped; edge engine runs market+ML only |
| News/Reddit/X | Empty context blocks; Claude is told sources are unavailable |
| Telegram | Alerts logged and dropped |
| Postgres | Hard dependency — workers/API fail loudly (by design: no silent state divergence) |
