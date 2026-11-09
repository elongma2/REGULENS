import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SupplierDocumentsPanel, type SupplierDocumentsPanelHandle } from "./SupplierDocumentsPanel";

const api = vi.hoisted(() => ({
  listFormulationDocuments: vi.fn(),
  listSupplierDocuments: vi.fn(),
  uploadFormulationDocuments: vi.fn(),
  attachSupplierDocument: vi.fn(),
  detachFormulationDocument: vi.fn(),
  getSupplierDocument: vi.fn(),
  getSupplierDocumentFile: vi.fn(),
  deleteSupplierDocument: vi.fn(),
  updateSupplierDocument: vi.fn(),
  updateFormulationDocument: vi.fn(),
  retryFormulationDocument: vi.fn(),
  interpretFormulationDocument: vi.fn(),
}));

vi.mock("../api/cases", () => api);

const attachment = {
  id: "attachment-1",
  formulation_version_id: "version-1",
  supplier_document_id: "supplier-1",
  original_filename: "OPTASENSE Composition.pdf",
  mime_type: "application/pdf",
  sha256: "a".repeat(64),
  page_count: 1,
  processing_status: "ready",
  detected_roles: [{ role: "supplier_composition", confidence: "high", page: 1, source_snippet: "INCI", reasons: [] }],
  confirmed_roles: [],
  parsed_content: {}, extraction_result: {}, processing_diagnostics: {}, error: null,
  document_revision_label: null, governing_for_material: false,
  attached_extraction_key: "key", revision: 0,
  created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:00Z",
};

const savedDocument = {
  id: "saved-1", organisation_id: "organisation-1", original_filename: "matrixyl.pdf",
  mime_type: "application/pdf", sha256: "b".repeat(64), page_count: 2,
  supplier_name: "Sederma", trade_name: "MATRIXYL 3000", product_code: "SE28264",
  document_revision_label: "Rev 4", document_date: null, supersedes_supplier_document_id: null,
  detected_roles: [], confirmed_roles: ["supplier_composition"], extraction_schema_version: "1",
  processing_status: "ready", library_status: "available", processing_diagnostics: null, error: null,
  processing_key: "key", processing_attempt: 1, revision: 0, last_used_at: null,
  created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:00Z",
};

