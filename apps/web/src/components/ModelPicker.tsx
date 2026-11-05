import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { useStore } from "../store";
import { cx } from "../lib/util";

export default function ModelPicker() {
  const { models, model, setModel } = useStore();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const cur = models.find((m) => m.id === model) ?? models[0];
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open} className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-muted hover:bg-sunk hover:text-ink">
        {cur?.name} <ChevronDown size={14} />
      </button>
      {open && (
        <ul role="listbox" className="absolute bottom-full right-0 z-20 mb-2 w-72 rounded-xl border border-line bg-panel p-1 shadow-lg">
          {models.map((m) => (
            <li key={m.id}>
              <button role="option" aria-selected={m.id === model} onClick={() => { setModel(m.id); setOpen(false); }} className={cx("flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left hover:bg-sunk")}>
                <span className="flex-1">
                  <span className="block text-sm font-medium">{m.name}</span>
                  {m.note && <span className="block text-xs text-muted">{m.note}</span>}
                </span>
                {m.id === model && <Check size={16} className="mt-0.5 text-accent" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
