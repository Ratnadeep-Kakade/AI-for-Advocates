import { DEFAULT_MODELS } from "../types";
import type { AgentId, Case, CaseIntel, ChatRequest, ModelOption, StreamEvent } from "../types";
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

/** PATCH /api/cases/{case_id} -> update case details (e.g. rename). */
export async function updateCaseRemote(
  caseId: string,
  patch: {
    title?: string;
    description?: string;
    jurisdiction?: string;
    court?: string;
    practiceArea?: string;
    status?: string;
  }
): Promise<Case> {
  if (USE_MOCK) {
    throw new Error("Mock mode is enabled; server updates disabled.");
  }
  const payload: Record<string, string | undefined> = {};
  if (patch.title !== undefined) payload.case_name = patch.title;
  if (patch.description !== undefined) payload.case_description = patch.description;
  if (patch.jurisdiction !== undefined) payload.jurisdiction = patch.jurisdiction;
  if (patch.court !== undefined) payload.court = patch.court;
  if (patch.practiceArea !== undefined) payload.case_type = patch.practiceArea;
  if (patch.status !== undefined) payload.status = patch.status;

  const res = await fetch(`${API}/api/cases/${caseId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await readApiError(res, "Could not update case");
  return toFrontendCase((await res.json()) as ApiCase);
}

/** DELETE /api/cases/{case_id} -> permanently delete case and all associated Postgres + pgvector data. */
export async function deleteCaseRemote(caseId: string): Promise<void> {
  if (USE_MOCK) return;
  const res = await fetch(`${API}/api/cases/${caseId}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!res.ok && res.status !== 404) {
    throw await readApiError(res, "Could not delete case");
  }
}

/** DELETE /api/chat/{chat_id} -> delete chat execution records and traces from PostgreSQL. */
export async function deleteChatRemote(chatId: string): Promise<void> {
  if (USE_MOCK) return;
  const res = await fetch(`${API}/api/chat/${chatId}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!res.ok && res.status !== 404) {
    throw await readApiError(res, "Could not delete chat");
  }
}

/**
 * POST /api/chat/stream  ->  text/event-stream
 * Each frame:   data: {"type":"token","text":"..."}\n\n   (see StreamEvent in types.ts)
 */
interface ExecutionTaskState {
  task_id: string;
  agent_id: string;
  status: string;
  depends_on: string[];
}

interface ExecutionDetail {
  execution_id: string;
  status: string;
  final_response: string | null;
  error: string | null;
  clarification_questions: string[];
  tasks: ExecutionTaskState[];
  results: Record<
    string,
    {
      agent_id: string;
      status: string;
      validation_status: string;
      output_data: Record<string, unknown>;
      evidence_references: string[];
    }
  >;
}

const AGENT_ID_MAP: Record<string, AgentId> = {
  document_intelligence: "analyzer",
  legal_researcher: "researcher",
  argument: "argument",
  counterargument: "counterargument",
  evaluator: "evaluator",
  orchestrator: "orchestrator",
};

const AGENT_LABEL: Record<string, string> = {
  document_intelligence: "Document Intelligence",
  legal_researcher: "Legal Researcher",
  argument: "Argument Agent",
  counterargument: "Counterargument Agent",
  evaluator: "Evaluator",
};

function abortError(): DOMException {
  return new DOMException("Aborted", "AbortError");
}

/**
 * High-performance streaming chat using real-time SSE (/api/chat/stream).
 * Works seamlessly with or without a case attached.
 */
export async function streamChat(req: ChatRequest, onEvent: (e: StreamEvent) => void, signal: AbortSignal) {
  if (USE_MOCK) return mockStream(req, onEvent, signal);

  try {
    const res = await fetch(`${API}/api/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        prompt: req.prompt,
        chat_id: req.chat_id,
        case_id: req.case_id || null,
        model: req.model,
        mode: req.mode,
        jurisdiction: req.jurisdiction,
        history: req.history,
        document_ids: req.document_ids,
      }),
      signal,
    });

    if (!res.ok) {
      throw await readApiError(res, "Could not start chat stream");
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error("No readable stream response from server.");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      if (signal.aborted) throw abortError();
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;
        const jsonStr = trimmed.slice(6);
        try {
          const event = JSON.parse(jsonStr) as StreamEvent;
          onEvent(event);
        } catch {
          // Ignore partial frames
        }
      }
    }

    if (buffer.trim().startsWith("data: ")) {
      try {
        const event = JSON.parse(buffer.trim().slice(6)) as StreamEvent;
        onEvent(event);
      } catch {
        // Ignore
      }
    }
  } catch (err) {
    if (signal.aborted) throw abortError();
    // Fall back to case-execution polling if /api/chat/stream is unavailable and a case was provided
    if (req.case_id && (!res_status_ok(err))) {
      return streamCaseExecution(req, onEvent, signal);
    }
    throw err;
  }
}

