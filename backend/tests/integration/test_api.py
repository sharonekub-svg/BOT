"""API integration tests against the in-memory database (no external services)."""

from datetime import timedelta

import httpx
import pytest

from app.core.utils import now_utc
from app.db.base import get_sessionmaker
from app.db.models import Market, MarketSnapshot, Signal
from app.main import app


@pytest.fixture
async def client(db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def seed_market(market_id: str = "0xtest1", edge: float = 82.0) -> None:
    now = now_utc()
    async with get_sessionmaker()() as session:
        session.add(
            Market(
                id=market_id,
                question="Will the integration test pass?",
                category="tech",
                outcomes=["Yes", "No"],
                end_date=now + timedelta(days=10),
                active=True,
                closed=False,
                yes_price=0.55,
                best_bid=0.54,
                best_ask=0.56,
                spread=0.02,
                liquidity=40_000,
                volume_24h=120_000,
                one_day_change=0.04,
            )
        )
        for i in range(10):
            session.add(
                MarketSnapshot(
                    market_id=market_id,
                    ts=now - timedelta(hours=10 - i),
                    yes_price=0.50 + i * 0.005,
                    best_bid=0.49 + i * 0.005,
                    best_ask=0.51 + i * 0.005,
                    spread=0.02,
                    liquidity=40_000,
                    volume_24h=120_000,
                )
            )
        session.add(
            Signal(
                market_id=market_id,
                ts=now,
                source="edge_engine",
                direction="buy_yes",
                edge_score=edge,
                implied_prob=0.55,
                fair_prob=0.65,
                expected_value=0.16,
                kelly_size=0.05,
                confidence=0.7,
                rationale="test signal",
                status="active",
            )
        )
        await session.commit()


class TestSystem:
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_status_counts(self, client):
        await seed_market()
        resp = await client.get("/api/v1/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["counts"]["markets"] == 1
        assert body["trading_mode"] == "paper"


class TestMarkets:
    async def test_list_and_detail(self, client):
        await seed_market()
        resp = await client.get("/api/v1/markets")
        assert resp.status_code == 200
        markets = resp.json()["markets"]
        assert len(markets) == 1
        assert markets[0]["question"].startswith("Will the integration")

        detail = await client.get(f"/api/v1/markets/{markets[0]['id']}")
        assert detail.status_code == 200
        assert detail.json()["market"]["yes_price"] == 0.55

    async def test_history(self, client):
        await seed_market()
        resp = await client.get("/api/v1/markets/0xtest1/history")
        assert resp.status_code == 200
        points = resp.json()["points"]
        assert len(points) == 10
        assert points[0]["yes_price"] < points[-1]["yes_price"]  # chronological

    async def test_unknown_market_404(self, client):
        resp = await client.get("/api/v1/markets/0xmissing")
        assert resp.status_code == 404

    async def test_search_filter(self, client):
        await seed_market()
        hit = await client.get("/api/v1/markets", params={"search": "integration"})
        miss = await client.get("/api/v1/markets", params={"search": "zzz-no-match"})
        assert len(hit.json()["markets"]) == 1
        assert len(miss.json()["markets"]) == 0

    async def test_heatmap(self, client):
        await seed_market()
        resp = await client.get("/api/v1/markets/heatmap")
        assert resp.status_code == 200
        assert len(resp.json()["tiles"]) == 1


class TestOpportunities:
    async def test_ranked_opportunities(self, client):
        await seed_market(edge=82.0)
        resp = await client.get("/api/v1/opportunities")
        assert resp.status_code == 200
        opportunities = resp.json()["opportunities"]
        assert len(opportunities) == 1
        assert opportunities[0]["edge_score"] == 82.0
        assert opportunities[0]["direction"] == "buy_yes"

    async def test_min_edge_filter(self, client):
        await seed_market(edge=42.0)
        resp = await client.get("/api/v1/opportunities", params={"min_edge": 60})
        assert resp.json()["opportunities"] == []

    async def test_arbitrage_endpoint_empty(self, client):
        resp = await client.get("/api/v1/arbitrage")
        assert resp.status_code == 200
        assert resp.json()["arbitrage"] == []


class TestPortfolioAndTrading:
    async def test_default_portfolio(self, client):
        resp = await client.get("/api/v1/portfolio")
        assert resp.status_code == 200
        body = resp.json()
        assert body["equity"] == body["cash"] == 10_000.0
        assert body["mode"] == "paper"

    async def test_paper_trade_roundtrip(self, client):
        await seed_market()
        # buy
        resp = await client.post(
            "/api/v1/trades",
            json={"market_id": "0xtest1", "outcome": "YES", "side": "buy", "qty": 100},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "filled"
        assert 0.5 < resp.json()["fill_price"] < 0.6

        positions = (await client.get("/api/v1/positions")).json()["positions"]
        assert len(positions) == 1
        assert positions[0]["qty"] == 100

        trades = (await client.get("/api/v1/trades")).json()["trades"]
        assert len(trades) == 1

        # close
        close = await client.post(f"/api/v1/positions/{positions[0]['id']}/close")
        assert close.status_code == 200
        positions_after = (await client.get("/api/v1/positions")).json()["positions"]
        assert positions_after == []

    async def test_trade_unknown_market_rejected(self, client):
        resp = await client.post(
            "/api/v1/trades",
            json={"market_id": "0xmissing", "outcome": "YES", "side": "buy", "qty": 10},
        )
        assert resp.status_code == 400

    async def test_risk_endpoint(self, client):
        resp = await client.get("/api/v1/risk")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limits"]["max_drawdown_pct"] == 15.0
        assert body["circuit_breaker_tripped"] is False


class TestAnalytics:
    async def test_performance_empty(self, client):
        resp = await client.get("/api/v1/analytics/performance")
        assert resp.status_code == 200
        assert "metrics" in resp.json()

    async def test_calibration_empty(self, client):
        resp = await client.get("/api/v1/analytics/calibration")
        assert resp.status_code == 200
        assert resp.json()["n_resolved"] == 0

    async def test_backtest_requires_history(self, client):
        resp = await client.post("/api/v1/analytics/backtests", json={"strategy": "mean_reversion"})
        assert resp.status_code == 400  # no resolved markets seeded

    async def test_backtest_unknown_strategy(self, client):
        resp = await client.post("/api/v1/analytics/backtests", json={"strategy": "nope"})
        assert resp.status_code == 400


class TestGraph:
    async def test_graph_empty(self, client):
        resp = await client.get("/api/v1/graph")
        assert resp.status_code == 200
        assert resp.json()["edges"] == []
