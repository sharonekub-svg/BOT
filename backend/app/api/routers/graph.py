"""Relationship graph API: edges, hidden correlations, cascade simulation."""

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repositories as repo
from app.db.base import get_session
from app.graph.relationships import simulate_cascade

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


async def _load_graph(session: AsyncSession) -> nx.Graph:
    graph = nx.Graph()
    for edge in await repo.relationships(session):
        graph.add_edge(
            edge.market_a,
            edge.market_b,
            kind=edge.kind,
            coefficient=edge.coefficient,
            confidence=edge.confidence,
        )
    return graph


@router.get("")
async def get_graph(session: AsyncSession = Depends(get_session), limit: int = Query(500, le=5000)):
    edges = await repo.relationships(session, limit=limit)
    market_ids = {e.market_a for e in edges} | {e.market_b for e in edges}
    questions: dict[str, str] = {}
    for market_id in list(market_ids)[:1000]:
        market = await repo.get_market(session, market_id)
        if market:
            questions[market_id] = market.question
    return {
        "nodes": [{"id": mid, "question": questions.get(mid, mid)} for mid in market_ids],
        "edges": [
            {
                "source": e.market_a,
                "target": e.market_b,
                "kind": e.kind,
                "coefficient": e.coefficient,
                "confidence": e.confidence,
            }
            for e in edges
        ],
    }


@router.get("/correlations")
async def hidden_correlations(session: AsyncSession = Depends(get_session)):
    """Strong correlations between markets NOT in the same event — the
    non-obvious links worth investigating for lead/lag trades."""
    edges = await repo.relationships(session)
    hidden = [
        e for e in edges
        if e.kind in ("correlated", "anti_correlated") and abs(e.coefficient) >= 0.7
    ]
    hidden.sort(key=lambda e: -abs(e.coefficient))
    out = []
    for e in hidden[:50]:
        market_a = await repo.get_market(session, e.market_a)
        market_b = await repo.get_market(session, e.market_b)
        out.append(
            {
                "market_a": e.market_a,
                "question_a": market_a.question if market_a else e.market_a,
                "market_b": e.market_b,
                "question_b": market_b.question if market_b else e.market_b,
                "kind": e.kind,
                "coefficient": e.coefficient,
            }
        )
    return {"correlations": out}


@router.get("/cascade/{market_id}")
async def cascade(
    market_id: str,
    shock: float = Query(0.1, ge=-1, le=1),
    session: AsyncSession = Depends(get_session),
):
    graph = await _load_graph(session)
    if market_id not in graph:
        raise HTTPException(404, "market not in relationship graph (graph may not be built yet)")
    effects = simulate_cascade(graph, market_id, shock)
    enriched = []
    for effect in effects[:50]:
        market = await repo.get_market(session, effect["market_id"])
        enriched.append({**effect, "question": market.question if market else effect["market_id"]})
    return {"origin": market_id, "shock": shock, "effects": enriched}
