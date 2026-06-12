"""Central configuration loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General -------------------------------------------------
    app_name: str = "polymarket-edge"
    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "*"

    # --- Storage -------------------------------------------------
    database_url: str = "postgresql+asyncpg://polybot:polybot@localhost:5432/polybot"
    redis_url: str = "redis://localhost:6379/0"

    # --- Workers / scanner ----------------------------------------
    run_workers_in_app: bool = False
    scan_interval_seconds: int = 60
    max_markets_per_scan: int = 2000
    orderbook_top_n: int = 150
    snapshot_retention_days: int = 90
    graph_refresh_minutes: int = 60
    ml_retrain_hours: int = 24

    # --- Anthropic AI engine --------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    ai_analysis_enabled: bool = True
    ai_max_analyses_per_cycle: int = 8
    ai_analysis_cooldown_minutes: int = 120
    ai_min_confidence_alert: float = 0.75
    ai_max_concurrency: int = 2

    # --- External data sources ------------------------------------
    newsapi_key: str = ""
    twitter_bearer_token: str = ""
    reddit_user_agent: str = "polymarket-edge/1.0"
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    binance_base_url: str = "https://api.binance.com"
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"

    # --- Trading & risk -------------------------------------------
    trading_mode: str = "paper"  # paper | live
    auto_trade_enabled: bool = False
    starting_bankroll: float = 500.0
    fee_rate: float = 0.0
    spread_buffer: float = 0.005
    kelly_fraction: float = 0.25
    max_risk_per_trade_pct: float = 2.0
    max_market_exposure_pct: float = 10.0
    max_category_exposure_pct: float = 25.0
    max_total_exposure_pct: float = 60.0
    max_daily_loss_pct: float = 5.0
    max_drawdown_pct: float = 15.0
    stop_loss_pct: float = 25.0
    min_edge_score_to_trade: float = 70.0
    min_liquidity_to_trade: float = 1_000.0
    max_open_positions: int = 25
    auto_hedge_enabled: bool = True
    hedge_trigger_loss_pct: float = 15.0

    # --- Polymarket live trading ----------------------------------
    polymarket_private_key: str = ""
    polymarket_proxy_address: str = ""
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_api_passphrase: str = ""

    # --- Alerts ----------------------------------------------------
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    edge_alert_threshold: float = 75.0
    arb_alert_min_edge: float = 0.01
    alert_cooldown_minutes: int = 60
    big_move_alert_pct: float = 10.0

    # --- ML ---------------------------------------------------------
    ml_enabled: bool = True
    ml_min_training_samples: int = 200
    models_dir: str = "models"

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def anthropic_enabled(self) -> bool:
        return bool(self.anthropic_api_key) and self.ai_analysis_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()
