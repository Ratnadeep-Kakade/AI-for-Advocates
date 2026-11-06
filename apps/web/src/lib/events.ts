import type { AgentId, Message, StreamEvent, TraceItem } from "../types";
import { uid } from "./util";

// Pure reducer: folds one backend event into the assistant message being streamed.
export function applyEvent(m: Message, e: StreamEvent): Message {
  const trace = (kind: TraceItem["kind"], agent: AgentId, text: string): TraceItem[] => [
    ...(m.trace ?? []),
    { id: uid(), agent, kind, text, at: Date.now() },
  ];
  switch (e.type) {
    case "execution":
      return { ...m, executionId: e.executionId };
    case "agent_start":
      return { ...m, trace: trace("start", e.agent, e.text) };
    case "step":
      return { ...m, trace: trace("step", e.agent, e.text) };
    case "tool":
      return { ...m, trace: trace("tool", e.agent, `${e.tool}: ${e.text}`) };
    case "evidence": {
      const list = m.evidence ?? [];
      const exists = list.some((x) => x.id === e.evidence.id);
      return { ...m, evidence: exists ? list.map((x) => (x.id === e.evidence.id ? e.evidence : x)) : [...list, e.evidence] };
    }
    case "token":
      return { ...m, content: m.content + e.text };
    case "arguments":
      return { ...m, proArgs: e.pro, conArgs: e.con };
    case "evaluation":
      return { ...m, evaluation: e.evaluation };
    case "done":
      return { ...m, status: "done" };
    case "error":
      return { ...m, status: "error", error: e.message };
  }
}