function res_status_ok(err: unknown): boolean {
  return false;
}

/** Fallback for dedicated deep-agent background executions */
async function streamCaseExecution(req: ChatRequest, onEvent: (e: StreamEvent) => void, signal: AbortSignal) {
  const createRes = await fetch(`${API}/api/cases/${req.case_id}/executions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ user_request: req.prompt }),
    signal,
  });
  if (!createRes.ok) throw await readApiError(createRes, "Could not start the analysis");
  const created = (await createRes.json()) as { execution_id: string; status: string };
  onEvent({ type: "execution", executionId: created.execution_id });

  const seenTaskStatus = new Map<string, string>();
  const seenEvidence = new Set<string>();
  for (;;) {
    if (signal.aborted) throw abortError();
    await new Promise((r) => setTimeout(r, 3000));
    if (signal.aborted) throw abortError();
    const res = await fetch(`${API}/api/cases/${req.case_id}/executions/${created.execution_id}`, {
      headers: { Accept: "application/json" },
      signal,
    });
    if (!res.ok) throw await readApiError(res, "Could not load execution status");
    const detail = (await res.json()) as ExecutionDetail;

    for (const task of detail.tasks) {
      if (seenTaskStatus.get(task.task_id) === task.status) continue;
      seenTaskStatus.set(task.task_id, task.status);
      const agent = AGENT_ID_MAP[task.agent_id] ?? "orchestrator";
      const label = AGENT_LABEL[task.agent_id] ?? task.agent_id;
      if (task.status === "running") {
        onEvent({ type: "agent_start", agent, text: `${label} running` });
      } else if (task.status === "completed" || task.status === "partial" || task.status === "failed") {
        onEvent({ type: "step", agent, text: `${label} ${task.status}` });
      }
    }

    if (detail.status === "waiting_for_input") {
      const questions = detail.clarification_questions.length
        ? detail.clarification_questions.map((q) => `- ${q}`).join("\n")
        : "Could you clarify your request?";
      onEvent({ type: "token", text: `I need a bit more information before I can run this analysis:\n${questions}` });
      onEvent({ type: "done" });
      return;
    }
    if (detail.status === "failed") {
      throw new Error(detail.error || "The analysis execution failed.");
    }
    if (detail.status === "completed") {
      for (const result of Object.values(detail.results)) {
        const items = (result.output_data?.evidence_items ?? []) as Array<Record<string, unknown>>;
        for (const item of items) {
          const key = String(item.key ?? "");
          if (!key || seenEvidence.has(key)) continue;
          seenEvidence.add(key);
          onEvent({
            type: "evidence",
            evidence: {
              id: key,
              kind: "document",
              title: String(item.clause_label || item.filename || "Case document"),
              authority: "case-document",
              verification: "verified",
              passage: String(item.full_quote ?? item.quote ?? ""),
              source: `${String(item.filename ?? "")} · p.${String(item.page ?? "")}`,
            },
          });
        }
      }
      if (detail.final_response) onEvent({ type: "token", text: detail.final_response });
      onEvent({ type: "done" });
      return;
    }
  }
}

export interface ApiDocument {
  document_id: string;
  case_id: string;
  title: string;
  document_type: string | null;
  status: string;
  version_id: string;
  version_number: number;
  original_filename: string;
  mime_type: string;
  file_size: number;
  processing_run_id: string;
  processing_status: string;
  processing_stage?: string | null;
}

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function contentTypeFor(file: File): string {
  if (file.type) return file.type;
  const name = file.name.toLowerCase();
  if (name.endsWith(".pdf")) return "application/pdf";
  if (name.endsWith(".docx")) return DOCX_MIME;
  return "application/octet-stream";
}

/**
 * Direct-to-GCS upload (backend-issued signed URL):
 * POST .../documents/upload-url -> PUT file to GCS -> POST .../documents/complete.
 * The file bytes never pass through the Modal backend.
 */
export async function uploadDocument(
  caseId: string,
  file: File,
  onProgress?: (stage: string) => void
): Promise<{ id: string; processingStatus: string; processingStage?: string | null }> {
  if (USE_MOCK) {
    onProgress?.("Uploading");
    await new Promise((r) => setTimeout(r, 600));
    onProgress?.("Chunking");
    await new Promise((r) => setTimeout(r, 500));
    return { id: crypto.randomUUID(), processingStatus: "completed", processingStage: "Processed" };
  }
  const contentType = contentTypeFor(file);
  onProgress?.("Uploading");

  // Primary path: Direct upload to backend API (reliable, fast, immune to browser GCS CORS)
  try {
    const directRes = await fetch(
      `${API}/api/cases/${caseId}/documents/upload?filename=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        headers: {
          "Content-Type": contentType,
          "X-Filename": encodeURIComponent(file.name),
          Accept: "application/json",
        },
        body: file,
      }
    );
    if (directRes.ok) {
      onProgress?.("Chunking");
      const doc = (await directRes.json()) as ApiDocument;
      return { id: doc.document_id, processingStatus: doc.processing_status, processingStage: doc.processing_stage };
    }
  } catch (err) {
    console.warn("Direct upload failed, attempting signed URL fallback...", err);
  }

  // Fallback path: Pre-signed GCS URL
  const urlRes = await fetch(`${API}/api/cases/${caseId}/documents/upload-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ filename: file.name, content_type: contentType, file_size: file.size }),
  });
  if (!urlRes.ok) throw await readApiError(urlRes, "Could not start the upload");
  const grant = (await urlRes.json()) as {
    document_id: string;
    version_id: string;
    upload_url: string;
    method: string;
    required_headers: Record<string, string>;
  };
  const putRes = await fetch(grant.upload_url, {
    method: grant.method || "PUT",
    headers: grant.required_headers,
    body: file,
  });
  if (!putRes.ok) throw new Error(`Storage upload failed (${putRes.status})`);
  onProgress?.("Chunking");
  const completeRes = await fetch(`${API}/api/cases/${caseId}/documents/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      document_id: grant.document_id,
      version_id: grant.version_id,
      filename: file.name,
      content_type: contentType,
    }),
  });
  if (!completeRes.ok) throw await readApiError(completeRes, "Could not register the upload");
  const doc = (await completeRes.json()) as ApiDocument;
  return { id: doc.document_id, processingStatus: doc.processing_status, processingStage: doc.processing_stage };
}

