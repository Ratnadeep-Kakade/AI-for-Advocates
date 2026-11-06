import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { BookOpen, Briefcase, FileSearch, Gavel, Pencil, Plus, Scale, ShieldQuestion, Sparkles } from "lucide-react";
import { useStore } from "../store";
import type { Message, TaskMode } from "../types";
import { streamChat } from "../lib/api";
import { applyEvent } from "../lib/events";
import { ingestFiles } from "../lib/ingest";
import { uid } from "../lib/util";
import Composer from "../components/Composer";
import MessageView from "../components/MessageView";
import EvidenceDrawer from "../components/EvidenceDrawer";
import { Badge, PageHeader } from "../components/ui";

const controllers = new Map<string, AbortController>();

const SUGGESTIONS: { icon: typeof Scale; title: string; prompt: string; mode: TaskMode; tag: string }[] = [
  { icon: Scale, tag: "Contracts", title: "Draft mutual NDA", prompt: "Draft a comprehensive mutual non-disclosure agreement with confidentiality obligations surviving 2 years.", mode: "auto" },
  { icon: BookOpen, tag: "Statutes", title: "Section 138 NI Act", prompt: "Explain the essential ingredients and director liability under Section 141 of the Negotiable Instruments Act.", mode: "research" },
  { icon: Gavel, tag: "Arbitration", title: "Challenge Arbitral Award", prompt: "What are the substantive grounds and timeline to set aside an arbitral award under Section 34 of the Arbitration and Conciliation Act?", mode: "arguments" },
  { icon: ShieldQuestion, tag: "Stress-Test", title: "Anticipate Opposing Strategy", prompt: "Analyze potential counter-arguments opposing counsel will raise against our material breach claim, and identify weak spots.", mode: "full" },
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
  const renameChat = useStore((s) => s.renameChat);
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

  async function send(overridePrompt?: string) {
    const prompt = (overridePrompt ?? draft).trim();
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
    if (!overridePrompt) setDraft("");
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

  async function regenerate(botMsgId: string) {
    if (!chat || busy) return;
    const botIdx = chat.messages.findIndex((m) => m.id === botMsgId);
    if (botIdx <= 0) return;
    const userMsg = chat.messages[botIdx - 1];
    if (!userMsg || userMsg.role !== "user") return;

    const st = useStore.getState();
    st.updateMessage(chat.id, botMsgId, (m) => ({
      ...m,
      content: "",
      status: "streaming",
      trace: [],
      evidence: [],
      error: undefined,
    }));

    const history = chat.messages
      .slice(0, botIdx - 1)
      .filter((m) => m.status !== "error")
      .map((m) => ({ role: m.role, content: m.content }));

    const ctrl = new AbortController();
    controllers.set(chat.id, ctrl);
    st.setBusy(chat.id, true);
    const upd = (fn: (m: Message) => Message) => useStore.getState().updateMessage(chat.id, botMsgId, fn);

    try {
      await streamChat(
        {
          chat_id: chat.id,
          case_id: caseId,
          prompt: userMsg.content,
          model: st.model,
          mode: st.mode,
          jurisdiction: theCase?.jurisdiction ?? st.jurisdiction,
          agent_models: st.agentModels,
          document_ids: caseDocs.map((d) => d.id),
          history,
        },
        (e) => upd((m) => applyEvent(m, e)),
        ctrl.signal
      );
      upd((m) => (m.status === "streaming" ? { ...m, status: "done" } : m));
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === "AbortError";
      upd((m) => (aborted ? { ...m, status: "done", content: m.content || "Stopped." } : { ...m, status: "error", error: err instanceof Error ? err.message : "Request failed." }));
    } finally {
      controllers.delete(chat.id);
      useStore.getState().setBusy(chat.id, false);
    }
  }

  function handleEditPrompt(promptText: string) {
    setDraft(promptText);
    const textarea = document.querySelector("textarea");
    if (textarea) {
      textarea.focus();
      textarea.selectionStart = textarea.selectionEnd = textarea.value.length;
    }
  }

  const drawerMsg = drawer ? messages.find((m) => m.id === drawer.messageId) : undefined;

  return (
    <>
      <PageHeader
        title={chat?.title ?? "New chat"}
        sub={theCase ? `${theCase.title} · ${caseDocs.length} document${caseDocs.length === 1 ? "" : "s"}` : "Cicero Legal Intelligence"}
      >
        {chat && (
          <button
            type="button"
            onClick={() => {
              const next = prompt("Enter new chat title:", chat.title);
              if (next && next.trim()) renameChat(chat.id, next.trim());
            }}
            className="flex items-center gap-1 rounded-lg border border-line bg-panel px-2.5 py-1 text-sm text-muted hover:border-accent hover:text-ink"
            title="Rename chat"
          >
            <Pencil size={13} />
            <span className="hidden sm:inline">Rename</span>
          </button>
        )}
        <button
          onClick={() => nav("/")}
          className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1 text-sm font-medium hover:border-accent hover:text-accent"
          title="Start fresh chat"
        >
          <Plus size={14} /> New chat
        </button>
        <label className="flex items-center gap-2 text-sm text-muted">
          <Briefcase size={15} />
          <select
            aria-label="Linked case"
            value={caseId ?? ""}
            onChange={(e) => (chat ? setChatCase(chat.id, e.target.value || undefined) : setPendingCase(e.target.value || undefined))}
            className="max-w-40 rounded-lg border border-line bg-panel px-2 py-1 text-sm text-ink sm:max-w-56"
          >
            <option value="">No case linked (General Chat)</option>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        </label>
      </PageHeader>

      <div ref={scroller} className="flex-1 overflow-y-auto" onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
        {messages.length === 0 ? (
          <div className="mx-auto flex min-h-full max-w-3xl flex-col justify-center px-4 py-10">
            <div className="flex items-center gap-2 text-accent">
              <Sparkles size={24} />
              <span className="font-serif text-sm font-medium tracking-wide uppercase">Cicero Legal AI</span>
            </div>
            <h2 className="mt-2 font-serif text-3xl font-semibold sm:text-4xl">How can I assist your legal work?</h2>
            <p className="mt-2 max-w-xl text-muted text-sm sm:text-base">
              Ask any question freely, draft clauses, verify statutory provisions, or link a case to ground answers in confidential documents.
            </p>
            <div className="mt-6 grid gap-2.5 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s.title}
                  onClick={() => {
                    setDraft(s.prompt);
                    setMode(s.mode);
                  }}
                  className="group flex flex-col gap-1.5 rounded-xl border border-line bg-panel p-3.5 text-left transition hover:border-accent hover:shadow-sm"
                >
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-xs font-semibold text-accent uppercase tracking-wider">
                      <s.icon size={14} /> {s.tag}
                    </span>
                  </div>
                  <span className="text-sm font-medium group-hover:text-accent transition-colors">{s.title}</span>
                  <span className="text-xs text-muted line-clamp-2">{s.prompt}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
            {messages.map((m) => (
              <MessageView
                key={m.id}
                m={m}
                chatTitle={chat?.title ?? "Memo"}
                caseTitle={theCase?.title}
                onSources={(activeId) => setDrawer({ messageId: m.id, activeId })}
                onRegenerate={regenerate}
                onEdit={handleEditPrompt}
              />
            ))}
          </div>
        )}
      </div>

      <div className="shrink-0 px-4 pb-3 pt-1">
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={() => send()}
          onStop={() => chatId && controllers.get(chatId)?.abort()}
          busy={busy}
          canAttach={!!caseId}
          onFiles={(f) => caseId && ingestFiles(caseId, f)}
        />
        <p className="mt-2 text-center text-xs text-muted">Privileged & confidential. Rigorous legal AI: verify all statutory provisions and authorities before formal citation.</p>
      </div>

      {drawer && drawerMsg && <EvidenceDrawer evidence={drawerMsg.evidence ?? []} activeId={drawer.activeId} onClose={() => setDrawer(null)} />}
    </>
  );
}
