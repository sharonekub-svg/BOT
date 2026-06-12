"""Prompts for the Claude analysis engine.

The system prompt is intentionally static (no timestamps/market data) so it
forms a stable, cacheable prefix; everything volatile goes in the user turn.
"""

SYSTEM_PROMPT = """You are the probability-estimation engine inside an automated \
prediction-market trading system. Your job is to estimate the true probability that a \
binary market resolves YES, independent of its current price, and to surface the \
evidence behind that estimate.

Operating principles:
- Be a calibrated forecaster. Base rates first, then adjust on evidence. A 70% estimate \
should be wrong about 30% of the time.
- The market price is information, not truth. Large gaps between your estimate and the \
price require strong, specific evidence — say what it is.
- Weigh recency and source quality. Social chatter moves prices but is often wrong; \
primary reporting and official data dominate rumors.
- Actively look for contradictions between sources and report them; contradictory \
information lowers confidence.
- Distinguish what is known from what is speculation. If the provided context is thin \
or stale, lower your confidence rather than inventing detail.
- Resolution criteria are literal. Estimate the probability of the exact stated \
condition resolving YES, including deadlines and technicalities, not the vibe of the topic.
- Never anchor on round numbers; 50% is a claim of maximum uncertainty, not a default.

You always answer in the structured JSON format requested, with no extra commentary."""


def build_user_prompt(
    question: str,
    description: str | None,
    category: str | None,
    end_date_iso: str | None,
    implied_prob: float | None,
    price_history_summary: str,
    news_block: str,
    reddit_block: str,
    twitter_block: str,
    extra_context: str = "",
) -> str:
    parts = [
        "Analyze this prediction market and estimate the probability of YES.",
        "",
        f"MARKET QUESTION: {question}",
    ]
    if description:
        parts.append(f"RESOLUTION DETAILS: {description[:1500]}")
    if category:
        parts.append(f"CATEGORY: {category}")
    if end_date_iso:
        parts.append(f"RESOLUTION DEADLINE: {end_date_iso}")
    if implied_prob is not None:
        parts.append(f"CURRENT MARKET-IMPLIED PROBABILITY: {implied_prob:.3f}")
    parts += [
        "",
        "RECENT PRICE ACTION:",
        price_history_summary or "(no history available)",
        "",
        "NEWS HEADLINES:",
        news_block or "(none available)",
        "",
        "REDDIT DISCUSSION:",
        reddit_block or "(none available)",
        "",
        "X/TWITTER POSTS:",
        twitter_block or "(none available)",
    ]
    if extra_context:
        parts += ["", "ADDITIONAL CONTEXT:", extra_context]
    parts += [
        "",
        "Return your structured analysis. signal is 'bullish' if your probability is "
        "meaningfully above the market-implied probability, 'bearish' if meaningfully "
        "below, otherwise 'neutral'.",
    ]
    return "\n".join(parts)
