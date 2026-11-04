import { DEFAULT_MODELS } from "../types";
import type { Case, CaseIntel, ChatRequest, ModelOption, StreamEvent } from "../types";
import { mockAnalyze, mockStream } from "./mock";

const API = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/$/, "");
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true" || !API;
export const API_URL = API;


type ApiCase = {
  case_id: string;
  organization_id: string;
  case_name: string;
  case_description: string | null;
  jurisdiction: string | null;
  court: string | null;
  case_type: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

function toFrontendCase(row: ApiCase): Case {
  return {
    id: row.case_id,
    title: row.case_name,
    client: "",
    opposingParty: "",
    court: row.court ?? "",
    caseNumber: "",
    jurisdiction: row.jurisdiction ?? "",
    practiceArea: row.case_type ?? "General",
    status: row.status === "active" ? "active" : "closed",
    createdAt: Date.parse(row.created_at),
  };
}

async function readApiError(res: Response, fallback: string): Promise<Error> {
  try {
    const body = await res.json();
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    return new Error(detail || fallback);
  } catch {
    return new Error(`${fallback} (${res.status})`);
  }
}

/** Fetch cases from the authenticated demo-tenant API. */
export async function fetchCases(): Promise<Case[]> {
  if (USE_MOCK) throw new Error("Mock mode is enabled; refusing to present local cases as server data.");
  const res = await fetch(`${API}/api/cases`, { headers: { Accept: "application/json" } });
  if (!res.ok) throw await readApiError(res, "Could not load cases");
  const rows = (await res.json()) as ApiCase[];
  return rows.map(toFrontendCase);
}

/** Create a case in the backend and return its server-generated ID. */
export async function createCaseRemote(input: {
  title: string;
  client: string;
  opposingParty: string;
  court: string;
  jurisdiction: string;
  practiceArea: string;
}): Promise<Case> {
  if (USE_MOCK) throw new Error("Mock mode is enabled; refusing to create a local-only case.");
  const description = [
    input.client ? `Client: ${input.client}` : "",
    input.opposingParty ? `Opposing party: ${input.opposingParty}` : "",
  ].filter(Boolean).join("\n") || null;
  const res = await fetch(`${API}/api/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      case_name: input.title,
      case_description: description,
      jurisdiction: input.jurisdiction || null,
      court: input.court || null,
      case_type: input.practiceArea || null,
    }),
  });
  if (!res.ok) throw await readApiError(res, "Could not create case");
  return toFrontendCase((await res.json()) as ApiCase);
}

/**
 * POST /api/chat/stream  ->  text/event-stream
 * Each frame:   data: {"type":"token","text":"..."}\n\n   (see StreamEvent in types.ts)
 */
export async function streamChat(req: ChatRequest, onEvent: (e: StreamEvent) => void, signal: AbortSignal) {
  if (USE_MOCK) return mockStream(req, onEvent, signal);
  const res = await fetch(`${API}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(req),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`Backend returned ${res.status} ${res.statusText}`);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const data = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as StreamEvent);
    }
  }
}

/** POST /api/cases/{case_id}/documents (multipart, field "file") -> { id } */
export async function uploadDocument(caseId: string, file: File): Promise<{ id: string }> {
  if (USE_MOCK) {
    await new Promise((r) => setTimeout(r, 900));
    return { id: crypto.randomUUID() };
  }
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(`${API}/api/cases/${caseId}/documents`, { method: "POST", body });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  return res.json();
}

/** POST /api/cases/{case_id}/analyze -> CaseIntel */
export async function analyzeCase(caseId: string): Promise<CaseIntel> {
  if (USE_MOCK) return mockAnalyze(caseId);
  const res = await fetch(`${API}/api/cases/${caseId}/analyze`, { method: "POST" });
  if (!res.ok) throw new Error(`Analysis failed (${res.status})`);
  return res.json();
}

/** GET /api/models -> ModelOption[] */
export async function fetchModels(): Promise<ModelOption[]> {
  if (USE_MOCK) return DEFAULT_MODELS;
  try {
    const res = await fetch(`${API}/api/models`);
    if (!res.ok) throw new Error();
    return (await res.json()) as ModelOption[];
  } catch {
    return DEFAULT_MODELS;
  }
}
