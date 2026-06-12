"""Worker orchestration — the live trading pipeline.

Loops (independent asyncio tasks, each survives its own failures):

scan loop   (SCAN_INTERVAL_SECONDS)  scanner -> edge engine -> arbitrage -> alerts
ai loop     (SCAN_INTERVAL_SECONDS*5) AI analysis on the most interesting markets
risk loop   (30s)                     portfolio snapshot, stops/hedges, risk alerts
trade loop  (SCAN_INTERVAL_SECONDS)  executes approved signals when AUTO_TRADE_ENABLED
graph loop  (GRAPH_REFRESH_MINUTES)  rebuilds the market relationship graph
ml loop     (ML_RETRAIN_HOURS)       retrains the outcome model, labels predictions
"""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.ai.claude_engine import get_claude_engine
from app.ai.sentiment import ContextGatherer, summarize_price_history
from app.alerts.dispatcher import AlertDispatcher
from app.config import get_settings
from app.core.events import get_event_bus
from app.core.utils import as_utc, hours_until, now_utc
from app.db import repositories as repo
from app.db.base import session_scope
from app.db.models import AIAnalysis, ArbitrageOpportunity, Market, MarketSnapshot, PredictionRecord, Signal
from app.edge.arbitrage import binary_complement_arb, group_event_outcomes, multi_outcome_arb
from app.edge.engine import FairEstimate, MarketState, evaluate_market
from app.execution.engine import ExecutionEngine
from app.graph.relationships import build_graph, graph_edges_as_records
from app.logging_config import get_logger
from app.ml.models import get_outcome_model
from app.scanner.scanner import MarketScanner
from app.workers import pipeline_helpers as helpers

log = get_logger(__name__)


