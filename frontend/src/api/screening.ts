import type { ACDIngredientSearchResponse, FieldIssue, FormulationRequest, IngredientSearchResponse, ScreeningOptions, ScreeningResponse } from "../types/screening";
import { apiBase, apiFetch } from "./http";

export function sourceEvidenceUrl(rawRecordId: string, mode: "crop" | "page" = "crop"): string {
  const suffix = mode === "page" ? "/page" : "";
  return `${apiBase}/source-evidence/${encodeURIComponent(rawRecordId)}${suffix}`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
    public readonly issues: FieldIssue[] = [],
  ) {
    super(message);
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await apiFetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Unable to reach the screening service.", 0);
  }

  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload as T;

  const detail = payload?.detail;
  if (response.status === 422 && Array.isArray(detail)) {
    const issues = detail.map((item: { loc?: Array<string | number>; msg?: string }) => ({
      path: (item.loc ?? []).filter((part) => part !== "body").join("."),
      message: item.msg ?? "Invalid value",
    }));
    throw new ApiError("Please correct the highlighted fields.", 422, undefined, issues);
  }
  const code = typeof detail === "object" ? detail?.code : undefined;
  const message = typeof detail === "object" ? detail?.message : detail;
  throw new ApiError(message || "The screening request failed.", response.status, code);
}

export function getScreeningOptions(): Promise<ScreeningOptions> {
  return requestJson<ScreeningOptions>("/screening-options");
}

export function screenFormulation(request: FormulationRequest): Promise<ScreeningResponse> {
  return requestJson<ScreeningResponse>("/screen-formulation", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function searchIngredients(query: string, signal?: AbortSignal, limit = 20): Promise<IngredientSearchResponse> {
  return requestJson<IngredientSearchResponse>(`/ingredients?query=${encodeURIComponent(query)}&limit=${limit}`, { signal });
}

export function identitySourceEvidenceUrl(rawRecordId: string, mode: "crop" | "page" = "crop"): string {
  const suffix = mode === "page" ? "/page" : "";
  return `${apiBase}/identity-source-evidence/${encodeURIComponent(rawRecordId)}${suffix}`;
}

export function searchACDIngredients(query: string, signal?: AbortSignal, limit = 20): Promise<ACDIngredientSearchResponse> {
  return requestJson<ACDIngredientSearchResponse>(`/acd-ingredients?query=${encodeURIComponent(query)}&limit=${limit}`, { signal });
}
