import { useEffect, useRef } from "react";
import { ArrowUp, Paperclip, Square } from "lucide-react";
import { useStore } from "../store";
import { MODES } from "../types";
import { cx } from "../lib/util";
import ModelPicker from "./ModelPicker";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  canAttach: boolean;
  onFiles: (f: File[]) => void;
}

export default function Composer({ value, onChange, onSend, onStop, busy, canAttach, onFiles }: Props) {
  const { mode, setMode } = useStore();
  const ta = useRef<HTMLTextAreaElement>(null);
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 240) + "px";
  }, [value]);

  return (
    <div className="mx-auto w-full max-w-3xl rounded-2xl border border-line bg-panel p-2 shadow-sm focus-within:border-accent">
      <textarea
        ref={ta}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (!busy && value.trim()) onSend();
          }
        }}
        placeholder="Ask a legal question, or describe what you need for this matter"
        aria-label="Message"
        className="max-h-60 w-full resize-none bg-transparent px-2 py-2 text-[15px] outline-none placeholder:text-muted/70"
      />
      <div className="flex flex-wrap items-center gap-1 px-1 pt-1">
        <input ref={file} type="file" multiple hidden accept=".pdf,.docx,.txt,.png,.jpg,.jpeg" onChange={(e) => { onFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        <button disabled={!canAttach} onClick={() => file.current?.click()} title={canAttach ? "Add documents to this case" : "Link a case to attach documents"} aria-label="Attach documents" className="rounded-lg p-1.5 text-muted hover:bg-sunk hover:text-ink disabled:opacity-40">
          <Paperclip size={18} />
        </button>
        <div className="flex flex-1 flex-wrap gap-1" role="radiogroup" aria-label="Task type">
          {MODES.map((m) => (
            <button key={m.id} role="radio" aria-checked={mode === m.id} title={m.hint} onClick={() => setMode(m.id)} className={cx("rounded-full border px-2.5 py-0.5 text-xs", mode === m.id ? "border-accent bg-accent-soft text-accent" : "border-line text-muted hover:text-ink")}>
              {m.label}
            </button>
          ))}
        </div>
        <ModelPicker />
        {busy ? (
          <button onClick={onStop} aria-label="Stop" className="rounded-lg bg-ink p-2 text-page"><Square size={14} fill="currentColor" /></button>
        ) : (
          <button onClick={onSend} disabled={!value.trim()} aria-label="Send" className="rounded-lg bg-accent p-2 text-page hover:opacity-90 disabled:opacity-40"><ArrowUp size={16} /></button>
        )}
      </div>
    </div>
  );
}
