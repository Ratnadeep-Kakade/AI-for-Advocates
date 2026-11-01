import { useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Trash2 } from "lucide-react";
import { useStore } from "../store";
import type { Deadline } from "../types";
import { cx, daysUntil, fmtDate } from "../lib/util";
import { Badge, Empty, btnPrimary, input } from "./ui";
import type { Tone } from "./ui";

const kinds: Deadline["kind"][] = ["hearing", "filing", "limitation", "other"];

function when(date: string, done: boolean): [string, Tone] {
  if (done) return ["Done", "neutral"];
  const n = daysUntil(date);
  if (n < 0) return [`Overdue by ${-n} day${n === -1 ? "" : "s"}`, "bad"];
  if (n === 0) return ["Today", "bad"];
  if (n <= 7) return [`In ${n} day${n === 1 ? "" : "s"}`, "warn"];
  return [`In ${n} days`, "neutral"];
}

export default function DeadlineList({ caseId }: { caseId?: string }) {
  const { deadlines, cases, addDeadline, toggleDeadline, removeDeadline } = useStore();
  const [f, setF] = useState({ title: "", date: "", kind: "hearing" as Deadline["kind"], caseId: caseId ?? "" });
  const list = deadlines
    .filter((d) => !caseId || d.caseId === caseId)
    .sort((a, b) => Number(a.done) - Number(b.done) || a.date.localeCompare(b.date));

  return (
    <div className="space-y-4">
      <form
        className="grid gap-2 rounded-xl border border-line bg-panel p-3 sm:grid-cols-[1fr_auto_auto_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          if (!f.title.trim() || !f.date) return;
          addDeadline({ title: f.title.trim(), date: f.date, kind: f.kind, caseId: f.caseId || undefined });
          setF({ ...f, title: "", date: "" });
        }}
      >
        <input className={input} placeholder="Hearing, filing or limitation date" aria-label="Deadline title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <input className={input} type="date" aria-label="Date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
        <select className={input} aria-label="Type" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as Deadline["kind"] })}>
          {kinds.map((k) => <option key={k} value={k}>{k[0].toUpperCase() + k.slice(1)}</option>)}
        </select>
        <button className={btnPrimary} type="submit"><Plus size={15} /> Add</button>
        {!caseId && (
          <select className={cx(input, "sm:col-span-4")} aria-label="Case" value={f.caseId} onChange={(e) => setF({ ...f, caseId: e.target.value })}>
            <option value="">Not linked to a case</option>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        )}
      </form>

      {list.length === 0 ? (
        <Empty title="No deadlines yet">Add hearing dates, filing dates and limitation periods so nothing is missed.</Empty>
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line bg-panel">
          {list.map((d) => {
            const [label, tone] = when(d.date, d.done);
            const c = cases.find((x) => x.id === d.caseId);
            return (
              <li key={d.id} className="flex items-center gap-3 px-3 py-2.5">
                <input type="checkbox" checked={d.done} onChange={() => toggleDeadline(d.id)} aria-label={`Mark ${d.title} done`} className="h-4 w-4 accent-[var(--accent)]" />
                <div className="min-w-0 flex-1">
                  <p className={cx("truncate text-sm", d.done && "text-muted line-through")}>{d.title}</p>
                  <p className="truncate text-xs text-muted">
                    {fmtDate(d.date)}, {d.kind}
                    {!caseId && c && <> for <Link className="underline" to={`/cases/${c.id}`}>{c.title}</Link></>}
                  </p>
                </div>
                <Badge tone={tone}>{label}</Badge>
                <button aria-label={`Delete ${d.title}`} onClick={() => removeDeadline(d.id)} className="rounded p-1 text-muted hover:text-bad"><Trash2 size={15} /></button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
