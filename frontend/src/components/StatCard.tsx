export default function StatCard({
  label,
  value,
  sub,
  valueClass = "text-slate-100",
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-xl border border-panelBorder bg-panel/70 px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-widest text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-xl font-semibold ${valueClass}`}>{value}</div>
      {sub ? <div className="mt-0.5 text-xs text-slate-500">{sub}</div> : null}
    </div>
  );
}
