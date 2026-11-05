import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Loader2, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { useStore } from "../store";
import type { CaseIntel } from "../types";
import { analyzeCase } from "../lib/api";
import { ingestFiles, syncCaseDocuments } from "../lib/ingest";
import { cx, fmtDate, fmtSize, fmtTime } from "../lib/util";
import DeadlineList from "../components/DeadlineList";
import { Badge, Empty, PageHeader, btn, btnPrimary } from "../components/ui";

const TABS = [
  { id: "overview", label: "Case intelligence" },
  { id: "documents", label: "Documents" },
  { id: "chats", label: "Chats" },
  { id: "deadlines", label: "Deadlines" },
  { id: "audit", label: "Audit trail" },
] as const;

function List({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="rounded-xl border border-line bg-panel p-4">
      <h3 className="mb-2 font-serif text-base font-semibold">{title}</h3>
      {items.length ? <ul className="list-disc space-y-1 pl-5 text-sm">{items.map((i) => <li key={i}>{i}</li>)}</ul> : <p className="text-sm text-muted">None found</p>}
    </section>
  );
}

function Intel({ intel }: { intel: CaseIntel }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <List title="Parties" items={intel.parties.map((p) => (p.role ? `${p.name} (${p.role})` : p.name))} />
      <List title="Important dates" items={intel.important_dates.map((d) => `${fmtDate(d.date)}: ${d.label}`)} />
      <List title="Contractual obligations" items={intel.contractual_obligations} />
      <List title="Material facts" items={intel.material_facts} />
      <List title="Legal issues" items={intel.legal_issues} />
      <List title="Contradictions across documents" items={intel.contradictions} />
      <div className="md:col-span-2"><List title="Missing information" items={intel.missing_information} /></div>
    </div>
  );
}

