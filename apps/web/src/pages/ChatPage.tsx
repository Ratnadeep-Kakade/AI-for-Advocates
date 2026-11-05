import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Briefcase, FileSearch, Gavel, Scale, ShieldQuestion } from "lucide-react";
import { useStore } from "../store";
import type { Message, TaskMode } from "../types";
import { streamChat } from "../lib/api";
import { applyEvent } from "../lib/events";
import { ingestFiles } from "../lib/ingest";
import { uid } from "../lib/util";
import Composer from "../components/Composer";
import MessageView from "../components/MessageView";
import EvidenceDrawer from "../components/EvidenceDrawer";
import { PageHeader } from "../components/ui";

const controllers = new Map<string, AbortController>();

const SUGGESTIONS: { icon: typeof Scale; title: string; prompt: string; mode: TaskMode }[] = [
  { icon: Scale, title: "Check a clause", prompt: "Is the immediate termination clause enforceable on these facts?", mode: "research" },
  { icon: FileSearch, title: "Read the documents", prompt: "Extract the parties, key dates, obligations and contradictions from the uploaded documents.", mode: "analyze" },
  { icon: Gavel, title: "Build the argument", prompt: "Build the strongest argument that the termination was wrongful, with supporting authorities.", mode: "arguments" },
  { icon: ShieldQuestion, title: "Stress-test our position", prompt: "What will opposing counsel argue, and where is our position weakest?", mode: "full" },
];

export default function ChatPage() {
  const { chatId } = useParams();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const chat = useStore((s) => s.chats.find((c) => c.id === chatId));
  const cases = useStore((s) => s.cases);
  const docs = useStore((s) => s.docs);
  const busy = useStore((s) => (chatId ? !!s.busy[chatId] : false));
  const setChatCase = useStore((s) => s.setChatCase);
  const setMode = useStore((s) => s.setMode);

  const [draft, setDraft] = useState("");
  const [pendingCase, setPendingCase] = useState<string | undefined>(params.get("case") ?? undefined);
  const [drawer, setDrawer] = useState<{ messageId: string; activeId?: string } | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const caseId = chat ? chat.caseId : pendingCase;
  const theCase = cases.find((c) => c.id === caseId);
  const caseDocs = docs.filter((d) => d.caseId === caseId && d.status !== "failed");
  const messages = chat?.messages ?? [];

  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [chat?.messages]);

  async function send() {
    const prompt = draft.trim();
    if (!prompt) return;
    const st = useStore.getState();
    const id = chat?.id ?? st.createChat(pendingCase);
    if (!chat) nav(`/chat/${id}`, { replace: true });
    const history = (chat?.messages ?? []).filter((m) => m.status !== "error").map((m) => ({ role: m.role, content: m.content }));
    const now = Date.now();
    const aId = uid();
    const userMsg: Message = { id: uid(), role: "user", content: prompt, createdAt: now };
    const botMsg: Message = { id: aId, role: "assistant", content: "", createdAt: now, status: "streaming", model: st.model, mode: st.mode, trace: [], evidence: [] };
    st.addMessages(id, [userMsg, botMsg]);
    setDraft("");
    stick.current = true;
    st.setBusy(id, true);
    const ctrl = new AbortController();
    controllers.set(id, ctrl);
    const upd = (fn: (m: Message) => Message) => useStore.getState().updateMessage(id, aId, fn);
    try {
      await streamChat(
        {
          chat_id: id, case_id: caseId, prompt, model: st.model, mode: st.mode, jurisdiction: theCase?.jurisdiction ?? st.jurisdiction,
          agent_models: st.agentModels, document_ids: caseDocs.map((d) => d.id), history,
        },
        (e) => upd((m) => applyEvent(m, e)),
        ctrl.signal
      );
      upd((m) => (m.status === "streaming" ? { ...m, status: "done" } : m));
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === "AbortError";
      upd((m) => (aborted ? { ...m, status: "done", content: m.content || "Stopped." } : { ...m, status: "error", error: err instanceof Error ? err.message : "Request failed." }));
    } finally {
      controllers.delete(id);
      useStore.getState().setBusy(id, false);
    }
  }

  const drawerMsg = drawer ? messages.find((m) => m.id === drawer.messageId) : undefined;

  return (
    <>
      <PageHeader title={chat?.title ?? "New chat"} sub={theCase ? `${caseDocs.length} document${caseDocs.length === 1 ? "" : "s"} in context` : undefined}>
        <label className="flex items-center gap-2 text-sm text-muted">
          <Briefcase size={15} />
          <select
            aria-label="Linked case"
            value={caseId ?? ""}
            onChange={(e) => (chat ? setChatCase(chat.id, e.target.value || undefined) : setPendingCase(e.target.value || undefined))}
            className="max-w-40 rounded-lg border border-line bg-panel px-2 py-1 text-sm text-ink sm:max-w-56"
          >
            <option value="">No case linked</option>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        </label>
      </PageHeader>

      <div ref={scroller} className="flex-1 overflow-y-auto" onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
        {messages.length === 0 ? (
          <div className="mx-auto flex min-h-full max-w-3xl flex-col justify-center px-4 py-10">
            <h2 className="font-serif text-3xl font-semibold sm:text-4xl">What are we working on?</h2>
            <p className="mt-2 max-w-xl text-muted">
              Every answer cites its sources, marks which ones are verified, and shows the argument against your position.
            </p>
            <div className="mt-6 grid gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button key={s.title} onClick={() => { setDraft(s.prompt); setMode(s.mode); }} className="flex gap-3 rounded-xl border border-line bg-panel p-3 text-left hover:border-accent">
                  <s.icon size={18} className="mt-0.5 shrink-0 text-accent" />
                  <span><span className="block text-sm font-medium">{s.title}</span><span className="block text-sm text-muted">{s.prompt}</span></span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
            {messages.map((m) => (
              <MessageView key={m.id} m={m} chatTitle={chat?.title ?? "Memo"} caseTitle={theCase?.title} onSources={(activeId) => setDrawer({ messageId: m.id, activeId })} />
            ))}
          </div>
        )}
      </div>

      <div className="shrink-0 px-4 pb-3 pt-1">
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={send}
          onStop={() => chatId && controllers.get(chatId)?.abort()}
          busy={busy}
          canAttach={!!caseId}
          onFiles={(f) => caseId && ingestFiles(caseId, f)}
        />
        <p className="mt-2 text-center text-xs text-muted">Privileged and confidential. AI can be wrong: verify every authority before you cite it.</p>
      </div>

      {drawer && drawerMsg && <EvidenceDrawer evidence={drawerMsg.evidence ?? []} activeId={drawer.activeId} onClose={() => setDrawer(null)} />}
    </>
  );
}
