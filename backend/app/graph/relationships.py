"""Market relationship graph.

Edges:
- same_event       — markets under one Gamma event (mutually exclusive outcomes)
- correlated       — |pearson| of aligned price series above threshold
- anti_correlated  — strong negative correlation

Used for: cross-market arbitrage candidates, hidden-correlation discovery,
and cascade simulation (how a shock in one market propagates).
"""

from dataclasses import dataclass

import networkx as nx
import numpy as np

from app.core.utils import now_utc
from app.logging_config import get_logger

log = get_logger(__name__)

MIN_ALIGNED_POINTS = 12


@dataclass
class SeriesInput:
    market_id: str
    event_id: str | None
    question: str
    series: list[tuple[int, float]]  # (epoch_minute_bucket, yes_price)


def _aligned_returns(a: list[tuple[int, float]], b: list[tuple[int, float]]) -> tuple[np.ndarray, np.ndarray]:
    map_a = dict(a)
    map_b = dict(b)
    common = sorted(set(map_a) & set(map_b))
    if len(common) < MIN_ALIGNED_POINTS + 1:
        return np.array([]), np.array([])
    pa = np.array([map_a[t] for t in common], dtype=float)
    pb = np.array([map_b[t] for t in common], dtype=float)
    return np.diff(pa), np.diff(pb)


def correlation(a: list[tuple[int, float]], b: list[tuple[int, float]]) -> float | None:
    ra, rb = _aligned_returns(a, b)
    if ra.size < MIN_ALIGNED_POINTS:
        return None
    if np.std(ra) < 1e-9 or np.std(rb) < 1e-9:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def build_graph(
    inputs: list[SeriesInput],
    correlation_threshold: float = 0.6,
    max_pairs: int = 20000,
) -> nx.Graph:
    graph = nx.Graph()
    for item in inputs:
        graph.add_node(item.market_id, question=item.question, event_id=item.event_id)

    # same_event edges (cheap, structural)
    by_event: dict[str, list[SeriesInput]] = {}
    for item in inputs:
        if item.event_id:
            by_event.setdefault(item.event_id, []).append(item)
    for event_id, members in by_event.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                graph.add_edge(
                    members[i].market_id, members[j].market_id,
                    kind="same_event", coefficient=-1.0, confidence=1.0,
                )

    # correlation edges, limited to liquid series to keep O(n^2) bounded
    candidates = [item for item in inputs if len(item.series) >= MIN_ALIGNED_POINTS + 1]
    pairs_checked = 0
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if pairs_checked >= max_pairs:
                break
            pairs_checked += 1
            a, b = candidates[i], candidates[j]
            if graph.has_edge(a.market_id, b.market_id):
                continue
            coef = correlation(a.series, b.series)
            if coef is None or abs(coef) < correlation_threshold:
                continue
            graph.add_edge(
                a.market_id, b.market_id,
                kind="correlated" if coef > 0 else "anti_correlated",
                coefficient=round(coef, 4),
                confidence=round(min(1.0, abs(coef)), 4),
            )
    return graph


def graph_edges_as_records(graph: nx.Graph) -> list[dict]:
    ts = now_utc()
    return [
        {
            "market_a": a,
            "market_b": b,
            "kind": data.get("kind", "correlated"),
            "coefficient": float(data.get("coefficient", 0.0)),
            "confidence": float(data.get("confidence", 0.0)),
            "updated_at": ts,
        }
        for a, b, data in graph.edges(data=True)
    ]


def simulate_cascade(
    graph: nx.Graph,
    origin: str,
    shock: float,
    damping: float = 0.6,
    min_effect: float = 0.01,
    max_depth: int = 3,
) -> list[dict]:
    """Propagate a probability shock through the graph (BFS with damping).

    same_event edges push the opposite way (one outcome up → siblings down);
    correlated edges push proportionally to the coefficient.
    """
    if origin not in graph:
        return []
    effects: dict[str, float] = {origin: shock}
    frontier = [(origin, shock, 0)]
    while frontier:
        node, effect, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        for neighbor in graph.neighbors(node):
            data = graph.get_edge_data(node, neighbor) or {}
            coef = float(data.get("coefficient", 0.0))
            propagated = effect * coef * damping
            if abs(propagated) < min_effect:
                continue
            previous = effects.get(neighbor, 0.0)
            if abs(previous) >= abs(propagated):
                continue
            effects[neighbor] = propagated
            frontier.append((neighbor, propagated, depth + 1))
    return [
        {"market_id": market, "expected_move": round(move, 4)}
        for market, move in sorted(effects.items(), key=lambda kv: -abs(kv[1]))
        if market != origin
    ]
