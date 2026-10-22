import { ApiError } from "./screening";
import { apiFetch } from "./http";
import type { AgentPreparedFormulation, AgentRowUpdate, AgentSession } from "../types/agent";
import type { CaseView, CurrentUser, FormulationVersion, ScreeningRun } from "../types/cases";

async function parse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload as T;
  const detail = payload?.detail;
  throw new ApiError(typeof detail === "object" ? detail?.message : detail || "The request failed.", response.status, typeof detail === "object" ? detail?.code : undefined);
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  return parse<T>(await apiFetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  }));
}

export const getMe = () => json<CurrentUser>("/me");
export const listCases = () => json<CaseView[]>("/cases");
export const getCase = (id: string) => json<CaseView>(`/cases/${encodeURIComponent(id)}`);
export const createCase = (name: string, clientName: string | null) => json<CaseView>("/cases", { method: "POST", body: JSON.stringify({ name, client_name: clientName }) });
export const updateCase = (id: string, changes: Partial<Pick<CaseView, "name" | "client_name" | "product_type" | "status">>) => json<CaseView>(`/cases/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(changes) });
export async function deleteCase(id: string): Promise<void> { await parse<unknown>(await apiFetch(`/cases/${encodeURIComponent(id)}`, { method: "DELETE" })); }
export async function deleteAccount(): Promise<void> { await json<unknown>("/me", { method: "DELETE", body: JSON.stringify({ confirmation: "DELETE" }) }); }

export async function uploadCaseFormulation(caseId: string, file: File): Promise<FormulationVersion> {
  const body = new FormData(); body.append("file", file);
  return parse<FormulationVersion>(await apiFetch(`/cases/${encodeURIComponent(caseId)}/formulations`, { method: "POST", body }));
}
export const getFormulationVersion = (id: string) => json<FormulationVersion>(`/formulations/${encodeURIComponent(id)}`);
export async function deleteFormulationVersion(id: string): Promise<void> { await json<unknown>(`/formulations/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirmation: "DELETE" }) }); }
export const retryFormulationVersion = (id: string) => json<FormulationVersion>(`/formulations/${encodeURIComponent(id)}/interpret`, { method: "POST" });
export function answerFormulationVersion(session: AgentSession, answers: Array<{ question_id: string; option_id: string; value?: unknown }> = [], rowUpdates: AgentRowUpdate[] = []) {
  return json<FormulationVersion>(`/formulations/${encodeURIComponent(session.session_id)}/answers`, { method: "POST", body: JSON.stringify({ revision: session.revision, answers, row_updates: rowUpdates }) });
}
export function prepareFormulationVersion(session: AgentSession, metadata: { formulation_id: string | null; formulation_name: string | null; product_context: string | null; product_applicability?: import("../types/screening").ProductApplicabilityFacts }) {
  return json<AgentPreparedFormulation>(`/formulations/${encodeURIComponent(session.session_id)}/prepare`, { method: "POST", body: JSON.stringify({ revision: session.revision, ...metadata }) });
}
export const screenFormulationVersion = (id: string) => json<ScreeningRun>(`/formulations/${encodeURIComponent(id)}/screen`, { method: "POST" });
export const listFormulationScreenings = (id: string) => json<ScreeningRun[]>(`/formulations/${encodeURIComponent(id)}/screenings`);

