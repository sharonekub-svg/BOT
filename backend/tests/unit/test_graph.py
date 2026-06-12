from app.graph.relationships import (
    SeriesInput,
    build_graph,
    correlation,
    graph_edges_as_records,
    simulate_cascade,
)


def series(values: list[float], start: int = 0) -> list[tuple[int, float]]:
    return [(start + i, v) for i, v in enumerate(values)]


def wiggle(n: int, seed: int = 1) -> list[float]:
    # deterministic non-constant series
    vals = []
    x = 0.5
    for i in range(n):
        x += 0.01 if (i * seed) % 3 == 0 else -0.005
        vals.append(round(x, 4))
    return vals


class TestCorrelation:
    def test_identical_series_perfectly_correlated(self):
        a = series(wiggle(30))
        assert abs(correlation(a, a) - 1.0) < 1e-9

    def test_inverted_series_anti_correlated(self):
        vals = wiggle(30)
        a = series(vals)
        b = series([1 - v for v in vals])
        assert correlation(a, b) < -0.99

    def test_insufficient_overlap_returns_none(self):
        a = series(wiggle(30), start=0)
        b = series(wiggle(30), start=1000)  # no common buckets
        assert correlation(a, b) is None

    def test_flat_series_returns_none(self):
        a = series([0.5] * 30)
        b = series(wiggle(30))
        assert correlation(a, b) is None


class TestBuildGraph:
    def test_same_event_edges(self):
        inputs = [
            SeriesInput("a", "ev1", "A?", []),
            SeriesInput("b", "ev1", "B?", []),
            SeriesInput("c", "ev2", "C?", []),
        ]
        graph = build_graph(inputs)
        assert graph.has_edge("a", "b")
        assert graph.get_edge_data("a", "b")["kind"] == "same_event"
        assert not graph.has_edge("a", "c")

    def test_correlation_edges(self):
        vals = wiggle(40)
        inputs = [
            SeriesInput("a", None, "A?", series(vals)),
            SeriesInput("b", None, "B?", series(vals)),  # identical -> corr 1
            SeriesInput("c", None, "C?", series([0.5] * 40)),  # flat -> no edge
        ]
        graph = build_graph(inputs, correlation_threshold=0.6)
        assert graph.has_edge("a", "b")
        assert graph.get_edge_data("a", "b")["kind"] == "correlated"
        assert not graph.has_edge("a", "c")

    def test_edge_records_shape(self):
        inputs = [SeriesInput("a", "ev1", "A?", []), SeriesInput("b", "ev1", "B?", [])]
        records = graph_edges_as_records(build_graph(inputs))
        assert len(records) == 1
        record = records[0]
        for key in ("market_a", "market_b", "kind", "coefficient", "confidence", "updated_at"):
            assert key in record


class TestCascade:
    def test_shock_propagates_with_damping(self):
        inputs = [
            SeriesInput("a", None, "A?", []),
            SeriesInput("b", None, "B?", []),
        ]
        graph = build_graph(inputs)
        graph.add_edge("a", "b", kind="correlated", coefficient=1.0, confidence=1.0)
        effects = simulate_cascade(graph, "a", shock=0.2, damping=0.6)
        assert effects[0]["market_id"] == "b"
        assert abs(effects[0]["expected_move"] - 0.12) < 1e-9

    def test_same_event_pushes_opposite(self):
        inputs = [SeriesInput("a", "ev1", "A?", []), SeriesInput("b", "ev1", "B?", [])]
        graph = build_graph(inputs)  # same_event edge has coefficient -1
        effects = simulate_cascade(graph, "a", shock=0.2, damping=0.6)
        assert effects[0]["expected_move"] < 0

    def test_unknown_origin(self):
        graph = build_graph([])
        assert simulate_cascade(graph, "missing", 0.5) == []

    def test_small_effects_pruned(self):
        inputs = [SeriesInput("a", None, "A?", []), SeriesInput("b", None, "B?", [])]
        graph = build_graph(inputs)
        graph.add_edge("a", "b", kind="correlated", coefficient=0.05, confidence=1.0)
        assert simulate_cascade(graph, "a", shock=0.1, min_effect=0.01) == []
