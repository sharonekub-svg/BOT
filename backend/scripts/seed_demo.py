"""Seed synthetic demo data: `python -m scripts.seed_demo`.

Creates realistic-looking markets, 7 days of price history, signals, AI
analyses, arbitrage, trades/positions and portfolio history so the dashboard
and analytics endpoints have content without hitting any external API.
"""

import asyncio
import random
from datetime import timedelta

from app.core.utils import now_utc
from app.db.base import init_db, session_scope
from app.db.models import (
    AIAnalysis,
    ArbitrageOpportunity,
    Market,
    MarketSnapshot,
    PortfolioSnapshot,
    Position,
    PredictionRecord,
    Signal,
    Trade,
)
from app.logging_config import get_logger, setup_logging

log = get_logger(__name__)
random.seed(42)

DEMO_MARKETS = [
    ("Will the Fed cut rates at the next FOMC meeting?", "economics", 0.62),
    ("Will Bitcoin close above $150k this quarter?", "crypto", 0.31),
    ("Will the incumbent win the upcoming election?", "politics", 0.55),
    ("Will SpaceX complete an orbital Starship flight this month?", "science", 0.74),
    ("Will the S&P 500 hit a new all-time high this month?", "economics", 0.47),
    ("Will Ethereum flip $8k before year end?", "crypto", 0.18),
    ("Will the champion repeat at the finals?", "sports", 0.41),
    ("Will a major AI lab release a new frontier model this quarter?", "tech", 0.83),
    ("Will the bill pass the Senate before recess?", "politics", 0.28),
    ("Will global temperatures set a monthly record this summer?", "science", 0.66),
    ("Will the studio's blockbuster gross $1B worldwide?", "culture", 0.52),
    ("Will the team make the playoffs?", "sports", 0.69),
]


def random_walk(start: float, steps: int, vol: float = 0.012) -> list[float]:
    prices = [start]
    for _ in range(steps - 1):
        drift = (0.5 - prices[-1]) * 0.002
        nxt = prices[-1] + random.gauss(drift, vol)
        prices.append(min(max(nxt, 0.02), 0.98))
    return prices


