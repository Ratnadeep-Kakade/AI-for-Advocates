import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileText, MessageSquare, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { useStore } from "../store";
import { createCaseRemote, fetchCases, USE_MOCK } from "../lib/api";
import { daysUntil, fmtDate } from "../lib/util";
import { Badge, Empty, Field, Modal, PageHeader, btnPrimary, input } from "../components/ui";

export default function CasesPage() {
  const nav = useNavigate();
  const { cases, docs, chats, deadlines, setCases, updateCase, deleteCase, jurisdiction } = useStore();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(cases.length === 0);
    fetchCases()
      .then((rows) => { if (!cancelled) setCases(rows); })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load cases"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [setCases, cases.length]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const blank = { title: "", client: "", opposingParty: "", court: "", caseNumber: "", jurisdiction, practiceArea: "" };
  const [f, setF] = useState(blank);
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const list = cases.filter((c) => [c.title, c.client, c.opposingParty, c.caseNumber].join(" ").toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <PageHeader title="Cases" sub="Each case keeps its documents, research, deadlines and audit trail together">
        <button className={btnPrimary} onClick={() => { setF(blank); setOpen(true); }}><Plus size={15} /> New case</button>
      </PageHeader>
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-4 px-4 py-6">
          <div className="relative max-w-sm">
            <Search size={15} className="absolute left-3 top-3 text-muted" />
            <input className={input + " pl-9"} placeholder="Search by title, client, party or case number" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {USE_MOCK && <div className="rounded-lg border border-warn/30 bg-warn/10 p-3 text-sm">Mock mode is enabled. Server-backed case management is disabled.</div>}
          {error && <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm">Could not load cases: {error}</div>}
          {loading ? (
            <div className="py-12 text-center text-sm text-muted">Loading cases from Cicero...</div>
          ) : list.length === 0 ? (
            <Empty title={cases.length ? "No cases match that search" : "No cases yet"}>
              {cases.length ? "Try a different name or case number." : "Create a case to upload its documents and run research against them."}
            </Empty>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((c) => {
                const next = deadlines.filter((d) => d.caseId === c.id && !d.done).sort((a, b) => a.date.localeCompare(b.date))[0];
                return (
                  <Link key={c.id} to={`/cases/${c.id}`} className="rounded-xl border border-line bg-panel p-4 hover:border-accent">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="font-serif text-lg font-semibold leading-snug">{c.title}</h3>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <Badge tone={c.status === "active" ? "ok" : "neutral"}>{c.status}</Badge>
                        <button
                          type="button"
                          aria-label={`Rename case ${c.title}`}
                          title="Rename case"
                          className="rounded p-1 text-muted hover:text-accent"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            const next = prompt("Enter new case title:", c.title);
                            if (next && next.trim()) updateCase(c.id, { title: next.trim() });
                          }}
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete case ${c.title}`}
                          title="Delete case"
                          className="rounded p-1 text-muted hover:text-bad"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            if (confirm(`Permanently delete "${c.title}" and all its documents, pgvector embeddings, and data from PostgreSQL?`)) {
                              deleteCase(c.id);
                            }
                          }}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>
                    <p className="mt-1 text-sm text-muted">{c.client || "No client"}{c.opposingParty && ` v. ${c.opposingParty}`}</p>
                    <p className="text-sm text-muted">{[c.court, c.caseNumber].filter(Boolean).join(", ")}</p>
                    <div className="mt-3 flex items-center gap-3 text-xs text-muted">
                      <span className="flex items-center gap-1"><FileText size={13} />{docs.filter((d) => d.caseId === c.id).length}</span>
                      <span className="flex items-center gap-1"><MessageSquare size={13} />{chats.filter((x) => x.caseId === c.id).length}</span>
                      {next && <span className={daysUntil(next.date) <= 7 ? "text-warn" : ""}>Next: {next.title}, {fmtDate(next.date)}</span>}
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {open && (
        <Modal title="New case" onClose={() => setOpen(false)}>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!f.title.trim() || saving) return;
              setSaving(true);
              setError(null);
              createCaseRemote({ ...f, title: f.title.trim() })
                .then((created) => {
                  setCases([created, ...useStore.getState().cases.filter((item) => item.id !== created.id)]);
                  setOpen(false);
                  nav(`/cases/${created.id}`);
                })
                .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not create case"))
                .finally(() => setSaving(false));
            }}
          >
            <Field label="Case title"><input autoFocus required className={input} placeholder="e.g. Acme v. Zenith, termination dispute" value={f.title} onChange={set("title")} /></Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Client"><input className={input} value={f.client} onChange={set("client")} /></Field>
              <Field label="Opposing party"><input className={input} value={f.opposingParty} onChange={set("opposingParty")} /></Field>
              <Field label="Court or forum"><input className={input} value={f.court} onChange={set("court")} /></Field>
              <Field label="Jurisdiction"><input className={input} value={f.jurisdiction} onChange={set("jurisdiction")} /></Field>
              <Field label="Practice area"><input className={input} placeholder="Commercial, family, tax" value={f.practiceArea} onChange={set("practiceArea")} /></Field>
            </div>
            <div className="flex justify-end pt-2"><button type="submit" disabled={saving} className={btnPrimary}>{saving ? "Creating..." : "Create case"}</button></div>
          </form>
        </Modal>
      )}
    </>
  );
}
