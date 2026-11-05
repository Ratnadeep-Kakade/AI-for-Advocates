import { useState } from "react";
import { ChevronRight, Loader2 } from "lucide-react";
import { AGENTS } from "../types";
import type { AgentId, TraceItem } from "../types";
import { cx } from "../lib/util";

const dot: Record<AgentId, string> = {
  orchestrator: "bg-accent", analyzer: "bg-sky-500", researcher: "bg-emerald-500",
  argument: "bg-violet-500", counterargument: "bg-rose-500", evaluator: "bg-amber-500",
};

export default function AgentTrace({ trace, streaming }: { trace: TraceItem[]; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  const show = open || streaming;
  const last = trace[trace.length - 1];
  return (
    <div className="mb-3 rounded-xl border border-line bg-sunk/60 text-sm">
      <button onClick={() => setOpen(!open)} aria-expanded={show} className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted">
        {streaming ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} className={cx("transition-transform", show && "rotate-90")} />}
        <span className="flex-1 truncate">
          {streaming && last ? `${AGENTS[last.agent].name}: ${last.text}` : `Agent activity (${trace.length} steps)`}
        </span>
      </button>
      {show && (
        <ol className="space-y-1.5 border-t border-line px-3 py-2">
          {trace.map((t) => (
            <li key={t.id} className="flex gap-2">
              <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", dot[t.agent])} />
              <span className={cx(t.kind === "tool" && "font-mono text-xs leading-5", t.kind === "start" && "font-medium")}>
                {t.kind === "start" && <span className="text-muted">{AGENTS[t.agent].name}: </span>}
                {t.kind !== "start" && <span className="text-muted">{AGENTS[t.agent].name} </span>}
                {t.text}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