describe("SupplierDocumentsPanel", () => {
  beforeEach(() => {
    Object.values(api).forEach((mock) => mock.mockReset());
    api.listFormulationDocuments.mockResolvedValue([]);
    api.listSupplierDocuments.mockResolvedValue([]);
    api.detachFormulationDocument.mockResolvedValue(undefined);
    api.deleteSupplierDocument.mockResolvedValue(undefined);
  });

  it("keeps the ordinary formulation path clear when no documents are attached", async () => {
    render(<SupplierDocumentsPanel versionId="version-1" />);

    expect(await screen.findByText("No supporting documents attached")).toBeInTheDocument();
    expect(screen.getByText(/Ordinary INCI formulations still work normally/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Attach" })).toBeDisabled();
  });

  it("keeps source management compact until the reviewer opens it", async () => {
    const user = userEvent.setup();
    api.listFormulationDocuments.mockResolvedValue([{ ...attachment, confirmed_roles: ["supplier_composition"], governing_for_material: true }]);
    render(<SupplierDocumentsPanel compact versionId="version-1" />);

    expect(await screen.findByText("1 ready")).toBeInTheDocument();
    expect(screen.queryByText("Reuse a saved supplier file")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manage files" }));
    expect(screen.getByRole("dialog", { name: "Manage supplier files" })).toBeInTheDocument();
    expect(screen.getByText("Reuse a saved supplier file")).toBeInTheDocument();
    expect(screen.getByText(/keeps the private original file and the ingredients extracted from it/i)).toBeInTheDocument();
  });

  it("opens the exact source file requested by an assembly issue", async () => {
    const ref = createRef<SupplierDocumentsPanelHandle>();
    api.listFormulationDocuments.mockResolvedValue([{ ...attachment, confirmed_roles: ["supplier_composition"] }]);
    render(<SupplierDocumentsPanel ref={ref} compact versionId="version-1" />);

    await screen.findByText("1 ready");
    ref.current?.openManager("attachment-1");

    expect(await screen.findByRole("dialog", { name: "Manage supplier files" })).toBeInTheDocument();
    await waitFor(() => expect(document.getElementById("supplier-document-attachment-1")).toBeInTheDocument());
  });

  it("uploads multiple documents through one supporting-document control", async () => {
    const user = userEvent.setup();
    api.uploadFormulationDocuments.mockResolvedValue({ documents: [{ ...attachment }], failures: [] });
    api.listFormulationDocuments
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ ...attachment }]);
    render(<SupplierDocumentsPanel versionId="version-1" />);
    await screen.findByText("No supporting documents attached");

    const files = [
      new File(["composition"], "composition.pdf", { type: "application/pdf" }),
      new File(["sds"], "sds.pdf", { type: "application/pdf" }),
    ];
    await user.upload(screen.getByLabelText("Add documents"), files);

    await waitFor(() => expect(api.uploadFormulationDocuments).toHaveBeenCalledWith("version-1", files));
    expect(await screen.findByText("OPTASENSE Composition.pdf")).toBeInTheDocument();
  });

  it("adds documents through Manage files after initial processing", async () => {
    const user = userEvent.setup();
    const existing = { ...attachment, confirmed_roles: ["supplier_composition"], governing_for_material: true };
    const added = { ...attachment, id: "attachment-2", original_filename: "later-supplier.pdf" };
    api.listFormulationDocuments.mockResolvedValueOnce([existing]).mockResolvedValueOnce([existing, added]);
    api.uploadFormulationDocuments.mockResolvedValue({ documents: [added], failures: [] });
    render(<SupplierDocumentsPanel compact versionId="version-1" />);

    await user.click(await screen.findByRole("button", { name: "Manage files" }));
    const file = new File(["later"], "later-supplier.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Add documents"), file);

    await waitFor(() => expect(api.uploadFormulationDocuments).toHaveBeenCalledWith("version-1", [file]));
    expect(await screen.findByText("later-supplier.pdf")).toBeInTheDocument();
  });

  it("keeps the file picker available while an unrelated saved-document action is busy", async () => {
    const user = userEvent.setup();
    let finishMetadata!: (value: typeof savedDocument) => void;
    api.listSupplierDocuments.mockImplementation((options: { includeArchived?: boolean }) => (
      Promise.resolve(options?.includeArchived ? [savedDocument] : [])
    ));
    api.updateSupplierDocument.mockImplementation(() => new Promise((resolve) => { finishMetadata = resolve; }));
    render(<SupplierDocumentsPanel versionId="version-1" />);
    await screen.findByText("No supporting documents attached");

    await user.click(screen.getByRole("button", { name: "View saved documents" }));
    await user.click(await screen.findByText("Edit saved details"));
    await user.click(screen.getByRole("button", { name: "Save details" }));

    expect(screen.getByLabelText("Add documents")).toBeEnabled();
    finishMetadata({ ...savedDocument, revision: 1 });
  });

  it("keeps successful uploads visible when another document in the batch fails", async () => {
    const user = userEvent.setup();
    api.uploadFormulationDocuments.mockResolvedValue({
      documents: [{ ...attachment }],
      failures: [{
        filename: "empty.pdf", code: "agent_csv_empty",
        message: "The uploaded file is empty", recoverable: false,
      }],
    });
    api.listFormulationDocuments
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ ...attachment }]);
    render(<SupplierDocumentsPanel versionId="version-1" />);
    await screen.findByText("No supporting documents attached");

    await user.upload(screen.getByLabelText("Add documents"), [
      new File(["composition"], "composition.pdf", { type: "application/pdf" }),
      new File([], "empty.pdf", { type: "application/pdf" }),
    ]);

    expect(await screen.findByText("OPTASENSE Composition.pdf")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("empty.pdf: The uploaded file is empty");
  });

  it("interprets newly uploaded retained documents with at most two concurrent workers", async () => {
    const uploaded = [0, 1, 2].map((index) => ({
      ...attachment,
      id: `attachment-${index}`,
      supplier_document_id: `supplier-${index}`,
      original_filename: `source-${index}.pdf`,
      processing_status: "uploaded",
    }));
    let active = 0;
    let maximumActive = 0;
    const releases: Array<() => void> = [];
    api.listFormulationDocuments.mockResolvedValueOnce(uploaded).mockResolvedValue(uploaded);
    api.interpretFormulationDocument.mockImplementation((id: string) => new Promise((resolve) => {
      active += 1;
      maximumActive = Math.max(maximumActive, active);
      releases.push(() => {
        active -= 1;
        resolve({ ...uploaded.find((item) => item.id === id), processing_status: "ready" });
      });
    }));

    render(<SupplierDocumentsPanel versionId="version-1" />);

    await waitFor(() => expect(api.interpretFormulationDocument).toHaveBeenCalledTimes(2));
    expect(maximumActive).toBe(2);
    releases.splice(0, 2).forEach((release) => release());
    await waitFor(() => expect(api.interpretFormulationDocument).toHaveBeenCalledTimes(3));
    releases.splice(0).forEach((release) => release());
    await waitFor(() => expect(active).toBe(0));
    expect(maximumActive).toBe(2);
  });

  it("does not ask users to reconfirm a high-confidence supplier composition", async () => {
    api.listFormulationDocuments.mockResolvedValue([{ ...attachment }]);
    render(<SupplierDocumentsPanel versionId="version-1" />);

    expect(await screen.findByText(/Supplier composition · recognised automatically/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Supplier composition" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("All documents are ready");
    expect(api.updateSupplierDocument).not.toHaveBeenCalled();
  });

  it("allows any proposed document role to be corrected without making ordinary ingredient lists reusable", async () => {
    const user = userEvent.setup();
    api.listFormulationDocuments.mockResolvedValue([{
      ...attachment,
      detected_roles: [{
        role: "supplier_composition", confidence: "medium", page: 1,
        source_snippet: "Possible composition", reasons: [],
      }],
    }]);
    api.getSupplierDocument.mockResolvedValue({
      id: "supplier-1", revision: 0, extraction_result: {}, confirmed_roles: [],
    });
    api.updateSupplierDocument.mockResolvedValue({ id: "supplier-1", revision: 1 });
    api.updateFormulationDocument.mockResolvedValue({
      ...attachment,
      revision: 1,
      confirmed_roles: ["ingredient_list"],
      governing_for_material: false,
    });
    render(<SupplierDocumentsPanel versionId="version-1" />);

    await user.selectOptions(await screen.findByLabelText("Other document type"), "ingredient_list");

    await waitFor(() => expect(api.updateSupplierDocument).toHaveBeenCalledWith(
      "supplier-1", 0,
      { confirmed_roles: ["ingredient_list"], library_status: "needs_confirmation" },
    ));
    expect(api.updateFormulationDocument).toHaveBeenCalledWith(
      "attachment-1", 0,
      { confirmed_roles: ["ingredient_list"], governing_for_material: false },
    );
  });

  it("attaches an available saved document without uploading bytes", async () => {
    const user = userEvent.setup();
    api.listSupplierDocuments.mockResolvedValue([{
      id: "saved-1", trade_name: "MATRIXYL 3000", product_code: "SE28264",
      original_filename: "matrixyl.pdf", document_revision_label: "Rev 4",
    }]);
    api.attachSupplierDocument.mockResolvedValue({
      ...attachment,
      id: "attachment-2",
      supplier_document_id: "saved-1",
      original_filename: "matrixyl.pdf",
      confirmed_roles: ["supplier_composition"],
    });
    render(<SupplierDocumentsPanel versionId="version-1" />);

    await user.selectOptions(await screen.findByLabelText("Saved supplier document"), "saved-1");
    await user.click(screen.getByRole("button", { name: "Attach" }));

    await waitFor(() => expect(api.attachSupplierDocument).toHaveBeenCalledWith("version-1", "saved-1"));
    expect(api.uploadFormulationDocuments).not.toHaveBeenCalled();
    expect(await screen.findByText("matrixyl.pdf")).toBeInTheDocument();
  });

  it("opens the authorised private source from its short-lived URL", async () => {
    const user = userEvent.setup();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    api.listFormulationDocuments.mockResolvedValue([{ ...attachment }]);
    api.getSupplierDocumentFile.mockResolvedValue({
      url: "https://storage.example.test/signed-source",
      expires_in: 60,
    });
    render(<SupplierDocumentsPanel versionId="version-1" />);

    await user.click(await screen.findByRole("button", { name: "View source" }));

    await waitFor(() => expect(api.getSupplierDocumentFile).toHaveBeenCalledWith("supplier-1"));
    expect(click).toHaveBeenCalledTimes(1);
    click.mockRestore();
  });

  it("searches the private saved-document library before attachment", async () => {
    const user = userEvent.setup();
    api.listSupplierDocuments.mockResolvedValue([]);
    render(<SupplierDocumentsPanel versionId="version-1" />);
    await screen.findByText("No supporting documents attached");

    await user.type(screen.getByLabelText("Find a saved SDS or composition file"), "EN80159");

    await waitFor(() => expect(api.listSupplierDocuments).toHaveBeenCalledWith({
      availableOnly: true,
      search: "EN80159",
    }));
  });

  it("manages saved revisions without removing historical references silently", async () => {
    const user = userEvent.setup();
    api.listSupplierDocuments.mockImplementation((options: { includeArchived?: boolean }) => (
      Promise.resolve(options?.includeArchived ? [savedDocument] : [])
    ));
    api.updateSupplierDocument.mockResolvedValue({ ...savedDocument, library_status: "archived", revision: 1 });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SupplierDocumentsPanel versionId="version-1" />);
    await screen.findByText("No supporting documents attached");

    await user.click(screen.getByRole("button", { name: "View saved documents" }));
    expect(await screen.findByText("MATRIXYL 3000")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.updateSupplierDocument).toHaveBeenCalledWith(
      "saved-1", 0, { library_status: "archived" },
    ));
    expect(screen.getByText("Archived")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Permanently delete MATRIXYL 3000" }));
    await waitFor(() => expect(api.deleteSupplierDocument).toHaveBeenCalledWith("saved-1"));
    expect(confirm).toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("lets a reviewer link a changed file to its exact previous revision", async () => {
    const user = userEvent.setup();
    const newer = {
      ...savedDocument,
      id: "saved-2",
      sha256: "c".repeat(64),
      original_filename: "matrixyl-rev5.pdf",
      document_revision_label: "Rev 5",
      revision: 2,
    };
    api.listSupplierDocuments.mockImplementation((options: { includeArchived?: boolean }) => (
      Promise.resolve(options?.includeArchived ? [newer, savedDocument] : [])
    ));
    api.updateSupplierDocument.mockResolvedValue({
      ...newer,
      supersedes_supplier_document_id: "saved-1",
      revision: 3,
    });
    render(<SupplierDocumentsPanel versionId="version-1" />);
    await screen.findByText("No supporting documents attached");

    await user.click(screen.getByRole("button", { name: "View saved documents" }));
    await user.selectOptions(await screen.findByLabelText("Previous revision for MATRIXYL 3000 Rev 5"), "saved-1");

    await waitFor(() => expect(api.updateSupplierDocument).toHaveBeenCalledWith(
      "saved-2", 2, { supersedes_supplier_document_id: "saved-1" },
    ));
  });

  it("persists corrected metadata for future saved-document searches", async () => {
    const user = userEvent.setup();
    api.listSupplierDocuments.mockImplementation((options: { includeArchived?: boolean }) => (
      Promise.resolve(options?.includeArchived ? [savedDocument] : [])
    ));
    api.updateSupplierDocument.mockResolvedValue({
      ...savedDocument,
      supplier_name: "Reviewed Supplier",
      revision: 1,
    });
    render(<SupplierDocumentsPanel versionId="version-1" />);
    await screen.findByText("No supporting documents attached");

    await user.click(screen.getByRole("button", { name: "View saved documents" }));
    await user.click(await screen.findByText("Edit saved details"));
    await user.clear(screen.getByLabelText("Supplier"));
    await user.type(screen.getByLabelText("Supplier"), "Reviewed Supplier");
    await user.click(screen.getByRole("button", { name: "Save details" }));

    await waitFor(() => expect(api.updateSupplierDocument).toHaveBeenCalledWith(
      "saved-1", 0, {
        supplier_name: "Reviewed Supplier",
        trade_name: "MATRIXYL 3000",
        product_code: "SE28264",
        document_revision_label: "Rev 4",
      },
    ));
  });

  it("retries a retained image-only SDS without asking for another upload", async () => {
    const user = userEvent.setup();
    const interrupted = {
      ...attachment,
      processing_status: "interrupted",
      error: { code: "agent_pdf_text_unavailable", message: "No selectable text", recoverable: true },
    };
    api.listFormulationDocuments.mockResolvedValue([interrupted]);
    api.retryFormulationDocument.mockResolvedValue({
      ...interrupted,
      processing_status: "needs_confirmation",
      revision: 1,
      error: null,
    });
    render(<SupplierDocumentsPanel versionId="version-1" />);

    await user.click(await screen.findByRole("button", { name: "Retry saved file" }));

    await waitFor(() => expect(api.retryFormulationDocument).toHaveBeenCalledWith("attachment-1"));
    expect(api.uploadFormulationDocuments).not.toHaveBeenCalled();
    expect(screen.queryByText("No selectable text")).not.toBeInTheDocument();
  });

  it("offers safe resume for a persisted processing state after refresh", async () => {
    const user = userEvent.setup();
    const processing = { ...attachment, processing_status: "extracting" };
    api.listFormulationDocuments.mockResolvedValue([processing]);
    api.retryFormulationDocument.mockResolvedValue({
      ...processing,
      processing_status: "needs_confirmation",
      revision: 1,
    });
    render(<SupplierDocumentsPanel versionId="version-1" />);

    expect(await screen.findByText("Processing · Reading document · 1 page")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Check or resume" }));

    await waitFor(() => expect(api.retryFormulationDocument).toHaveBeenCalledWith("attachment-1"));
    expect(api.uploadFormulationDocuments).not.toHaveBeenCalled();
  });

  it("places every supplier file in one clear workflow state", async () => {
    api.listFormulationDocuments.mockResolvedValue([
      { ...attachment, id: "ready", confirmed_roles: ["supplier_composition"] },
      { ...attachment, id: "processing", original_filename: "processing.pdf", processing_status: "extracting" },
      {
        ...attachment,
        id: "choice",
        original_filename: "choice.pdf",
        detected_roles: [{ role: "technical_document", confidence: "medium", page: 1, source_snippet: null, reasons: [] }],
      },
      {
        ...attachment,
        id: "retry",
        original_filename: "retry.pdf",
        processing_status: "interrupted",
        error: { code: "parse_failed", message: "Try again", recoverable: true },
      },
    ]);

    render(<SupplierDocumentsPanel versionId="version-1" />);

    expect(await screen.findByText("1 ready · 1 processing · 1 choice needed · 1 retry needed")).toBeInTheDocument();
    expect(screen.getByText("2 documents need action before screening")).toBeInTheDocument();
    expect(screen.getByText(/Choice needed · Technical document/)).toBeInTheDocument();
    expect(screen.getByText(/Retry needed · Supplier composition/)).toBeInTheDocument();
  });

  it("lets the reviewer choose the exact supplier revision used for calculation", async () => {
    const user = userEvent.setup();
    const confirmed = {
      ...attachment,
      confirmed_roles: ["supplier_composition"],
      detected_roles: [{
        role: "supplier_composition", confidence: "medium", page: 1,
        source_snippet: "Possible composition", reasons: [],
      }],
      governing_for_material: false,
    };
    api.listFormulationDocuments.mockResolvedValue([confirmed]);
    api.updateFormulationDocument.mockResolvedValue({
      ...confirmed,
      governing_for_material: true,
      revision: 1,
    });
    render(<SupplierDocumentsPanel versionId="version-1" />);

    await user.click(await screen.findByLabelText("Use this file"));

    await waitFor(() => expect(api.updateFormulationDocument).toHaveBeenCalledWith(
      "attachment-1", 0, { governing_for_material: true },
    ));
  });

  it("uses one current revision when two files describe the same supplier material", async () => {
    const user = userEvent.setup();
    const extraction_result = {
      supplier_materials: [{ trade_name: "LumiMatrix 3000", product_code: "LMX-3000" }],
    };
    const first = {
      ...attachment,
      id: "attachment-a",
      original_filename: "LumiMatrix Rev A.pdf",
      extraction_result,
      governing_for_material: true,
    };
    const second = {
      ...attachment,
      id: "attachment-b",
      original_filename: "LumiMatrix Rev B.pdf",
      extraction_result,
      governing_for_material: true,
    };
    api.listFormulationDocuments.mockResolvedValue([first, second]);
    api.updateFormulationDocument.mockImplementation(async (id, revision, changes) => ({
      ...(id === first.id ? first : second),
      ...changes,
      revision: revision + 1,
    }));
    render(<SupplierDocumentsPanel versionId="version-1" />);

    const choices = await screen.findAllByLabelText("Use this revision");
    await user.click(choices[1]);

    await waitFor(() => expect(api.updateFormulationDocument).toHaveBeenCalledWith(
      first.id, first.revision, { governing_for_material: false },
    ));
    expect(screen.getByText("All documents are ready")).toBeInTheDocument();
  });
});
