import { ApiError } from "./screening";
import type { AgentPreparedFormulation, AgentRowUpdate, AgentSession } from "../types/agent";
import type { ProductApplicabilityFacts } from "../types/screening";
import { apiFetch } from "./http";

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload as T;
  const detail = payload?.detail;
  const code = typeof detail === "object" ? detail?.code : undefined;
  const message = typeof detail === "object" ? detail?.message : detail;
  throw new ApiError(message || "The formulation agent request failed.", response.status, code);
}

async function agentJson<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await apiFetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    return parseResponse<T>(response);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("Unable to reach the formulation agent.", 0);
  }
}

export async function uploadAgentCSV(file: File): Promise<AgentSession> {
  const body = new FormData();
  body.append("file", file);
  try {
    return parseResponse<AgentSession>(await apiFetch("/agent/formulations", { method: "POST", body }));
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("Unable to reach the formulation agent.", 0);
  }
}

export function retryAgentSession(sessionId: string): Promise<AgentSession> {
  return agentJson(`/agent/formulations/${encodeURIComponent(sessionId)}/retry`, { method: "POST" });
}

export function answerAgentQuestions(
  session: AgentSession,
  answers: Array<{ question_id: string; option_id: string; value?: unknown }> = [],
  rowUpdates: AgentRowUpdate[] = [],
): Promise<AgentSession> {
  return agentJson(`/agent/formulations/${encodeURIComponent(session.session_id)}/answers`, {
    method: "POST",
    body: JSON.stringify({ revision: session.revision, answers, row_updates: rowUpdates }),
  });
}

export function prepareAgentFormulation(
  session: AgentSession,
  metadata: { formulation_id: string | null; formulation_name: string | null; product_context: string | null; product_applicability?: ProductApplicabilityFacts },
): Promise<AgentPreparedFormulation> {
  return agentJson(`/agent/formulations/${encodeURIComponent(session.session_id)}/prepare`, {
    method: "POST",
    body: JSON.stringify({ revision: session.revision, ...metadata }),
  });
}