export default function CaseWorkspace() {
  const { caseId = "" } = useParams();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get("tab") ?? "overview") as (typeof TABS)[number]["id"];
  const { cases, docs, chats, updateCase, setIntel, deleteCase, removeDoc } = useStore();
  const c = cases.find((x) => x.id === caseId);
  const myDocs = docs.filter((d) => d.caseId === caseId);
  const myChats = chats.filter((x) => x.caseId === caseId).sort((a, b) => b.updatedAt - a.updatedAt);
  const [analyzing, setAnalyzing] = useState(false);
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!caseId) return;
    let active = true;

    const runSync = async () => {
      try {
        await syncCaseDocuments(caseId);
      } catch {
        // Ignore offline or transient network issues
      }
    };

    runSync();

    const timer = setInterval(() => {
      if (!active) return;
      const currentDocs = useStore.getState().docs.filter((d) => d.caseId === caseId);
      if (currentDocs.some((d) => d.status === "processing")) {
        runSync();
      }
    }, 5000);

    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [caseId]);

  if (!c) return <Navigate to="/cases" replace />;

  async function analyze() {
    setAnalyzing(true); setErr("");
    try { setIntel(caseId, await analyzeCase(caseId)); } catch (e) { setErr(e instanceof Error ? e.message : "Analysis failed"); }
    setAnalyzing(false);
  }

  return (
    <>
      <PageHeader title={c.title} sub={[c.client && `${c.client}${c.opposingParty ? ` v. ${c.opposingParty}` : ""}`, c.court, c.caseNumber, c.jurisdiction].filter(Boolean).join(", ")}>
        <Badge tone="neutral" title="Everything in this case is treated as confidential">Privileged</Badge>
        <select aria-label="Status" className={btn} value={c.status} onChange={(e) => updateCase(c.id, { status: e.target.value as typeof c.status })}>
          <option value="active">Active</option><option value="on-hold">On hold</option><option value="closed">Closed</option>
        </select>
        <button className={btnPrimary} onClick={() => nav(`/?case=${c.id}`)}><Plus size={15} /> New chat</button>
      </PageHeader>

      <nav className="flex shrink-0 gap-1 overflow-x-auto border-b border-line px-4" aria-label="Case sections">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setSp({ tab: t.id })} aria-current={tab === t.id} className={cx("whitespace-nowrap border-b-2 px-3 py-2.5 text-sm", tab === t.id ? "border-accent font-medium" : "border-transparent text-muted hover:text-ink")}>
            {t.label}
          </button>
        ))}
      </nav>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl px-4 py-6">
          {tab === "overview" && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <button className={btnPrimary} disabled={analyzing || myDocs.length === 0} onClick={analyze}>
                  {analyzing ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />} {c.intel ? "Re-analyze documents" : "Analyze documents"}
                </button>
                {myDocs.length === 0 && <span className="text-sm text-muted">Upload documents first.</span>}
                {err && <span role="alert" className="text-sm text-bad">{err}</span>}
              </div>
              {c.intel ? <Intel intel={c.intel} /> : <Empty title="No case intelligence yet">Analyze the documents to extract parties, dates, obligations, facts and contradictions.</Empty>}
              <div className="pt-6">
                <button className="text-sm text-bad hover:underline" onClick={() => { if (confirm(`Delete "${c.title}" and its documents and deadlines? Chats are kept.`)) { deleteCase(c.id); nav("/cases"); } }}>Delete this case</button>
              </div>
            </div>
          )}

          {tab === "documents" && (
            <div className="space-y-4">
              <div
                onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => { e.preventDefault(); setDrag(false); ingestFiles(c.id, Array.from(e.dataTransfer.files)); }}
                className={cx("flex flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center", drag ? "border-accent bg-accent-soft/40" : "border-line")}
              >
                <Upload size={22} className="text-muted" />
                <p className="text-sm">Drop contracts, notices, pleadings and orders here</p>
                <input ref={file} type="file" multiple hidden accept=".pdf,.docx,.txt,.png,.jpg,.jpeg" onChange={(e) => { ingestFiles(c.id, Array.from(e.target.files ?? [])); e.target.value = ""; }} />
                <button className={btn} onClick={() => file.current?.click()}>Choose files</button>
                <p className="text-xs text-muted">PDF, Word, text or scanned images</p>
              </div>
              {myDocs.length > 0 && (
                <ul className="divide-y divide-line rounded-xl border border-line bg-panel">
                  {myDocs.map((d) => (
                    <li key={d.id} className="flex items-center gap-3 px-3 py-2.5">
                      <div className="min-w-0 flex-1"><p className="truncate text-sm">{d.name}</p><p className="text-xs text-muted">{fmtSize(d.size)}, added {fmtDate(d.addedAt)}</p></div>
                      {d.status === "processing" && <Badge tone="warn"><Loader2 size={11} className="animate-spin" /> Processing</Badge>}
                      {d.status === "analyzed" && <Badge tone="ok">Ready</Badge>}
                      {d.status === "failed" && <Badge tone="bad">Upload failed</Badge>}
                      <button aria-label={`Remove ${d.name}`} className="rounded p-1 text-muted hover:text-bad" onClick={() => removeDoc(d.id)}><Trash2 size={15} /></button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {tab === "chats" &&
            (myChats.length === 0 ? (
              <Empty title="No chats for this case yet">Start a chat from the button at the top.</Empty>
            ) : (
              <ul className="divide-y divide-line rounded-xl border border-line bg-panel">
                {myChats.map((x) => (
                  <li key={x.id}><Link to={`/chat/${x.id}`} className="flex items-center justify-between px-4 py-3 text-sm hover:bg-sunk"><span className="truncate">{x.title}</span><span className="ml-3 shrink-0 text-xs text-muted">{fmtTime(x.updatedAt)}</span></Link></li>
                ))}
              </ul>
            ))}

          {tab === "deadlines" && <DeadlineList caseId={c.id} />}

          {tab === "audit" && <Audit caseId={c.id} />}
        </div>
      </div>
    </>
  );
}

// Every AI run on this case: when, which question, which agents and models, how well sourced.
function Audit({ caseId }: { caseId: string }) {
  const chats = useStore((s) => s.chats).filter((c) => c.caseId === caseId);
  const rows = chats.flatMap((c) =>
    c.messages.flatMap((m, i) => (m.role === "assistant" && m.status !== "streaming" ? [{ chat: c, m, q: c.messages[i - 1]?.content ?? "" }] : []))
  ).sort((a, b) => b.m.createdAt - a.m.createdAt);
  if (!rows.length) return <Empty title="No AI runs recorded">Each answer is logged here with its agents, model and source checks.</Empty>;
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-panel">
      <table className="w-full text-left text-sm">
        <thead className="bg-sunk text-muted"><tr>{["When", "Question", "Agents", "Model", "Sources", "Result"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">
          {rows.map(({ chat, m, q }) => {
            const ev = m.evidence ?? [];
            const bad = ev.filter((e) => e.verification !== "verified").length;
            const agents = [...new Set((m.trace ?? []).map((t) => t.agent))].length;
            return (
              <tr key={m.id}>
                <td className="whitespace-nowrap px-3 py-2 text-muted">{fmtTime(m.createdAt)}</td>
                <td className="max-w-xs truncate px-3 py-2"><Link className="hover:underline" to={`/chat/${chat.id}`}>{q}</Link></td>
                <td className="px-3 py-2">{agents}</td>
                <td className="whitespace-nowrap px-3 py-2">{m.model ?? "auto"}</td>
                <td className="whitespace-nowrap px-3 py-2">{ev.length} cited{bad > 0 && <span className="text-warn">, {bad} unverified</span>}</td>
                <td className="px-3 py-2"><Badge tone={m.status === "error" ? "bad" : "ok"}>{m.status === "error" ? "Failed" : "Complete"}</Badge></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
