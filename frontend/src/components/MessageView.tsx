import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { BookMarked, Check, Copy, Download } from "lucide-react";
import type { Evidence, Message } from "../types";
import { cx } from "../lib/util";
import { exportMemo } from "../lib/export";
import AgentTrace from "./AgentTrace";
import { ArgumentsPanel, EvaluationPanel } from "./Analysis";

const EMPTY: Evidence[] = [];
const chip = { accent: "border-accent/40 bg-accent-soft text-accent", warn: "border-warn/40 bg-warn/10 text-warn", bad: "border-bad/40 bg-bad/10 text-bad" };

interface Props {
  m: Message;
  chatTitle: string;
  caseTitle?: string;
  onSources: (activeId?: string) => void;
}

export default function MessageView({ m, chatTitle, caseTitle, onSources }: Props) {
  const [copied, setCopied] = useState(false);
  const ev = m.evidence ?? EMPTY;
  const num = (id: string) => ev.findIndex((e) => e.id === id) + 1;

  // Turn [E1] markers into numbered citation chips. A marker with no matching evidence is shown in red.
  const text = useMemo(
    () => m.content.replace(/\[(E\d+)\]/g, (_, id: string) => `[${ev.findIndex((e) => e.id === id) + 1 || "?"}](#ev:${id})`),
    [m.content, ev]
  );
  const components: Components = useMemo(
    () => ({
      a: ({ href, children }) => {
        if (href?.startsWith("#ev:")) {
          const id = href.slice(4);
          const e = ev.find((x) => x.id === id);
          const tone = !e || e.verification === "failed" ? "bad" : e.verification === "unverified" ? "warn" : "accent";
          return (
            <button onClick={() => onSources(id)} title={e ? e.title : "This citation has no matching source in the evidence store"} className={cx("mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-0.5 items-center justify-center rounded-full border px-1 font-sans text-[11px] font-medium", chip[tone])}>
              {children}
            </button>
          );
        }
        return <a href={href} target="_blank" rel="noreferrer" className="text-accent underline">{children}</a>;
      },
    }),
    [ev, onSources]
  );

  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-sunk px-4 py-2.5 text-[15px]">{m.content}</div>
      </div>
    );
  }

  const streaming = m.status === "streaming";
  const unverified = ev.filter((e) => e.verification !== "verified").length;
  return (
    <div>
      {m.trace && m.trace.length > 0 && <AgentTrace trace={m.trace} streaming={streaming && !m.content} />}
      {streaming && !m.content && !m.trace?.length && (
        <div className="flex gap-1 py-2" aria-label="Working"><span className="dot h-2 w-2 rounded-full bg-muted" /><span className="dot h-2 w-2 rounded-full bg-muted" /><span className="dot h-2 w-2 rounded-full bg-muted" /></div>
      )}
      {m.content && (
        <div className="memo">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{text}</ReactMarkdown>
        </div>
      )}
      {m.status === "error" && (
        <p role="alert" className="mt-2 rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">
          {m.error ?? "Something went wrong."} Check that the backend is running, then send the message again.
        </p>
      )}
      {m.proArgs && m.conArgs && <ArgumentsPanel pro={m.proArgs} con={m.conArgs} num={num} onCite={onSources} />}
      {m.evaluation && <EvaluationPanel ev={m.evaluation} />}

      {!streaming && m.status !== "error" && (
        <div className="mt-3 flex flex-wrap items-center gap-1 text-sm text-muted">
          {ev.length > 0 && (
            <button onClick={() => onSources()} className="flex items-center gap-1.5 rounded-lg px-2 py-1 hover:bg-sunk hover:text-ink">
              <BookMarked size={15} /> {ev.length} sources{unverified > 0 && <span className="text-warn">, {unverified} to check</span>}
            </button>
          )}
          <button aria-label="Copy answer" className="rounded-lg p-1.5 hover:bg-sunk hover:text-ink" onClick={() => { navigator.clipboard.writeText(m.content); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
            {copied ? <Check size={15} /> : <Copy size={15} />}
          </button>
          <button className="flex items-center gap-1.5 rounded-lg px-2 py-1 hover:bg-sunk hover:text-ink" onClick={() => exportMemo(chatTitle, caseTitle, m)}>
            <Download size={15} /> Export memo
          </button>
          {m.executionId && <span className="ml-auto text-xs">Run {m.executionId}</span>}
        </div>
      )}
    </div>
  );
}
