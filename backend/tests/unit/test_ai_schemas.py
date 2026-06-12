from app.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.ai.schemas import ANALYSIS_JSON_SCHEMA, MarketAnalysis


class TestMarketAnalysis:
    def test_valid_payload(self):
        analysis = MarketAnalysis(
            probability_estimate=0.72,
            confidence=0.6,
            signal="bullish",
            reasoning="Strong evidence.",
            key_factors=["a", "b"],
            contradictions=[],
            news_sentiment=0.4,
            social_sentiment=-0.2,
            sources_considered=["news"],
        )
        assert analysis.probability_estimate == 0.72
        assert analysis.signal == "bullish"

    def test_probability_clamped(self):
        analysis = MarketAnalysis(
            probability_estimate=1.7, confidence=-0.5, signal="bullish", reasoning="x"
        )
        assert analysis.probability_estimate == 1.0
        assert analysis.confidence == 0.0

    def test_sentiment_clamped(self):
        analysis = MarketAnalysis(
            probability_estimate=0.5, confidence=0.5, signal="neutral",
            reasoning="x", news_sentiment=5.0, social_sentiment=-9.0,
        )
        assert analysis.news_sentiment == 1.0
        assert analysis.social_sentiment == -1.0

    def test_unknown_signal_becomes_neutral(self):
        analysis = MarketAnalysis(
            probability_estimate=0.5, confidence=0.5, signal="MOON", reasoning="x"
        )
        assert analysis.signal == "neutral"


class TestJsonSchema:
    def test_schema_is_strict(self):
        assert ANALYSIS_JSON_SCHEMA["additionalProperties"] is False
        # every property is required (structured-outputs requirement)
        assert set(ANALYSIS_JSON_SCHEMA["required"]) == set(ANALYSIS_JSON_SCHEMA["properties"])

    def test_schema_has_no_unsupported_constraints(self):
        # numeric min/max are unsupported by structured outputs — must not appear
        def walk(node):
            if isinstance(node, dict):
                assert "minimum" not in node and "maximum" not in node
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(ANALYSIS_JSON_SCHEMA)

    def test_schema_matches_pydantic_fields(self):
        assert set(ANALYSIS_JSON_SCHEMA["properties"]) == set(MarketAnalysis.model_fields)


class TestPrompts:
    def test_system_prompt_is_static(self):
        # cacheability: no volatile interpolation markers
        assert "{" not in SYSTEM_PROMPT or "}" not in SYSTEM_PROMPT.replace("{}", "")
        assert len(SYSTEM_PROMPT) > 200

    def test_user_prompt_includes_market_data(self):
        prompt = build_user_prompt(
            question="Will X happen?",
            description="Resolution details here",
            category="politics",
            end_date_iso="2026-12-31T00:00:00+00:00",
            implied_prob=0.42,
            price_history_summary="current 0.42",
            news_block="- headline",
            reddit_block="- post",
            twitter_block="- tweet",
        )
        assert "Will X happen?" in prompt
        assert "0.420" in prompt
        assert "headline" in prompt
