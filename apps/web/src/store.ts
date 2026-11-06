import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { AGENT_IDS, DEFAULT_MODELS } from "./types";
import type { AgentId, Case, CaseDoc, CaseIntel, Chat, Deadline, Message, ModelOption, TaskMode } from "./types";
import { uid } from "./lib/util";
import { deleteCaseRemote, deleteChatRemote, updateCaseRemote } from "./lib/api";

type Theme = "system" | "light" | "dark";

interface State {
  theme: Theme;
  model: string;
  mode: TaskMode;
  models: ModelOption[];
  agentModels: Record<AgentId, string>;
  jurisdiction: string;
  cases: Case[];
  chats: Chat[];
  docs: CaseDoc[];
  deadlines: Deadline[];
  busy: Record<string, boolean>; // not persisted
  sidebarOpen: boolean; // not persisted

  setTheme: (t: Theme) => void;
  setModel: (m: string) => void;
  setMode: (m: TaskMode) => void;
  setModels: (m: ModelOption[]) => void;
  setAgentModel: (a: AgentId, m: string) => void;
  setJurisdiction: (j: string) => void;
  setBusy: (chatId: string, b: boolean) => void;
  setSidebar: (o: boolean) => void;

  setCases: (cases: Case[]) => void;
  createCase: (c: Omit<Case, "id" | "createdAt" | "status">) => string;
  updateCase: (id: string, patch: Partial<Case>) => void;
  setIntel: (id: string, intel: CaseIntel) => void;
  deleteCase: (id: string) => void;

  setCaseDocs: (caseId: string, docs: CaseDoc[]) => void;
  addDoc: (d: CaseDoc) => void;
  patchDoc: (id: string, patch: Partial<CaseDoc>) => void;
  removeDoc: (id: string) => void;

  createChat: (caseId?: string) => string;
  renameChat: (id: string, title: string) => void;
  deleteChat: (id: string) => void;
  setChatCase: (id: string, caseId?: string) => void;
  addMessages: (chatId: string, msgs: Message[]) => void;
  updateMessage: (chatId: string, msgId: string, fn: (m: Message) => Message) => void;

  addDeadline: (d: Omit<Deadline, "id" | "done">) => void;
  toggleDeadline: (id: string) => void;
  removeDeadline: (id: string) => void;
  resetAll: () => void;
}

const defaultAgentModels = Object.fromEntries(
  AGENT_IDS.map((a) => [a, a === "orchestrator" || a === "evaluator" ? "muse-spark-1.3" : "auto"])
) as Record<AgentId, string>;

// Debounce localStorage writes so streaming tokens don't hammer it.
let timer: number | undefined;
const storage = createJSONStorage(() => ({
  getItem: (k: string) => localStorage.getItem(k),
  removeItem: (k: string) => localStorage.removeItem(k),
  setItem: (k: string, v: string) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => localStorage.setItem(k, v), 400);
  },
}));

