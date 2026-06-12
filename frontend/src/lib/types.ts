export interface Opportunity {
  signal_id: number;
  market_id: string;
  question: string;
  category: string | null;
  direction: "buy_yes" | "buy_no";
  edge_score: number;
  implied_prob: number | null;
  fair_prob: number | null;
  expected_value: number | null;
  kelly_size: number | null;
  confidence: number | null;
  liquidity: number | null;
  volume_24h: number | null;
  end_date: string | null;
  rationale: string | null;
  source: string;
  ts: string;
}

export interface Position {
  id: number;
  market_id: string;
  question: string;
  category: string | null;
  outcome: "YES" | "NO";
  qty: number;
  avg_price: number;
  current_price: number | null;
  value: number;
  unrealized_pnl: number | null;
  opened_at: string | null;
}

export interface Portfolio {
  equity: number;
  cash: number;
  exposure: number;
  unrealized_pnl: number;
  realized_pnl_today: number;
  drawdown: number;
  open_positions: number;
  starting_bankroll: number;
  mode: string;
  ts?: string;
}

export interface PortfolioPoint {
  ts: string;
  equity: number;
  exposure: number;
  drawdown: number;
}

export interface RiskReport {
  equity: number;
  cash: number;
  total_exposure: number;
  total_exposure_pct: number;
  exposure_by_category: Record<string, number>;
  open_positions: number;
  daily_pnl: number;
  drawdown_pct: number;
  circuit_breaker_tripped: boolean;
  warnings: string[];
  limits: {
    max_risk_per_trade_pct: number;
    max_market_exposure_pct: number;
    max_total_exposure_pct: number;
    max_daily_loss_pct: number;
    max_drawdown_pct: number;
    max_open_positions: number;
    kelly_fraction: number;
  };
}

export interface HeatmapTile {
  id: string;
  question: string;
  category: string;
  yes_price: number | null;
  change: number | null;
  volume_24h: number | null;
}

export interface ArbitrageRow {
  id: number;
  ts: string;
  kind: string;
  market_ids: string[];
  net_edge: number;
  gross_edge: number;
  description: string;
}

export interface FeedEvent {
  type: string;
  ts: string;
  data: Record<string, unknown>;
}

export interface SystemStatus {
  version: string;
  trading_mode: string;
  auto_trade_enabled: boolean;
  ai_enabled: boolean;
  telegram_enabled: boolean;
  redis_connected: boolean;
  counts: Record<string, number>;
}
