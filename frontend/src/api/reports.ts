import type { FormulationRequest } from "../types/screening";
import { apiFetch } from "./http";
import { ApiError } from "./screening";

function filenameFrom(response: Response): string {
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? "regulens-screening-report.pdf";
}

async function download(response: Response): Promise<void> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload?.detail;
    throw new ApiError(
      typeof detail === "object" ? detail?.message : detail || "The PDF report could not be generated.",
      response.status,
      typeof detail === "object" ? detail?.code : undefined,
    );
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filenameFrom(response);
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function downloadAdHocScreeningReport(request: FormulationRequest): Promise<void> {
  await download(await apiFetch("/screen-formulation/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }));
}

export async function downloadSavedScreeningReport(screeningRunId: string): Promise<void> {
  await download(await apiFetch(`/screenings/${encodeURIComponent(screeningRunId)}/report.pdf`));
}
