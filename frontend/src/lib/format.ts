export function fmtUsd(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "–";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

export function fmtCompact(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "–";
  return `${(value * 100).toFixed(digits)}%`;
}

export function fmtSignedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "–";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(digits)}%`;
}

export function fmtProb(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `${Math.round(value * 100)}¢`;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "–";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return `${Math.max(1, Math.floor(seconds))}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function pnlColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return "text-slate-400";
  if (value > 0) return "text-emerald-400";
  if (value < 0) return "text-rose-400";
  return "text-slate-400";
}

export function edgeColor(score: number): string {
  if (score >= 75) return "text-emerald-400";
  if (score >= 50) return "text-amber-400";
  return "text-slate-400";
}

export function heatColor(change: number | null | undefined): string {
  if (change === null || change === undefined) return "bg-slate-800";
  const c = Math.max(-0.15, Math.min(0.15, change));
  if (c > 0.075) return "bg-emerald-600/80";
  if (c > 0.025) return "bg-emerald-700/60";
  if (c > 0.005) return "bg-emerald-800/40";
  if (c < -0.075) return "bg-rose-600/80";
  if (c < -0.025) return "bg-rose-700/60";
  if (c < -0.005) return "bg-rose-800/40";
  return "bg-slate-800";
}
