"""Structured output contract for the Claude analysis engine.

The JSON schema is sent via `output_config.format` so the API guarantees
shape; Pydantic re-validates and clamps ranges client-side (the structured
outputs feature doesn't support numeric min/max constraints).
"""

from pydantic import BaseModel, Field, field_validator


class MarketAnalysis(BaseModel):
    probability_estimate: float = Field(description="P(YES) between 0 and 1")
    confidence: float = Field(description="Self-assessed confidence 0..1")
    signal: str = Field(description="bullish | bearish | neutral (on YES)")
    reasoning: str
    key_factors: list[str] = []
    contradictions: list[str] = []
    news_sentiment: float = 0.0    # -1..1
    social_sentiment: float = 0.0  # -1..1
    sources_considered: list[str] = []

    @field_validator("probability_estimate", "confidence")
    @classmethod
    def _clamp_unit(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("news_sentiment", "social_sentiment")
    @classmethod
    def _clamp_signed(cls, v: float) -> float:
        return max(-1.0, min(1.0, v))

    @field_validator("signal")
    @classmethod
    def _normalize_signal(cls, v: str) -> str:
        v = v.lower().strip()
        return v if v in {"bullish", "bearish", "neutral"} else "neutral"


# JSON schema for output_config.format — objects need additionalProperties:false
# and every property required; numeric range constraints are not supported.
ANALYSIS_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "probability_estimate": {
            "type": "number",
            "description": "Probability the market resolves YES, between 0 and 1.",
        },
        "confidence": {
            "type": "number",
            "description": "Confidence in the estimate, between 0 and 1.",
        },
        "signal": {
            "type": "string",
            "enum": ["bullish", "bearish", "neutral"],
            "description": "Directional view on the YES outcome relative to current price.",
        },
        "reasoning": {
            "type": "string",
            "description": "Concise reasoning summary (3-6 sentences).",
        },
        "key_factors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Most important drivers of the estimate.",
        },
        "contradictions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Conflicting information detected across sources.",
        },
        "news_sentiment": {
            "type": "number",
            "description": "Aggregate news sentiment toward YES, -1 (bearish) to 1 (bullish).",
        },
        "social_sentiment": {
            "type": "number",
            "description": "Aggregate social (X/Reddit) sentiment toward YES, -1 to 1.",
        },
        "sources_considered": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Which provided context sections informed the estimate.",
        },
    },
    "required": [
        "probability_estimate",
        "confidence",
        "signal",
        "reasoning",
        "key_factors",
        "contradictions",
        "news_sentiment",
        "social_sentiment",
        "sources_considered",
    ],
    "additionalProperties": False,
}
