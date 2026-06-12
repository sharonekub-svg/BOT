import type { ReactNode } from "react";

export default function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-panelBorder bg-panel/70 backdrop-blur px-4 py-3 ${className}`}
    >
      <header className="mb-3 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">{title}</h2>
        {right}
      </header>
      {children}
    </section>
  );
}
