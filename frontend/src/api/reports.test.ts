import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { downloadAdHocScreeningReport, downloadSavedScreeningReport } from "./reports";

const apiFetch = vi.fn();
vi.mock("./http", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));

describe("screening report downloads", () => {
  beforeEach(() => {
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:report") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("downloads an ad-hoc report with the server filename", async () => {
    apiFetch.mockResolvedValue(new Response(new Blob(["pdf"]), {
      status: 200,
      headers: { "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="FORM-1-screening-report.pdf"' },
    }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    await downloadAdHocScreeningReport({
      formulation_id: "FORM-1",
      formulation_name: "Test",
      product_context: null,
      product_applicability: {},
      ingredients: [{ name: "Aqua", cas_number: null, concentration: null, regulated_functions: [] }],
    });

    expect(apiFetch).toHaveBeenCalledWith("/screen-formulation/report", expect.objectContaining({ method: "POST" }));
    expect(click).toHaveBeenCalledOnce();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:report");
  });

  it("requests the immutable saved screening report", async () => {
    apiFetch.mockResolvedValue(new Response(new Blob(["pdf"]), { status: 200 }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    await downloadSavedScreeningReport("run/1");

    expect(apiFetch).toHaveBeenCalledWith("/screenings/run%2F1/report.pdf");
  });
});
