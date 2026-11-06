import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { BookMarked, Check, Copy, Download, Loader2, Pencil, RotateCcw } from "lucide-react";
import type { Evidence, Message } from "../types";
import { cx } from "../lib/util";
import { exportMemo } from "../lib/export";
import { ArgumentsPanel, EvaluationPanel } from "./Analysis";

const EMPTY: Evidence[] = [];
const chip = { accent: "border-accent/40 bg-accent-soft text-accent", warn: "border-warn/40 bg-warn/10 text-warn", bad: "border-bad/40 bg-bad/10 text-bad" };

const AGENT_REASONING_LABELS: Record<string, string> = {
  interpreter: "Interpreting...",
  orchestrator: "Orchestrating...",
  researcher: "Researching...",
  argument: "Building arguments...",
  counterargument: "Formulating counter-arguments...",
  evaluator: "Evaluating...",
  analyzer: "Analyzing...",
};

interface Props {
  m: Message;
  chatTitle: string;
  caseTitle?: string;
  onSources: (activeId?: string) => void;
  onRegenerate?: (messageId: string) => void;
  onEdit?: (prompt: string) => void;
}

function cleanBpeText(content: string): string {
  if (!content) return "";
  // Decode raw byte-level BPE tokens (Ġ -> space, Ċ -> newline, ĉ -> tab, č -> carriage return)
  return content
    .replace(/Ċ/g, "\n")
    .replace(/Ġ/g, " ")
    .replace(/ĉ/g, "\t")
    .replace(/č/g, "\r");
}

export default function MessageView({ m, chatTitle, caseTitle, onSources, onRegenerate, onEdit }: Props) {
  const [copied, setCopied] = useState(false);
  const ev = m.evidence ?? EMPTY;
  const num = (id: string) => ev.findIndex((e) => e.id === id) + 1;

  const cleanedContent = useMemo(() => cleanBpeText(m.content), [m.content]);

  // Turn [E1] markers into numbered citation chips. A marker with no matching evidence is shown in red.
  const text = useMemo(
    () => cleanedContent.replace(/\[(E\d+)\]/g, (_, id: string) => `[${ev.findIndex((e) => e.id === id) + 1 || "?"}](#ev:${id})`),
    [cleanedContent, ev]
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
      code: ({ className, children, ...props }) => {
        const match = /language-(\w+)/.exec(className || "");
        const contentStr = String(children).replace(/\n$/, "");
        const isMultiLine = contentStr.includes("\n");
        if (!match && !isMultiLine) {
          return <code className="rounded bg-sunk px-1.5 py-0.5 font-mono text-xs text-ink" {...props}>{children}</code>;
        }
        const lang = match ? match[1] : "text";
        return (
          <div className="my-3 overflow-hidden rounded-xl border border-line bg-page text-sm">
            <div className="flex items-center justify-between border-b border-line bg-sunk/60 px-3 py-1.5 text-xs text-muted">
              <span className="font-mono uppercase">{lang}</span>
              <button
                type="button"
                className="flex items-center gap-1 rounded px-2 py-0.5 hover:bg-panel hover:text-ink"
                onClick={() => {
                  navigator.clipboard.writeText(contentStr);
                }}
              >
                <Copy size={12} /> Copy
              </button>
            </div>
            <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed">
              <code>{children}</code>
            </pre>
          </div>
        );
      },
    }),
    [ev, onSources]
  );

  if (m.role === "user") {
    return (
      <div className="group flex justify-end items-start gap-2">
        {onEdit && (
          <button
            type="button"
            aria-label="Edit prompt"
            onClick={() => onEdit(m.content)}
            className="rounded-lg p-1 text-muted opacity-0 hover:bg-sunk hover:text-ink group-hover:opacity-100 transition-opacity"
            title="Edit prompt"
          >
            <Pencil size={14} />
          </button>
        )}
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-sunk px-4 py-2.5 text-[15px]">{m.content}</div>
      </div>
    );
  }

  const streaming = m.status === "streaming";
  const unverified = ev.filter((e) => e.verification !== "verified").length;
  const lastStep = m.trace && m.trace.length > 0 ? m.trace[m.trace.length - 1] : null;
  const activeAgent = lastStep?.agent ?? "interpreter";
  const reasoningStatus = AGENT_REASONING_LABELS[activeAgent] ?? "Interpreting...";

  return (
    <div>
      {streaming && !m.content && (
        <div className="flex items-center gap-2.5 py-2 text-sm text-accent font-medium" aria-label={reasoningStatus}>
          <Loader2 size={14} className="animate-spin text-accent" />
          <span>{reasoningStatus}</span>
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
            <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse [animation-delay:0.2s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse [animation-delay:0.4s]" />
          </span>
        </div>
      )}
      {m.content && (
        <div className="memo">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{text}</ReactMarkdown>
          {streaming && <span className="inline-block h-4 w-1.5 animate-pulse bg-accent align-middle ml-1" />}
        </div>
      )}
      {m.status === "error" && (
        <div role="alert" className="mt-2 flex items-center justify-between rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">
          <span>{m.error ?? "Something went wrong."}</span>
          {onRegenerate && (
            <button
              className="ml-3 rounded border border-bad/40 bg-bad/20 px-2 py-1 text-xs font-medium hover:bg-bad/30"
              onClick={() => onRegenerate(m.id)}
            >
              Retry
            </button>
          )}
        </div>
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
          <button aria-label="Copy answer" className="rounded-lg p-1.5 hover:bg-sunk hover:text-ink" onClick={() => { navigator.clipboard.writeText(cleanedContent); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
            {copied ? <Check size={15} /> : <Copy size={15} />}
          </button>
          {onRegenerate && (
            <button
              title="Regenerate answer"
              aria-label="Regenerate answer"
              className="flex items-center gap-1 rounded-lg px-2 py-1 hover:bg-sunk hover:text-ink"
              onClick={() => onRegenerate(m.id)}
            >
              <RotateCcw size={14} /> <span className="text-xs">Regenerate</span>
            </button>
          )}
          <button className="flex items-center gap-1.5 rounded-lg px-2 py-1 hover:bg-sunk hover:text-ink" onClick={() => exportMemo(chatTitle, caseTitle, { ...m, content: cleanedContent })}>
            <Download size={15} /> Export memo
          </button>
          {m.executionId && <span className="ml-auto text-xs">Run {m.executionId}</span>}
        </div>
      )}
    </div>
  );
}
