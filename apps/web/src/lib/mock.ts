import type { CaseIntel, ChatRequest, Evidence, StreamEvent } from "../types";

// SAMPLE DATA ONLY. Nothing here is real legal authority.
const sleep = (ms: number, sig: AbortSignal) =>
  new Promise<void>((res, rej) => {
    const t = setTimeout(res, ms);
    sig.addEventListener("abort", () => { clearTimeout(t); rej(new DOMException("Aborted", "AbortError")); }, { once: true });
  });

const E1: Evidence = {
  id: "E1", kind: "document", title: "Master Services Agreement, clause 14.2", authority: "case-document", verification: "verified",
  source: "MSA_signed.pdf, p. 9",
  passage: "Either party may terminate this Agreement with immediate effect by written notice if the other party commits a material breach and fails to remedy it within thirty (30) days of receiving notice of that breach.",
};
const E2: Evidence = {
  id: "E2", kind: "document", title: "Termination notice (sample)", authority: "case-document", verification: "verified",
  source: "Notice_12_March.pdf, p. 1",
  passage: "We hereby terminate the Agreement with immediate effect on account of your failure to meet the delivery milestones.",
};
const E3: Evidence = {
  id: "E3", kind: "judgment", title: "Illustrative Co. v. Placeholder Ltd. (sample, not a real case)", authority: "persuasive", verification: "unverified",
  cite: "Sample citation",
  passage: "Sample passage: where a contract prescribes a cure period before termination, a notice that skips the cure period does not terminate the contract.",
};

const ANSWER = `**Short answer (sample data):** On the documents provided, immediate termination looks **premature**. Clause 14.2 allows immediate termination only after written notice of breach and a 30-day cure period [E1], and the notice relied on states immediate termination without offering one [E2].

### Key points
1. **What the clause requires.** Written notice of the breach, then thirty days to remedy it, before termination takes effect [E1].
2. **What the notice did.** It terminated "with immediate effect" and does not refer to any earlier notice of breach [E2].
3. **Authority.** A persuasive sample authority treats a skipped cure period as fatal to the termination [E3]. This source is **unverified**, so confirm it before citing.

### Open items
- Check whether an earlier notice of breach was served.
- Check for statutory restrictions on termination in this jurisdiction.
- Look for binding judgments that interpret similar cure-period clauses.`;

export async function mockStream(req: ChatRequest, on: (e: StreamEvent) => void, sig: AbortSignal) {
  const full = req.mode === "full" || req.mode === "arguments" || req.mode === "auto";
  await sleep(300, sig);
  on({ type: "execution", executionId: "exec_" + Math.random().toString(36).slice(2, 8) });
  on({ type: "agent_start", agent: "orchestrator", text: "Reading the request and planning the work" });
  await sleep(500, sig);
  on({ type: "step", agent: "orchestrator", text: `Task type: ${req.mode === "auto" ? "contract termination analysis" : req.mode}. Agents needed: analyzer, researcher${full ? ", argument, counter-argument, evaluator" : ""}` });
  on({ type: "agent_start", agent: "analyzer", text: "Reading case documents" });
  on({ type: "tool", agent: "analyzer", tool: "case_document_search", text: "termination, notice, cure period" });
  await sleep(700, sig);
  on({ type: "evidence", evidence: E1 });
  on({ type: "evidence", evidence: E2 });
  on({ type: "step", agent: "analyzer", text: "Extracted clause 14.2 and the notice; both quotes matched to their source pages" });
  on({ type: "agent_start", agent: "researcher", text: "Researching authorities on cure periods" });
  on({ type: "tool", agent: "researcher", tool: "legal_database_search", text: "termination cure period notice judgment" });
  await sleep(800, sig);
  on({ type: "step", agent: "researcher", text: "Found 1 relevant judgment. Not yet verified against the source; marked unverified" });
  on({ type: "evidence", evidence: E3 });
  on({ type: "step", agent: "researcher", text: "Gap check: no binding authority found yet. Further research recommended" });
  if (full) {
    on({ type: "agent_start", agent: "argument", text: "Building supporting arguments" });
    await sleep(700, sig);
    on({
      type: "arguments",
      pro: [{ id: "A1", claim: "The termination was invalid because the cure period was skipped.", basis: "Clause 14.2 makes a 30-day cure period a condition of immediate termination.", evidenceIds: ["E1", "E2", "E3"], vulnerabilities: ["Depends on E3, which is unverified"] }],
      con: [{ id: "C1", claim: "The breach was incurable, so a cure period would have been futile.", basis: "Missed delivery milestones may be argued to go to the root of the contract.", evidenceIds: ["E2"], vulnerabilities: ["Clause 14.2 has no incurable-breach exception"] }],
    });
    on({ type: "agent_start", agent: "counterargument", text: "Challenging the arguments with a different model family" });
    await sleep(600, sig);
    on({ type: "agent_start", agent: "evaluator", text: "Checking clause text, evidence and authorities" });
    await sleep(600, sig);
    on({ type: "evaluation", evaluation: { legalBasis: "uncertain", evidenceSufficiency: "inadequate", conflictingAuthorities: [], missingInformation: ["Whether an earlier notice of breach was served"], unresolvedQuestions: ["Is there a binding authority on incurable breach?"] } });
  }
  on({ type: "agent_start", agent: "orchestrator", text: "Writing the final answer" });
  for (const w of ANSWER.split(/(\s+)/)) {
    on({ type: "token", text: w });
    await sleep(12, sig);
  }
  on({ type: "done" });
}

export async function mockAnalyze(caseId: string): Promise<CaseIntel> {
  await new Promise((r) => setTimeout(r, 1200));
  return {
    case_id: caseId,
    parties: [{ name: "Client (sample)", role: "Service provider" }, { name: "Counterparty (sample)", role: "Customer" }],
    contractual_obligations: ["Deliver milestones 1 to 3 by the agreed dates (cl. 5)", "Pay invoices within 30 days (cl. 8)", "30-day cure period before termination (cl. 14.2)"],
    material_facts: ["Notice of termination issued on 12 March without a prior breach notice", "Milestone 2 delivered 9 days late"],
    important_dates: [{ label: "Agreement signed", date: "2025-01-15" }, { label: "Termination notice", date: "2026-03-12" }],
    legal_issues: ["Validity of immediate termination", "Whether late delivery is a material breach"],
    contradictions: ["Notice cites missed milestones; delivery log shows milestone 2 accepted"],
    missing_information: ["Any correspondence before 12 March", "Acceptance certificate for milestone 2"],
  };
}
