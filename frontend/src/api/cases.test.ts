import { beforeEach, describe, expect, it, vi } from "vitest";
import { uploadCaseDocumentSelection } from "./cases";

const apiFetch = vi.fn();
vi.mock("./http", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));

describe("case document uploads", () => {
  beforeEach(() => {
    apiFetch.mockReset().mockResolvedValue(new Response(JSON.stringify({ id: "version-1" }), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }));
  });

  it("sends the selected formulation separately from every supplier document", async () => {
    const formulation = new File(["formula"], "finished.xlsx");
    const suppliers = [new File(["a"], "a.pdf"), new File(["b"], "b.pdf")];

    await uploadCaseDocumentSelection("case/1", formulation, suppliers);

    expect(apiFetch).toHaveBeenCalledTimes(1);
    const [path, init] = apiFetch.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/cases/case%2F1/formulations");
    expect(init.method).toBe("POST");
    const body = init.body as FormData;
    expect(body.get("file")).toBe(formulation);
    expect(body.getAll("files")).toEqual(suppliers);
  });
});
