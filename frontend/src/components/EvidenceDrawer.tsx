import { useEffect, useRef } from "react";
import { AlertTriangle, Copy, X } from "lucide-react";
import type { Authority, Evidence, Verification } from "../types";
import { cx } from "../lib/util";
import { Badge } from "./ui";
import type { Tone } from "./ui";

const authLabel: Record<Authority, [string, Tone]> = {
  binding: ["Binding authority", "ok"],
  persuasive: ["Persuasive authority", "accent"],
  "non-authoritative": ["Not authoritative", "neutral"],
  "case-document": ["Case document", "neutral"],
};
const verLabel: Record<Verification, [string, Tone]> = {
  verified: ["Verified against source", "ok"],
  unverified: ["Unverified", "warn"],
  failed: ["Verification failed", "bad"],
};

export default function EvidenceDrawer({ evidence, activeId, onClose }: { evidence: Evidence[]; activeId?: string; onClose: () => void }) {
  const refs = useRef<Record<string, HTMLElement | null>>({});
  useEffect(() => {
    if (activeId) refs.current[activeId]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeId]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <aside aria-label="Sources" className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-line bg-panel shadow-xl">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="font-serif text-lg font-semibold">Sources ({evidence.length})</h2>
        <button aria-label="Close sources" onClick={onClose} className="rounded-lg p-1.5 hover:bg-sunk"><X size={18} /></button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {evidence.map((e, i) => {
          const [al, at] = authLabel[e.authority];
          const [vl, vt] = verLabel[e.verification];
          return (
            <article key={e.id} ref={(el) => { refs.current[e.id] = el; }} className={cx("rounded-xl border p-3", e.id === activeId ? "border-accent bg-accent-soft/40" : "border-line")}>
              <div className="mb-1 flex items-start gap-2">
                <span className="mt-0.5 flex h-5 min-w-5 items-center justify-center rounded-full border border-line bg-sunk px-1 text-[11px]">{i + 1}</span>
                <h3 className="flex-1 text-sm font-medium">{e.title}</h3>
                <button aria-label="Copy citation" title="Copy citation" className="rounded p-1 text-muted hover:text-ink" onClick={() => navigator.clipboard.writeText(`${e.title}${e.cite ? ", " + e.cite : ""}`)}>
                  <Copy size={14} />
                </button>
              </div>
              <div className="mb-2 flex flex-wrap gap-1">
                <Badge tone={at}>{al}</Badge>
                <Badge tone={vt}>{vl}</Badge>
              </div>
              <blockquote className="border-l-2 border-line pl-3 font-serif text-[15px] leading-relaxed">{e.passage}</blockquote>
              {e.source && <p className="mt-2 text-xs text-muted">{/^https?:/.test(e.source) ? <a className="underline" href={e.source} target="_blank" rel="noreferrer">{e.source}</a> : e.source}</p>}
              {e.verification !== "verified" && (
                <p className="mt-2 flex items-start gap-1.5 text-xs text-warn"><AlertTriangle size={13} className="mt-0.5 shrink-0" /> Check this against the original before citing it in any filing.</p>
              )}
            </article>
          );
        })}
      </div>
    </aside>
  );
}