export const useStore = create<State>()(
  persist(
    (set) => ({
      theme: "system",
      model: "auto",
      mode: "auto",
      models: DEFAULT_MODELS,
      agentModels: defaultAgentModels,
      jurisdiction: "India",
      cases: [],
      chats: [],
      docs: [],
      deadlines: [],
      busy: {},
      sidebarOpen: false,

      setTheme: (theme) => set({ theme }),
      setModel: (model) => set({ model }),
      setMode: (mode) => set({ mode }),
      setModels: (models) => set({ models }),
      setAgentModel: (a, m) => set((s) => ({ agentModels: { ...s.agentModels, [a]: m } })),
      setJurisdiction: (jurisdiction) => set({ jurisdiction }),
      setBusy: (chatId, b) => set((s) => ({ busy: { ...s.busy, [chatId]: b } })),
      setSidebar: (sidebarOpen) => set({ sidebarOpen }),

      setCases: (cases) =>
        set((state) => {
          const existingIntel = new Map(state.cases.map((c) => [c.id, c.intel]));
          return {
            cases: cases.map((c) => ({
              ...c,
              intel: c.intel || existingIntel.get(c.id),
            })),
          };
        }),
      createCase: (c) => {
        const id = uid();
        set((s) => ({ cases: [{ ...c, id, status: "active", createdAt: Date.now() }, ...s.cases] }));
        return id;
      },
      updateCase: (id, patch) => {
        updateCaseRemote(id, {
          title: patch.title,
          court: patch.court,
          jurisdiction: patch.jurisdiction,
          practiceArea: patch.practiceArea,
          status: patch.status,
        }).catch(() => {});
        set((s) => ({ cases: s.cases.map((c) => (c.id === id ? { ...c, ...patch } : c)) }));
      },
      setIntel: (id, intel) => set((s) => ({ cases: s.cases.map((c) => (c.id === id ? { ...c, intel } : c)) })),
      deleteCase: (id) => {
        deleteCaseRemote(id).catch(() => {});
        set((s) => ({
          cases: s.cases.filter((c) => c.id !== id),
          docs: s.docs.filter((d) => d.caseId !== id),
          deadlines: s.deadlines.filter((d) => d.caseId !== id),
          chats: s.chats.map((c) => (c.caseId === id ? { ...c, caseId: undefined } : c)),
        }));
      },

      setCaseDocs: (caseId, newDocs) =>
        set((s) => ({
          docs: [...s.docs.filter((d) => d.caseId !== caseId), ...newDocs],
        })),
      addDoc: (d) =>
        set((s) => {
          const idx = s.docs.findIndex((x) => x.id === d.id);
          if (idx >= 0) {
            const copy = [...s.docs];
            copy[idx] = { ...copy[idx], ...d };
            return { docs: copy };
          }
          return { docs: [d, ...s.docs] };
        }),
      patchDoc: (id, patch) => set((s) => ({ docs: s.docs.map((d) => (d.id === id ? { ...d, ...patch } : d)) })),
      removeDoc: (id) => set((s) => ({ docs: s.docs.filter((d) => d.id !== id) })),

      createChat: (caseId) => {
        const id = uid();
        const now = Date.now();
        set((s) => ({ chats: [{ id, title: "New chat", caseId, createdAt: now, updatedAt: now, messages: [] }, ...s.chats] }));
        return id;
      },
      renameChat: (id, title) =>
        set((s) => ({
          chats: s.chats.map((c) => (c.id === id ? { ...c, title: title.trim() || c.title, updatedAt: Date.now() } : c)),
        })),
      deleteChat: (id) => {
        deleteChatRemote(id).catch(() => {});
        set((s) => ({ chats: s.chats.filter((c) => c.id !== id) }));
      },
      setChatCase: (id, caseId) => set((s) => ({ chats: s.chats.map((c) => (c.id === id ? { ...c, caseId } : c)) })),
      addMessages: (chatId, msgs) =>
        set((s) => ({
          chats: s.chats.map((c) => {
            if (c.id !== chatId) return c;
            const first = c.messages.length === 0 ? msgs.find((m) => m.role === "user") : undefined;
            return {
              ...c,
              title: first ? first.content.replace(/\s+/g, " ").slice(0, 48) : c.title,
              updatedAt: Date.now(),
              messages: [...c.messages, ...msgs],
            };
          }),
        })),
      updateMessage: (chatId, msgId, fn) =>
        set((s) => ({
          chats: s.chats.map((c) =>
            c.id !== chatId ? c : { ...c, updatedAt: Date.now(), messages: c.messages.map((m) => (m.id === msgId ? fn(m) : m)) }
          ),
        })),

      addDeadline: (d) => set((s) => ({ deadlines: [...s.deadlines, { ...d, id: uid(), done: false }] })),
      toggleDeadline: (id) => set((s) => ({ deadlines: s.deadlines.map((d) => (d.id === id ? { ...d, done: !d.done } : d)) })),
      removeDeadline: (id) => set((s) => ({ deadlines: s.deadlines.filter((d) => d.id !== id) })),
      resetAll: () => set({ cases: [], chats: [], docs: [], deadlines: [] }),
    }),
    {
      name: "counsel-v1",
      storage,
      partialize: (s) => ({
        theme: s.theme, model: s.model, mode: s.mode, agentModels: s.agentModels, jurisdiction: s.jurisdiction,
        cases: s.cases, chats: s.chats, docs: s.docs, deadlines: s.deadlines,
      }),
      merge: (persisted, current) => {
        const merged = { ...current, ...(persisted as Partial<State>) };
        // A reload kills any in-flight stream; don't leave messages stuck as "streaming".
        merged.chats = merged.chats.map((c) => ({
          ...c,
          messages: c.messages.map((m) => (m.status === "streaming" ? { ...m, status: "error" as const, error: "Interrupted by a page reload" } : m)),
        }));
        return merged;
      },
    }
  )
);
