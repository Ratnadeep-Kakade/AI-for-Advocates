import type { Message } from "../types";
import { download, fmtDate } from "./util";

export function exportMemo(chatTitle: string, caseTitle: string | undefined, m: Message) {
  const ev = m.evidence ?? [];
  const lines: string[] = [
    `# ${chatTitle}`,
    caseTitle ? `Matter: ${caseTitle}` : "",
    `Generated: ${fmtDate(m.createdAt)}${m.executionId ? ` (execution ${m.executionId})` : ""}`,
    "",
    "> Privileged and confidential. AI-assisted research: verify every authority before relying on it.",
    "",
    m.content,
  ];
  if (m.evaluation) {
    const e = m.evaluation;
    lines.push("", "## Evaluation", `- Legal basis: ${e.legalBasis}`, `- Evidence sufficiency: ${e.evidenceSufficiency}`);
    if (e.conflictingAuthorities.length) lines.push(`- Conflicting authorities: ${e.conflictingAuthorities.join("; ")}`);
    if (e.missingInformation.length) lines.push(`- Missing information: ${e.missingInformation.join("; ")}`);
    if (e.unresolvedQuestions.length) lines.push(`- Unresolved questions: ${e.unresolvedQuestions.join("; ")}`);
  }
  if (ev.length) {
    lines.push("", "## Sources");
    ev.forEach((x, i) =>
      lines.push(`${i + 1}. ${x.title}${x.cite ? `, ${x.cite}` : ""} [${x.authority}, ${x.verification}]${x.source ? ` (${x.source})` : ""}`)
    );
  }
  download(`${chatTitle.replace(/[^\w]+/g, "-").slice(0, 40) || "memo"}.md`, lines.filter((l, i) => l !== "" || i > 0).join("\n"));
}
