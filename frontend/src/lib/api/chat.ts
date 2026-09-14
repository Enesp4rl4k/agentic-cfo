/**
 * Grounded agent chat API (/chat/agent).
 */
import { apiClient } from "./client";
import type { ChatMessage } from "./cfo";

export type AgentFilter =
  | "all" | "cfo" | "cto" | "cmo" | "coo" | "chro" | "risk" | "audit";

export interface ChatEvidenceMeta {
  evidence_found?: boolean;
  evidence_tx_count?: number;
  evidence_semantic_count?: number;
  evidence_retriever_version?: string;
  grounding_validated?: boolean;
}

export interface AgentChatResponse {
  answer: string;
  session_id?: string;
  context_agents?: string[];
  evidence: ChatEvidenceMeta;
}

export async function sendAgentChatMessage(
  question: string,
  options: {
    agentFilter?: AgentFilter;
    history?: ChatMessage[];
    sessionId?: string;
    useReasoning?: boolean;
  } = {}
): Promise<AgentChatResponse> {
  const res = await apiClient.post<{
    data: {
      answer: string;
      session_id?: string;
      context_agents?: string[];
      evidence_found?: boolean;
      evidence_tx_count?: number;
      evidence_semantic_count?: number;
      evidence_retriever_version?: string;
      grounding_validated?: boolean;
    };
    error: string | null;
  }>("/chat/agent", {
    question,
    agent_filter: options.agentFilter ?? "cfo",
    conversation_history: (options.history ?? []).map((m) => ({
      role: m.role,
      content: m.content,
    })),
    session_id: options.sessionId,
    stream: false,
    use_reasoning: options.useReasoning ?? false,
  });

  if (res.data.error) throw new Error(res.data.error);

  const data = res.data.data;
  return {
    answer: data.answer,
    session_id: data.session_id,
    context_agents: data.context_agents,
    evidence: {
      evidence_found: data.evidence_found,
      evidence_tx_count: data.evidence_tx_count,
      evidence_semantic_count: data.evidence_semantic_count,
      evidence_retriever_version: data.evidence_retriever_version,
      grounding_validated: data.grounding_validated,
    },
  };
}
