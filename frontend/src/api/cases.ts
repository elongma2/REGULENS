import { ApiError } from "./screening";
import { apiFetch } from "./http";
import type { AgentPreparedFormulation, AgentRowAddition, AgentRowUpdate, AgentSession } from "../types/agent";
import type { AssemblyPreparation, CaseView, CurrentUser, DocumentRole, FormulationAssemblyState, FormulationDocument, FormulationDocumentBatch, FormulationVersion, ScreeningRun, SupplierDocument, SupplierDocumentBatch, SupplierDocumentDetail } from "../types/cases";

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
export async function uploadCaseFormulationDocuments(caseId: string, files: File[]): Promise<FormulationVersion> {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  return parse<FormulationVersion>(await apiFetch(`/cases/${encodeURIComponent(caseId)}/formulations`, { method: "POST", body }));
}
export async function uploadCaseSupplierDocuments(caseId: string, files: File[]): Promise<SupplierDocumentBatch> {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  return parse<SupplierDocumentBatch>(await apiFetch(`/cases/${encodeURIComponent(caseId)}/supplier-documents`, { method: "POST", body }));
}
export const getFormulationVersion = (id: string) => json<FormulationVersion>(`/formulations/${encodeURIComponent(id)}`);
export async function deleteFormulationVersion(id: string): Promise<void> { await json<unknown>(`/formulations/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirmation: "DELETE" }) }); }
export const retryFormulationVersion = (id: string) => json<FormulationVersion>(`/formulations/${encodeURIComponent(id)}/interpret`, { method: "POST" });
export function answerFormulationVersion(session: AgentSession, answers: Array<{ question_id: string; option_id: string; value?: unknown }> = [], rowUpdates: AgentRowUpdate[] = [], addRows: AgentRowAddition[] = [], removeRowIds: string[] = []) {
  return json<FormulationVersion>(`/formulations/${encodeURIComponent(session.session_id)}/answers`, { method: "POST", body: JSON.stringify({ revision: session.revision, answers, row_updates: rowUpdates, add_rows: addRows, remove_row_ids: removeRowIds }) });
}
export function prepareFormulationVersion(session: AgentSession, metadata: { formulation_id: string | null; formulation_name: string | null; product_context: string | null; product_applicability?: import("../types/screening").ProductApplicabilityFacts }) {
  return json<AgentPreparedFormulation>(`/formulations/${encodeURIComponent(session.session_id)}/prepare`, { method: "POST", body: JSON.stringify({ revision: session.revision, ...metadata }) });
}
export const screenFormulationVersion = (id: string) => json<ScreeningRun>(`/formulations/${encodeURIComponent(id)}/screen`, { method: "POST" });
export const listFormulationScreenings = (id: string) => json<ScreeningRun[]>(`/formulations/${encodeURIComponent(id)}/screenings`);

export function listSupplierDocuments(options: { search?: string; availableOnly?: boolean; includeArchived?: boolean } = {}) {
  const query = new URLSearchParams();
  if (options.search) query.set("search", options.search);
  if (options.availableOnly) query.set("available_only", "true");
  if (options.includeArchived) query.set("include_archived", "true");
  const suffix = query.size ? `?${query.toString()}` : "";
  return json<SupplierDocument[]>(`/supplier-documents${suffix}`);
}

export const getSupplierDocument = (id: string) => json<SupplierDocumentDetail>(`/supplier-documents/${encodeURIComponent(id)}`);
export const getSupplierDocumentFile = (id: string) => json<{ url: string; expires_in: number }>(`/supplier-documents/${encodeURIComponent(id)}/file`);
export const retrySupplierDocument = (id: string) => json<SupplierDocument>(`/supplier-documents/${encodeURIComponent(id)}/retry`, { method: "POST" });

export function updateSupplierDocument(id: string, revision: number, changes: { supplier_name?: string | null; trade_name?: string | null; product_code?: string | null; document_revision_label?: string | null; supersedes_supplier_document_id?: string | null; confirmed_roles?: DocumentRole[]; library_status?: "available" | "needs_confirmation" | "archived" }) {
  return json<SupplierDocument>(`/supplier-documents/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ revision, ...changes }),
  });
}

export async function deleteSupplierDocument(id: string): Promise<void> {
  await parse<unknown>(await apiFetch(`/supplier-documents/${encodeURIComponent(id)}`, { method: "DELETE" }));
}

export const listFormulationDocuments = (versionId: string) => json<FormulationDocument[]>(`/formulations/${encodeURIComponent(versionId)}/documents`);

export async function uploadFormulationDocuments(versionId: string, files: File[]): Promise<FormulationDocumentBatch> {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  return parse<FormulationDocumentBatch>(await apiFetch(`/formulations/${encodeURIComponent(versionId)}/documents`, { method: "POST", body }));
}

export function attachSupplierDocument(versionId: string, supplierDocumentId: string) {
  return json<FormulationDocument>(`/formulations/${encodeURIComponent(versionId)}/documents/attach`, {
    method: "POST",
    body: JSON.stringify({ supplier_document_id: supplierDocumentId }),
  });
}

export function updateFormulationDocument(id: string, revision: number, changes: { confirmed_roles?: DocumentRole[]; governing_for_material?: boolean; document_revision_label?: string | null }) {
  return json<FormulationDocument>(`/formulation-documents/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ revision, ...changes }),
  });
}

export function retryFormulationDocument(id: string) {
  return json<FormulationDocument>(`/formulation-documents/${encodeURIComponent(id)}/retry`, {
    method: "POST",
  });
}

export function interpretFormulationDocument(id: string) {
  return json<FormulationDocument>(`/formulation-documents/${encodeURIComponent(id)}/interpret`, {
    method: "POST",
  });
}

export async function detachFormulationDocument(versionId: string, documentId: string): Promise<void> {
  await parse<unknown>(await apiFetch(`/formulations/${encodeURIComponent(versionId)}/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" }));
}

export const refreshFormulationAssembly = (versionId: string) => json<AssemblyPreparation>(
  `/formulations/${encodeURIComponent(versionId)}/assembly/refresh`,
  { method: "POST" },
);

export async function getOrInitializeFormulationAssembly(versionId: string): Promise<AssemblyPreparation> {
  try {
    return await json<AssemblyPreparation>(`/formulations/${encodeURIComponent(versionId)}/assembly`);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404 || error.code !== "assembly_not_initialized") {
      throw error;
    }
    return refreshFormulationAssembly(versionId);
  }
}

export const updateFormulationAssembly = (
  versionId: string,
  assemblyRevision: number,
  assemblyState: FormulationAssemblyState,
) => json<AssemblyPreparation>(`/formulations/${encodeURIComponent(versionId)}/assembly`, {
  method: "PATCH",
  body: JSON.stringify({ assembly_revision: assemblyRevision, assembly_state: assemblyState }),
});

