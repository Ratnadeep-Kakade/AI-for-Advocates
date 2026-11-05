// Shared types. The StreamEvent union is the contract between the Modal backend and this UI.

export type AgentId =
  | "orchestrator"
  | "analyzer"
  | "researcher"
  | "argument"
  | "counterargument"
  | "evaluator";

export const AGENTS: Record<AgentId, { name: string; role: string }> = {
  orchestrator: { name: "Orchestrator", role: "Plans the work, delegates and writes the final answer" },
  analyzer: { name: "Document analyzer", role: "Extracts parties, dates, obligations and facts from case documents" },
  researcher: { name: "Legal researcher", role: "Runs iterative research across legal sources and case documents" },
  argument: { name: "Argument builder", role: "Builds the strongest arguments for your position" },
  counterargument: { name: "Counter-argument", role: "Attacks those arguments and finds weaknesses" },
  evaluator: { name: "Evaluator", role: "Checks evidence and reasoning quality; can reject either side" },
};
export const AGENT_IDS = Object.keys(AGENTS) as AgentId[];

export type TaskMode = "auto" | "research" | "analyze" | "arguments" | "full";
export const MODES: { id: TaskMode; label: string; hint: string }[] = [
  { id: "auto", label: "Auto", hint: "Let the orchestrator decide which agents to run" },
  { id: "research", label: "Research", hint: "Find and verify authorities" },
  { id: "analyze", label: "Analyze documents", hint: "Extract case intelligence from uploaded documents" },
  { id: "arguments", label: "Build arguments", hint: "Arguments and counter-arguments" },
  { id: "full", label: "Full analysis", hint: "Research, arguments, counter-arguments and evaluation" },
];

export interface ModelOption { id: string; name: string; note?: string }
export const DEFAULT_MODELS: ModelOption[] = [
  { id: "auto", name: "Auto routing", note: "Each agent uses the model set in Settings" },
  { id: "muse-spark-1.3", name: "Muse Spark 1.3", note: "Meta model API" },
];

export type Authority = "binding" | "persuasive" | "non-authoritative" | "case-document";
export type Verification = "verified" | "unverified" | "failed";

export interface Evidence {
  id: string; // e.g. "E1": referenced in answers as [E1]
  kind: "document" | "judgment" | "statute" | "web";
  title: string;
  cite?: string;
  authority: Authority;
  verification: Verification;
  passage: string;
  source?: string; // file name + page, or URL
}

export interface Argument {
  id: string;
  claim: string;
  basis: string;
  evidenceIds: string[];
  vulnerabilities?: string[];
}

export interface Evaluation {
  legalBasis: "supported" | "unsupported" | "uncertain";
  evidenceSufficiency: "sufficient" | "inadequate";
  conflictingAuthorities: string[];
  missingInformation: string[];
  unresolvedQuestions: string[];
}

export interface TraceItem { id: string; agent: AgentId; kind: "start" | "step" | "tool"; text: string; at: number }

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  status?: "streaming" | "done" | "error";
  executionId?: string;
  model?: string;
  mode?: TaskMode;
  trace?: TraceItem[];
  evidence?: Evidence[];
  proArgs?: Argument[];
  conArgs?: Argument[];
  evaluation?: Evaluation;
  error?: string;
}

export interface Chat { id: string; title: string; caseId?: string; createdAt: number; updatedAt: number; messages: Message[] }

// Mirrors the CaseIntelligence JSON produced by the Document Intelligence agent.
export interface CaseIntel {
  case_id?: string;
  parties: { name: string; role?: string }[];
  contractual_obligations: string[];
  material_facts: string[];
  important_dates: { label: string; date: string }[];
  legal_issues: string[];
  contradictions: string[];
  missing_information: string[];
  evidence_references?: string[];
}

export interface Case {
  id: string;
  title: string;
  client: string;
  opposingParty: string;
  court: string;
  caseNumber: string;
  jurisdiction: string;
  practiceArea: string;
  status: "active" | "on-hold" | "closed";
  createdAt: number;
  intel?: CaseIntel;
}

export interface CaseDoc {
  id: string;
  caseId: string;
  name: string;
  size: number;
  status: "processing" | "analyzed" | "failed";
  addedAt: number;
}

export interface Deadline {
  id: string;
  caseId?: string;
  title: string;
  date: string; // YYYY-MM-DD
  kind: "hearing" | "filing" | "limitation" | "other";
  done: boolean;
}

export type StreamEvent =
  | { type: "execution"; executionId: string }
  | { type: "agent_start"; agent: AgentId; text: string }
  | { type: "step"; agent: AgentId; text: string }
  | { type: "tool"; agent: AgentId; tool: string; text: string }
  | { type: "evidence"; evidence: Evidence }
  | { type: "token"; text: string }
  | { type: "arguments"; pro: Argument[]; con: Argument[] }
  | { type: "evaluation"; evaluation: Evaluation }
  | { type: "done" }
  | { type: "error"; message: string };

export interface ChatRequest {
  chat_id: string;
  case_id?: string;
  prompt: string;
  model: string;
  mode: TaskMode;
  jurisdiction: string;
  agent_models: Record<AgentId, string>;
  document_ids: string[];
  history: { role: "user" | "assistant"; content: string }[];
}
