"""ORM models — see docs/DATABASE.md for the schema reference."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Market(Base):
    """A single Polymarket binary market (one outcome pair). PK = conditionId."""

    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # conditionId
    gamma_id: Mapped[str | None] = mapped_column(String(40), index=True)
    question: Mapped[str] = mapped_column(Text)
    slug: Mapped[str | None] = mapped_column(String(255), index=True)
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    event_id: Mapped[str | None] = mapped_column(String(40), index=True)
    event_title: Mapped[str | None] = mapped_column(Text)
    neg_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    outcomes: Mapped[list | None] = mapped_column(JSON)        # ["Yes", "No"]
    clob_token_ids: Mapped[list | None] = mapped_column(JSON)  # [yes_token, no_token]
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_outcome: Mapped[str | None] = mapped_column(String(40))  # "Yes"/"No" once resolved

    # latest quote/state (denormalized for fast ranking queries)
    yes_price: Mapped[float | None] = mapped_column(Float)
    best_bid: Mapped[float | None] = mapped_column(Float)
    best_ask: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    liquidity: Mapped[float | None] = mapped_column(Float)
    volume_24h: Mapped[float | None] = mapped_column(Float)
    volume_total: Mapped[float | None] = mapped_column(Float)
    one_day_change: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MarketSnapshot(Base):
    """Time series of market state — the platform's price history store."""

    __tablename__ = "market_snapshots"
    __table_args__ = (Index("ix_snapshots_market_ts", "market_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    yes_price: Mapped[float | None] = mapped_column(Float)
    best_bid: Mapped[float | None] = mapped_column(Float)
    best_ask: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    liquidity: Mapped[float | None] = mapped_column(Float)
    volume_24h: Mapped[float | None] = mapped_column(Float)


class MarketEvent(Base):
    """Detected anomalies: price jumps, volume spikes, liquidity shifts."""

    __tablename__ = "market_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # price_jump | volume_spike | liquidity_drop
    severity: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    payload: Mapped[dict | None] = mapped_column(JSON)


class Signal(Base):
    """A ranked trading opportunity produced by the edge engine."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(30), default="edge_engine")  # edge_engine | ai | arbitrage
    direction: Mapped[str] = mapped_column(String(10))  # buy_yes | buy_no
    edge_score: Mapped[float] = mapped_column(Float, index=True)
    implied_prob: Mapped[float | None] = mapped_column(Float)
    fair_prob: Mapped[float | None] = mapped_column(Float)
    expected_value: Mapped[float | None] = mapped_column(Float)  # ROI per $1 at stake
    kelly_size: Mapped[float | None] = mapped_column(Float)      # fraction of bankroll
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active|executed|expired|dismissed
    components: Mapped[dict | None] = mapped_column(JSON)


class AIAnalysis(Base):
    """Claude's structured read on a market."""

    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    model: Mapped[str] = mapped_column(String(60))
    probability_estimate: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    signal: Mapped[str] = mapped_column(String(10))  # bullish | bearish | neutral
    reasoning: Mapped[str] = mapped_column(Text)
    key_factors: Mapped[list | None] = mapped_column(JSON)
    contradictions: Mapped[list | None] = mapped_column(JSON)
    news_sentiment: Mapped[float | None] = mapped_column(Float)    # -1..1
    social_sentiment: Mapped[float | None] = mapped_column(Float)  # -1..1
    sources_considered: Mapped[list | None] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(60))  # newsapi | reddit | twitter
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    matched_market_ids: Mapped[list | None] = mapped_column(JSON)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"), index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    mode: Mapped[str] = mapped_column(String(10), default="paper")  # paper | live
    side: Mapped[str] = mapped_column(String(6))      # buy | sell
    outcome: Mapped[str] = mapped_column(String(20))  # YES | NO
    order_type: Mapped[str] = mapped_column(String(10), default="market")  # market | limit
    qty: Mapped[float] = mapped_column(Float)          # shares
    limit_price: Mapped[float | None] = mapped_column(Float)
    fill_price: Mapped[float | None] = mapped_column(Float)
    notional: Mapped[float | None] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(15), default="pending", index=True)  # pending|open|filled|cancelled|rejected
    order_id: Mapped[str | None] = mapped_column(String(120))
    reason: Mapped[str | None] = mapped_column(Text)  # entry | stop_loss | hedge | rebalance | manual | close
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(20))  # YES | NO
    qty: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open | closed
    stop_loss_price: Mapped[float | None] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    exposure: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl_today: Mapped[float] = mapped_column(Float, default=0.0)
    peak_equity: Mapped[float] = mapped_column(Float)
    drawdown: Mapped[float] = mapped_column(Float, default=0.0)  # fraction 0..1
    open_positions: Mapped[int] = mapped_column(Integer, default=0)


class ArbitrageOpportunity(Base):
    __tablename__ = "arbitrage_opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # binary_complement | multi_outcome_long | multi_outcome_short | cross_market
    market_ids: Mapped[list] = mapped_column(JSON)
    legs: Mapped[list] = mapped_column(JSON)          # [{market_id, outcome, side, price}]
    gross_edge: Mapped[float] = mapped_column(Float)  # per $1 of basket
    net_edge: Mapped[float] = mapped_column(Float)
    size_cap: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(15), default="active", index=True)
    description: Mapped[str | None] = mapped_column(Text)


class MarketRelationship(Base):
    """Edges of the market relationship graph."""

    __tablename__ = "market_relationships"
    __table_args__ = (Index("ix_rel_pair", "market_a", "market_b"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_a: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    market_b: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    kind: Mapped[str] = mapped_column(String(20), index=True)  # same_event | correlated | anti_correlated
    coefficient: Mapped[float] = mapped_column(Float)          # correlation / strength -1..1
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    name: Mapped[str] = mapped_column(String(120))
    strategy: Mapped[str] = mapped_column(String(60))
    params: Mapped[dict | None] = mapped_column(JSON)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(15), default="completed")
    metrics: Mapped[dict | None] = mapped_column(JSON)
    equity_curve: Mapped[list | None] = mapped_column(JSON)  # [[iso_ts, equity], ...]


class PredictionRecord(Base):
    """Side-by-side record: ML prob vs AI prob vs market prob vs final outcome."""

    __tablename__ = "ml_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    model_name: Mapped[str] = mapped_column(String(60))
    model_prob: Mapped[float | None] = mapped_column(Float)
    ai_prob: Mapped[float | None] = mapped_column(Float)
    market_prob: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[int | None] = mapped_column(Integer)  # 1 = YES, 0 = NO, null = unresolved


class MLModelRecord(Base):
    __tablename__ = "ml_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    n_samples: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    path: Mapped[str] = mapped_column(Text)