/** GET /api/cases/{case_id}/documents -> registered documents with processing status. */
export async function fetchDocuments(caseId: string): Promise<ApiDocument[]> {
  if (USE_MOCK) return [];
  const res = await fetch(`${API}/api/cases/${caseId}/documents`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw await readApiError(res, "Could not load documents");
  return (await res.json()) as ApiDocument[];
}

/** DELETE /api/cases/{case_id}/documents/{document_id} -> soft-delete document. */
export async function deleteDocumentRemote(caseId: string, documentId: string): Promise<void> {
  if (USE_MOCK) return;
  const res = await fetch(`${API}/api/cases/${caseId}/documents/${documentId}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!res.ok && res.status !== 404) {
    throw await readApiError(res, "Could not delete document");
  }
}

/** POST /api/cases/{case_id}/analyze -> CaseIntel */
export async function analyzeCase(caseId: string): Promise<CaseIntel> {
  if (USE_MOCK) return mockAnalyze(caseId);
  const res = await fetch(`${API}/api/cases/${caseId}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) throw await readApiError(res, "Analysis failed");
  return res.json();
}

/** GET /api/cases/{case_id}/intel -> CaseIntel | null */
export async function getCaseIntel(caseId: string): Promise<CaseIntel | null> {
  if (USE_MOCK) return null;
  try {
    const res = await fetch(`${API}/api/cases/${caseId}/intel`, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data || null;
  } catch {
    return null;
  }
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
