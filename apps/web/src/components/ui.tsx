import type { ReactNode } from "react";
import { Menu, X } from "lucide-react";
import { useStore } from "../store";
import { cx } from "../lib/util";

export type Tone = "neutral" | "ok" | "warn" | "bad" | "accent";
const tones: Record<Tone, string> = {
  neutral: "text-muted border-line bg-sunk",
  ok: "text-ok border-ok/30 bg-ok/10",
  warn: "text-warn border-warn/30 bg-warn/10",
  bad: "text-bad border-bad/30 bg-bad/10",
  accent: "text-accent border-accent/30 bg-accent-soft",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium", tones[tone])}>
      {children}
    </span>
  );
}

export const input =
  "w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm outline-none placeholder:text-muted/70 focus:border-accent";
export const btn =
  "inline-flex items-center justify-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-sm hover:bg-sunk disabled:opacity-50";
export const btnPrimary =
  "inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-page hover:opacity-90 disabled:opacity-50";

export function PageHeader({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }) {
  const setSidebar = useStore((s) => s.setSidebar);
  return (
    <header className="flex min-h-14 shrink-0 items-center gap-3 border-b border-line px-4">
      <button className="rounded-lg p-1.5 hover:bg-sunk md:hidden" aria-label="Open menu" onClick={() => setSidebar(true)}>
        <Menu size={20} />
      </button>
      <div className="min-w-0 flex-1">
        <h1 className="truncate font-serif text-lg font-semibold">{title}</h1>
        {sub && <p className="truncate text-xs text-muted">{sub}</p>}
      </div>
      {children}
    </header>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div role="dialog" aria-label={title} className="max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-panel p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-serif text-xl font-semibold">{title}</h2>
          <button aria-label="Close" className="rounded-lg p-1 hover:bg-sunk" onClick={onClose}><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-sunk p-0.5">
      {options.map((o) => (
        <button key={o.id} onClick={() => onChange(o.id)} className={cx("rounded-md px-3 py-1 text-sm", value === o.id ? "bg-panel font-medium shadow-sm" : "text-muted hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-muted">{label}</span>
      {children}
    </label>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-6 py-10 text-center">
      <p className="font-serif text-lg">{title}</p>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}