class Orchestrator:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.scanner = MarketScanner()
        self.execution = ExecutionEngine()
        self.alerts = AlertDispatcher()
        self.claude = get_claude_engine()
        self.context = ContextGatherer()
        self.model = get_outcome_model()
        self._stop = asyncio.Event()
        self._anomaly_severity: dict[str, float] = {}

    # ------------------------------------------------------------ lifecycle

    async def run(self) -> None:
        log.info("orchestrator starting (mode=%s, auto_trade=%s, ai=%s)",
                 self.settings.trading_mode, self.settings.auto_trade_enabled,
                 self.claude.enabled)
        tasks = [
            asyncio.create_task(self._loop("scan", self._scan_cycle, self.settings.scan_interval_seconds)),
            asyncio.create_task(self._loop("ai", self._ai_cycle, self.settings.scan_interval_seconds * 5)),
            asyncio.create_task(self._loop("risk", self._risk_cycle, 30)),
            asyncio.create_task(self._loop("trade", self._trade_cycle, self.settings.scan_interval_seconds)),
            asyncio.create_task(self._loop("graph", self._graph_cycle, self.settings.graph_refresh_minutes * 60)),
            asyncio.create_task(self._loop("ml", self._ml_cycle, self.settings.ml_retrain_hours * 3600)),
            asyncio.create_task(self._loop("housekeeping", self._housekeeping_cycle, 6 * 3600)),
        ]
        await self._stop.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.scanner.close()
        await self.context.close()
        log.info("orchestrator stopped")

    def stop(self) -> None:
        self._stop.set()

    async def _loop(self, name: str, fn, interval: float) -> None:
        while not self._stop.is_set():
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("%s cycle failed", name)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------ scan + edge

    async def _scan_cycle(self) -> None:
        result = await self.scanner.scan_once()
        if result.markets_seen == 0:
            return
        self._anomaly_severity = {a.market_id: max(a.severity, self._anomaly_severity.get(a.market_id, 0))
                                  for a in result.anomalies} or {}
        await self._edge_cycle()
        await self._arbitrage_cycle()
        await self._label_resolved(result.resolved)

    async def _edge_cycle(self) -> None:
        published = 0
        async with session_scope() as session:
            markets = await repo.list_active_markets(session)
            for market in markets:
                if market.yes_price is None:
                    continue
                estimates = await self._estimates_for(session, market)
                state = MarketState(
                    market_id=market.id,
                    implied_prob=market.yes_price,
                    best_bid=market.best_bid,
                    best_ask=market.best_ask,
                    liquidity=market.liquidity or 0.0,
                    volume_24h=market.volume_24h or 0.0,
                    hours_to_resolution=hours_until(market.end_date),
                    anomaly_severity=self._anomaly_severity.get(market.id, 0.0),
                    category=market.category,
                )
                result = evaluate_market(
                    state, estimates,
                    fee_rate=self.settings.fee_rate,
                    spread_buffer=self.settings.spread_buffer,
                )
                await repo.expire_active_signals(session, market.id)
                if result.direction == "none" or result.edge_score < 20:
                    continue
                await repo.insert_signal(
                    session,
                    market_id=market.id,
                    ts=now_utc(),
                    source="edge_engine",
                    direction=result.direction,
                    edge_score=result.edge_score,
                    implied_prob=result.implied_prob,
                    fair_prob=result.fair_prob,
                    expected_value=result.expected_value,
                    kelly_size=result.kelly_fraction,
                    confidence=result.confidence,
                    rationale=helpers.signal_rationale(result, estimates),
                    components=result.components,
                )
                published += 1
                if result.edge_score >= self.settings.edge_alert_threshold:
                    await self.alerts.high_edge(
                        market.question, market.id, result.edge_score, result.direction,
                        result.expected_value, result.fair_prob, result.implied_prob,
                    )
                # 24h move alert
                if market.one_day_change is not None and market.yes_price is not None:
                    await self.alerts.big_move(
                        market.question, market.id, market.one_day_change, market.yes_price
                    )
        await get_event_bus().publish("signals_updated", {"count": published})

    async def _estimates_for(self, session, market: Market) -> list[FairEstimate]:
        estimates: list[FairEstimate] = []

        analysis = await repo.latest_analysis(session, market.id)
        if analysis is not None:
            age_hours = (now_utc() - as_utc(analysis.ts)).total_seconds() / 3600
            if age_hours < 24:
                decay = max(0.3, 1.0 - age_hours / 24)
                estimates.append(FairEstimate("ai", analysis.probability_estimate,
                                              analysis.confidence * decay))

        if self.settings.ml_enabled and self.model.available:
            features = await helpers.features_for_market(session, market)
            if features is not None:
                prob = self.model.predict_proba(features)
                if prob is not None:
                    estimates.append(FairEstimate("ml", prob, 0.5))
        return estimates

    # ------------------------------------------------------------ arbitrage

    async def _arbitrage_cycle(self) -> None:
        found = 0
        async with session_scope() as session:
            await repo.expire_arbitrage(session)
            markets = await repo.list_active_markets(session)

            entries = []
            for market in markets:
                ask_yes = market.best_ask
                bid_yes = market.best_bid
                ask_no = 1.0 - bid_yes if bid_yes is not None else None
                arb = binary_complement_arb(
                    market.id, market.question, ask_yes, ask_no,
                    fee_rate=self.settings.fee_rate, buffer=self.settings.spread_buffer,
                )
                if arb is not None:
                    session.add(ArbitrageOpportunity(
                        ts=now_utc(), kind=arb.kind, market_ids=arb.market_ids,
                        legs=[vars(leg) for leg in arb.legs], gross_edge=arb.gross_edge,
                        net_edge=arb.net_edge, size_cap=arb.size_cap, description=arb.description,
                    ))
                    await self.alerts.arbitrage(arb.kind, arb.description, arb.net_edge, arb.market_ids)
                    found += 1
                entries.append({
                    "market_id": market.id, "question": market.question,
                    "event_id": market.event_id, "neg_risk": market.neg_risk,
                    "ask": market.best_ask, "bid": market.best_bid,
                })

            for group in group_event_outcomes(entries):
                for arb in multi_outcome_arb(group.event_id, group.markets,
                                             fee_rate=self.settings.fee_rate,
                                             buffer=self.settings.spread_buffer):
                    session.add(ArbitrageOpportunity(
                        ts=now_utc(), kind=arb.kind, market_ids=arb.market_ids,
                        legs=[vars(leg) for leg in arb.legs], gross_edge=arb.gross_edge,
                        net_edge=arb.net_edge, size_cap=arb.size_cap, description=arb.description,
                    ))
                    await self.alerts.arbitrage(arb.kind, arb.description, arb.net_edge, arb.market_ids)
                    found += 1
        if found:
            await get_event_bus().publish("arbitrage_found", {"count": found})

    # ------------------------------------------------------------ AI

    async def _ai_cycle(self) -> None:
        if not self.claude.enabled:
            return
        async with session_scope() as session:
            candidates = await helpers.ai_candidates(
                session,
                limit=self.settings.ai_max_analyses_per_cycle,
                cooldown_minutes=self.settings.ai_analysis_cooldown_minutes,
            )
        for market in candidates:
            try:
                await self._analyze_one(market)
            except Exception:
                log.exception("ai analysis failed for %s", market.id)

    async def _analyze_one(self, market: Market) -> None:
        async with session_scope() as session:
            snaps = await repo.recent_snapshots(session, market.id, limit=48)
        history = [(s.ts.isoformat(), s.yes_price) for s in snaps if s.yes_price is not None]
        context = await self.context.gather(market.id, market.question)

        result = await self.claude.analyze_market(
            question=market.question,
            description=market.event_title,
            category=market.category,
            end_date_iso=market.end_date.isoformat() if market.end_date else None,
            implied_prob=market.yes_price,
            price_history_summary=summarize_price_history(history),
            news_block=context["news"],
            reddit_block=context["reddit"],
            twitter_block=context["twitter"],
        )
        if result is None:
            return
        analysis, usage = result

        async with session_scope() as session:
            session.add(AIAnalysis(
                market_id=market.id,
                ts=now_utc(),
                model=usage.get("model") or self.settings.anthropic_model,
                probability_estimate=analysis.probability_estimate,
                confidence=analysis.confidence,
                signal=analysis.signal,
                reasoning=analysis.reasoning,
                key_factors=analysis.key_factors,
                contradictions=analysis.contradictions,
                news_sentiment=analysis.news_sentiment,
                social_sentiment=analysis.social_sentiment,
                sources_considered=analysis.sources_considered,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            ))
            # Track the prediction for later calibration scoring.
            session.add(PredictionRecord(
                market_id=market.id,
                ts=now_utc(),
                model_name="claude",
                model_prob=None,
                ai_prob=analysis.probability_estimate,
                market_prob=market.yes_price,
            ))

        await get_event_bus().publish("ai_analysis", {
            "market_id": market.id, "question": market.question[:80],
            "prob": analysis.probability_estimate, "confidence": analysis.confidence,
            "signal": analysis.signal,
        })
        await self.alerts.ai_conviction(
            market.question, market.id, analysis.signal, analysis.confidence,
            analysis.probability_estimate, market.yes_price or 0.5, analysis.reasoning,
        )

    # ------------------------------------------------------------ risk + trading

    async def _risk_cycle(self) -> None:
        snap = await self.execution.snapshot_portfolio()
        async with session_scope() as session:
            state = await self.execution.portfolio_state(session)
        warnings = self.execution.risk.check_portfolio_health(state)
        if warnings:
            await self.alerts.risk_warning(warnings)
        await self.execution.run_protections()
        await get_event_bus().publish("portfolio", {
            "equity": snap.equity, "cash": snap.cash, "exposure": snap.exposure,
            "drawdown": snap.drawdown, "open_positions": snap.open_positions,
        })

    async def _trade_cycle(self) -> None:
        if not self.settings.auto_trade_enabled:
            return
        async with session_scope() as session:
            ranked = await repo.top_signals(
                session, limit=10, min_edge=self.settings.min_edge_score_to_trade
            )
        for signal, market in ranked:
            existing_yes = None
            async with session_scope() as session:
                outcome = "YES" if signal.direction == "buy_yes" else "NO"
                existing_yes = await repo.position_for(session, market.id, outcome)
            if existing_yes is not None:
                continue  # already positioned this way
            trade = await self.execution.execute_signal(signal, market)
            if trade is not None and trade.status == "filled":
                async with session_scope() as session:
                    db_signal = await session.get(Signal, signal.id)
                    if db_signal is not None:
                        db_signal.status = "executed"
        await self.execution.rebalance()

    # ------------------------------------------------------------ graph

    async def _graph_cycle(self) -> None:
        async with session_scope() as session:
            inputs = await helpers.series_inputs(session, max_markets=300)
            graph = build_graph(inputs)
            records = graph_edges_as_records(graph)
            await repo.replace_relationships(session, records)
        log.info("relationship graph rebuilt: %d nodes / %d edges", len(inputs), len(records))
        await get_event_bus().publish("graph_updated", {"nodes": len(inputs), "edges": len(records)})

    # ------------------------------------------------------------ ML

    async def _ml_cycle(self) -> None:
        if not self.settings.ml_enabled:
            return
        async with session_scope() as session:
            X, y = await helpers.training_matrix(session)
        if X is None or len(X) < self.settings.ml_min_training_samples:
            log.info("ml: not enough resolved history to train (%s samples)",
                     0 if X is None else len(X))
            return
        try:
            report = self.model.train(X, y)
        except ValueError as exc:
            log.info("ml training skipped: %s", exc)
            return
        async with session_scope() as session:
            await helpers.record_model(session, report)

    async def _label_resolved(self, resolved_ids: list[str]) -> None:
        """Fill outcome labels on prediction records when markets resolve."""
        if not resolved_ids:
            return
        async with session_scope() as session:
            for market_id in resolved_ids:
                market = await repo.get_market(session, market_id)
                if market is None or market.resolved_outcome is None:
                    continue
                outcome = 1 if market.resolved_outcome == "Yes" else 0
                rows = await session.execute(
                    select(PredictionRecord).where(
                        PredictionRecord.market_id == market_id,
                        PredictionRecord.outcome.is_(None),
                    )
                )
                for record in rows.scalars():
                    record.outcome = outcome

    # ------------------------------------------------------------ housekeeping

    async def _housekeeping_cycle(self) -> None:
        await self.scanner.prune_history()
        cutoff = now_utc() - timedelta(days=7)
        async with session_scope() as session:
            from sqlalchemy import delete

            await session.execute(
                delete(Signal).where(Signal.status == "expired", Signal.ts < cutoff)
            )
            await session.execute(
                delete(MarketSnapshot).where(MarketSnapshot.ts < now_utc() - timedelta(
                    days=self.settings.snapshot_retention_days))
            )