async def seed() -> None:
    now = now_utc()
    steps = 7 * 24  # hourly snapshots, 7 days

    async with session_scope() as session:
        market_rows: list[Market] = []
        for i, (question, category, price) in enumerate(DEMO_MARKETS):
            market_id = f"0xdemo{i:04d}"
            walk = random_walk(price, steps)
            spread = random.uniform(0.005, 0.03)
            liquidity = random.uniform(5_000, 250_000)
            volume = random.uniform(2_000, 400_000)
            market = Market(
                id=market_id,
                gamma_id=str(1000 + i),
                question=question,
                slug=question.lower().replace(" ", "-")[:50],
                category=category,
                event_id=f"ev{i // 3}",
                event_title=f"Demo event {i // 3}",
                neg_risk=(i % 3 == 0),
                outcomes=["Yes", "No"],
                clob_token_ids=[f"tok{i}y", f"tok{i}n"],
                end_date=now + timedelta(days=random.randint(5, 60)),
                active=True,
                closed=False,
                yes_price=walk[-1],
                best_bid=max(walk[-1] - spread / 2, 0.01),
                best_ask=min(walk[-1] + spread / 2, 0.99),
                spread=spread,
                liquidity=liquidity,
                volume_24h=volume,
                volume_total=volume * random.uniform(5, 40),
                one_day_change=walk[-1] - walk[-24],
            )
            session.add(market)
            market_rows.append(market)

            for step, p in enumerate(walk):
                session.add(
                    MarketSnapshot(
                        market_id=market_id,
                        ts=now - timedelta(hours=steps - step),
                        yes_price=p,
                        best_bid=max(p - spread / 2, 0.01),
                        best_ask=min(p + spread / 2, 0.99),
                        spread=spread,
                        liquidity=liquidity * random.uniform(0.9, 1.1),
                        volume_24h=volume * random.uniform(0.7, 1.3),
                    )
                )

        # Resolved markets (for backtests/calibration)
        for i in range(30):
            market_id = f"0xresolved{i:04d}"
            outcome_yes = random.random() < 0.5
            start_price = random.uniform(0.25, 0.75)
            walk = random_walk(start_price, steps)
            # drift toward the outcome near the end
            target = 0.97 if outcome_yes else 0.03
            for j in range(24):
                k = steps - 24 + j
                walk[k] = walk[k] * (1 - j / 24) + target * (j / 24)
            session.add(
                Market(
                    id=market_id,
                    question=f"Resolved demo market #{i}?",
                    category=random.choice(["politics", "crypto", "sports", "economics"]),
                    outcomes=["Yes", "No"],
                    end_date=now - timedelta(days=1),
                    active=False,
                    closed=True,
                    resolved_outcome="Yes" if outcome_yes else "No",
                    yes_price=walk[-1],
                    liquidity=random.uniform(5_000, 80_000),
                    volume_24h=random.uniform(1_000, 60_000),
                )
            )
            for step, p in enumerate(walk):
                session.add(
                    MarketSnapshot(
                        market_id=market_id,
                        ts=now - timedelta(days=8) + timedelta(hours=step),
                        yes_price=p,
                        best_bid=max(p - 0.01, 0.01),
                        best_ask=min(p + 0.01, 0.99),
                        spread=0.02,
                        liquidity=random.uniform(5_000, 80_000),
                        volume_24h=random.uniform(1_000, 60_000),
                    )
                )
            session.add(
                PredictionRecord(
                    market_id=market_id,
                    ts=now - timedelta(days=3),
                    model_name="claude",
                    ai_prob=min(max((0.8 if outcome_yes else 0.2) + random.gauss(0, 0.15), 0.02), 0.98),
                    market_prob=walk[steps // 2],
                    outcome=1 if outcome_yes else 0,
                )
            )

        # Signals + AI analyses on the active markets
        for market in market_rows:
            implied = market.yes_price or 0.5
            fair = min(max(implied + random.gauss(0, 0.08), 0.03), 0.97)
            direction = "buy_yes" if fair > implied else "buy_no"
            edge = min(max(abs(fair - implied) * 400 + random.uniform(5, 25), 10), 96)
            ev = abs(fair - implied) / max(implied, 0.05)
            session.add(
                Signal(
                    market_id=market.id,
                    ts=now - timedelta(minutes=random.randint(1, 50)),
                    source="edge_engine",
                    direction=direction,
                    edge_score=round(edge, 1),
                    implied_prob=round(implied, 3),
                    fair_prob=round(fair, 3),
                    expected_value=round(ev, 3),
                    kelly_size=round(min(ev / 4, 0.1), 4),
                    confidence=round(random.uniform(0.4, 0.9), 2),
                    rationale=f"demo: fair {fair:.2f} vs implied {implied:.2f}",
                    status="active",
                    components={"mispricing": 0.6, "value": 0.5, "confidence": 0.6,
                                "liquidity": 0.7, "time": 1.0, "anomaly": 0.1},
                )
            )
            if random.random() < 0.7:
                signal_dir = "bullish" if fair > implied else "bearish"
                session.add(
                    AIAnalysis(
                        market_id=market.id,
                        ts=now - timedelta(hours=random.randint(1, 12)),
                        model="demo-model",
                        probability_estimate=round(fair, 3),
                        confidence=round(random.uniform(0.5, 0.92), 2),
                        signal=signal_dir,
                        reasoning="Demo analysis: synthetic reasoning summary for dashboard preview. "
                        "Recent reporting and base rates point modestly away from the market price.",
                        key_factors=["recent polling shift", "historical base rate", "liquidity thinning"],
                        contradictions=["one source disputes the timeline"],
                        news_sentiment=round(random.uniform(-0.5, 0.7), 2),
                        social_sentiment=round(random.uniform(-0.6, 0.8), 2),
                        sources_considered=["news", "reddit"],
                        input_tokens=2400,
                        output_tokens=350,
                    )
                )

        # One arbitrage example
        session.add(
            ArbitrageOpportunity(
                ts=now - timedelta(minutes=4),
                kind="binary_complement",
                market_ids=[market_rows[0].id],
                legs=[
                    {"market_id": market_rows[0].id, "question": market_rows[0].question,
                     "outcome": "YES", "side": "buy", "price": 0.48},
                    {"market_id": market_rows[0].id, "question": market_rows[0].question,
                     "outcome": "NO", "side": "buy", "price": 0.50},
                ],
                gross_edge=0.02,
                net_edge=0.013,
                size_cap=2500.0,
                description="YES 0.480 + NO 0.500 = 0.980 < 1.00",
            )
        )

        # Trades, positions, portfolio history
        cash = 10_000.0
        equity = cash
        peak = equity
        for d in range(7 * 24):
            ts = now - timedelta(hours=7 * 24 - d)
            equity = max(equity + random.gauss(2.0, 35.0), 6_000)
            peak = max(peak, equity)
            if d % 6 == 0:
                session.add(
                    PortfolioSnapshot(
                        ts=ts,
                        equity=round(equity, 2),
                        cash=round(equity * 0.55, 2),
                        exposure=round(equity * 0.45, 2),
                        unrealized_pnl=round(random.gauss(0, 80), 2),
                        realized_pnl_today=round(random.gauss(10, 60), 2),
                        peak_equity=round(peak, 2),
                        drawdown=round(max(0.0, 1 - equity / peak), 4),
                        open_positions=random.randint(3, 8),
                    )
                )

        for market in market_rows[:6]:
            outcome = random.choice(["YES", "NO"])
            yes = market.yes_price or 0.5
            entry = yes if outcome == "YES" else 1 - yes
            entry = min(max(entry + random.gauss(0, 0.05), 0.05), 0.95)
            qty = round(random.uniform(50, 400), 0)
            session.add(
                Position(
                    market_id=market.id, outcome=outcome, qty=qty,
                    avg_price=round(entry, 3), status="open",
                    opened_at=now - timedelta(days=random.randint(1, 5)),
                )
            )
            session.add(
                Trade(
                    market_id=market.id, mode="paper", side="buy", outcome=outcome,
                    order_type="market", qty=qty, fill_price=round(entry, 3),
                    notional=round(entry * qty, 2), fee=0.0, status="filled",
                    order_id=f"paper-demo-{market.id}", reason="entry",
                    created_at=now - timedelta(days=random.randint(1, 5)),
                    filled_at=now - timedelta(days=random.randint(1, 5)),
                )
            )

    log.info("demo data seeded: %d active + 30 resolved markets, history, signals, portfolio",
             len(DEMO_MARKETS))


async def main() -> None:
    setup_logging()
    await init_db()
    await seed()


if __name__ == "__main__":
    asyncio.run(main())
