import { AlertCircle, Archive, CheckCircle2, ExternalLink, FileStack, Library, LoaderCircle, Paperclip, RotateCcw, Trash2, Upload, X } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import {
  attachSupplierDocument,
  deleteSupplierDocument,
  detachFormulationDocument,
  getSupplierDocument,
  getSupplierDocumentFile,
  interpretFormulationDocument,
  listFormulationDocuments,
  listSupplierDocuments,
  retryFormulationDocument,
  updateFormulationDocument,
  updateSupplierDocument,
  uploadFormulationDocuments,
} from "../api/cases";
import type { DocumentRole, FormulationDocument, SupplierDocument } from "../types/cases";

const roleLabels: Record<DocumentRole, string> = {
  finished_product_formulation: "Finished formulation",
  ingredient_list: "Ingredient list",
  supplier_composition: "Supplier composition",
  sds_msds: "SDS / MSDS",
  technical_document: "Technical document",
  unknown: "Role needs confirmation",
};

function primaryRole(document: FormulationDocument): DocumentRole {
  const extraction = document.extraction_result as {
    classification?: { recommended_extraction_schema?: string };
    supplier_materials?: unknown[];
  } | null;
  const recommended = extraction?.classification?.recommended_extraction_schema;
  if (extraction?.supplier_materials?.length) {
    if (recommended === "sds_composition") return "sds_msds";
    if (recommended === "supplier_composition") return "supplier_composition";
    const reliableSupplierRoles = [...new Set(document.detected_roles
      .filter((item) => ["supplier_composition", "sds_msds"].includes(item.role)
        && ["confirmed", "high"].includes(item.confidence))
      .map((item) => item.role))];
    if (reliableSupplierRoles.length === 1) return reliableSupplierRoles[0];
  }
  return document.confirmed_roles[0] ?? document.detected_roles[0]?.role ?? "unknown";
}

function automaticallyRecognisedSupplier(document: FormulationDocument): boolean {
  const role = primaryRole(document);
  const evidence = document.detected_roles.find((item) => item.role === role);
  return ["supplier_composition", "sds_msds"].includes(role)
    && Boolean(evidence && ["confirmed", "high"].includes(evidence.confidence));
}

type DocumentWorkflowState = "processing" | "ready" | "choice_needed" | "retry_needed";

function documentWorkflowState(
  document: FormulationDocument,
  revisionChoiceNeeded: boolean,
): DocumentWorkflowState {
  if (["interrupted", "failed"].includes(document.processing_status)) return "retry_needed";
  if (["uploaded", "parsing", "classifying", "extracting"].includes(document.processing_status)) return "processing";
  if (revisionChoiceNeeded) return "choice_needed";
  if (
    document.processing_status === "ready"
    && (document.confirmed_roles.length > 0 || automaticallyRecognisedSupplier(document))
  ) return "ready";
  if (automaticallyRecognisedSupplier(document)) return "ready";
  return "choice_needed";
}

function supplierMaterialKeys(document: FormulationDocument): string[] {
  const extraction = document.extraction_result as {
    supplier_materials?: Array<{
      trade_name?: string | null;
      supplier_name?: string | null;
      product_code?: string | null;
    }>;
  } | null;
  return (extraction?.supplier_materials ?? []).map((material) => {
    const productCode = (material.product_code ?? "").trim().toLocaleLowerCase();
    if (productCode) return `code:${productCode}`;
    const supplier = (material.supplier_name ?? "").trim().toLocaleLowerCase();
    const tradeName = (material.trade_name ?? "").trim().toLocaleLowerCase();
    return tradeName ? `supplier:${supplier}|trade:${tradeName}` : "";
  }).filter(Boolean);
}

function documentName(document: SupplierDocument): string {
  return document.trade_name || document.product_code || document.original_filename;
}

type SupplierMetadataDraft = Pick<SupplierDocument, "supplier_name" | "trade_name" | "product_code" | "document_revision_label">;

export interface SupplierDocumentWorkflowStatus {
  blocking: boolean;
  unresolvedRevisionGroups: number;
  reason: string | null;
}

interface RevisionGroup {
  key: string;
  name: string;
  documents: FormulationDocument[];
  recommendedDocumentId: string | null;
  recommendationReason: string | null;
}

function materialName(document: FormulationDocument, key: string): string {
  const extraction = document.extraction_result as {
    supplier_materials?: Array<{ trade_name?: string | null; product_code?: string | null }>;
  } | null;
  const material = (extraction?.supplier_materials ?? []).find((candidate) => {
    const productCode = (candidate.product_code ?? "").trim().toLocaleLowerCase();
    if (productCode && `code:${productCode}` === key) return true;
    const tradeName = (candidate.trade_name ?? "").trim().toLocaleLowerCase();
    return key.endsWith(`|trade:${tradeName}`);
  });
  return material?.trade_name || material?.product_code || "Supplier material";
}

function revisionRecommendation(
  documents: FormulationDocument[],
  savedById: Map<string, SupplierDocument>,
): { documentId: string | null; reason: string | null } {
  const normaliseRevision = (value: string | null | undefined) => (value ?? "")
    .toLocaleLowerCase()
    .replace(/^revision/, "rev")
    .replace(/[^a-z0-9]/g, "");
  const explicitTextSuccessors = documents.flatMap((document) => {
    const sourceText = JSON.stringify(document.parsed_content ?? {});
    const match = /supersedes?\s+(?:(?:document\s+)?revision\s*)?((?:rev(?:ision)?\.?\s*)?[a-z0-9][a-z0-9._/-]*)/i.exec(sourceText);
    if (!match) return [];
    const supersededRevision = normaliseRevision(match[1]);
    const hasMatchingPredecessor = documents.some((candidate) => (
      candidate.id !== document.id
      && normaliseRevision(candidate.document_revision_label) === supersededRevision
    ));
    return hasMatchingPredecessor ? [{ document, label: match[1] }] : [];
  });
  if (explicitTextSuccessors.length === 1) {
    const successor = explicitTextSuccessors[0];
    return { documentId: successor.document.id, reason: `The source states that it supersedes ${successor.label}.` };
  }

  const attachedSavedIds = new Set(documents.flatMap((document) => document.supplier_document_id ? [document.supplier_document_id] : []));
  const explicitSuccessors = documents.filter((document) => {
    const source = document.supplier_document_id ? savedById.get(document.supplier_document_id) : null;
    return Boolean(source?.supersedes_supplier_document_id && attachedSavedIds.has(source.supersedes_supplier_document_id));
  });
  if (explicitSuccessors.length === 1) {
    return { documentId: explicitSuccessors[0].id, reason: "This file is explicitly linked as superseding another attached revision." };
  }

  const dated = documents.flatMap((document) => {
    const source = document.supplier_document_id ? savedById.get(document.supplier_document_id) : null;
    const timestamp = source?.document_date ? Date.parse(source.document_date) : Number.NaN;
    return Number.isFinite(timestamp) ? [{ document, timestamp }] : [];
  }).sort((left, right) => right.timestamp - left.timestamp);
  if (dated.length >= 2 && dated[0].timestamp > dated[1].timestamp) {
    return { documentId: dated[0].document.id, reason: "This file has the latest stated document date." };
  }
  return { documentId: null, reason: null };
}

export interface SupplierDocumentsPanelHandle {
  openManager: (documentId?: string) => void;
}

export const SupplierDocumentsPanel = forwardRef<SupplierDocumentsPanelHandle, {
  versionId: string;
  onDocumentsChanged?: (documents: FormulationDocument[]) => void;
  onWorkflowStatusChange?: (status: SupplierDocumentWorkflowStatus) => void;
  compact?: boolean;
  allowUploads?: boolean;
}>(function SupplierDocumentsPanel({
  versionId,
  onDocumentsChanged,
  onWorkflowStatusChange,
  compact = false,
  allowUploads = true,
}, ref) {
  const uploadInput = useRef<HTMLInputElement>(null);
  const autoStarted = useRef(new Set<string>());
  const interpretationQueue = useRef<FormulationDocument[]>([]);
  const activeInterpretations = useRef(0);
  const mounted = useRef(true);
  const processingGeneration = useRef(0);
  const [documents, setDocuments] = useState<FormulationDocument[]>([]);
  const [library, setLibrary] = useState<SupplierDocument[]>([]);
  const [librarySearch, setLibrarySearch] = useState("");
  const [selectedSavedId, setSelectedSavedId] = useState("");
  const [managingLibrary, setManagingLibrary] = useState(false);
  const [managedLibrary, setManagedLibrary] = useState<SupplierDocument[]>([]);
  const [metadataDrafts, setMetadataDrafts] = useState<Record<string, SupplierMetadataDraft>>({});
  const [managerLoading, setManagerLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [managerOpen, setManagerOpen] = useState(false);
  const [targetDocumentId, setTargetDocumentId] = useState<string | null>(null);

  useImperativeHandle(ref, () => ({
    openManager: (documentId?: string) => {
      setTargetDocumentId(documentId ?? null);
      setManagerOpen(true);
    },
  }), []);

  useEffect(() => {
    if (!managerOpen || !targetDocumentId) return;
    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById(`supplier-document-${targetDocumentId}`);
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
      target?.querySelector<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled])")?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [managerOpen, targetDocumentId]);

  const load = async () => {
    setError(null);
    try {
      const [attached, saved] = await Promise.all([
        listFormulationDocuments(versionId),
        listSupplierDocuments({ availableOnly: true }),
      ]);
      setDocuments(attached);
      onDocumentsChanged?.(attached);
      setLibrary(saved);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Supporting documents could not be loaded.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    mounted.current = true;
    processingGeneration.current += 1;
    autoStarted.current.clear();
    interpretationQueue.current = [];
    activeInterpretations.current = 0;
    void load();
    return () => { mounted.current = false; };
  }, [versionId]);

  useEffect(() => {
    const pending = documents.filter((document) => (
      ["uploaded", "ready", "needs_confirmation"].includes(document.processing_status)
      && Boolean(document.supplier_document_id)
      && (
        document.processing_status === "uploaded"
        || document.extraction_current === false
      )
      && !autoStarted.current.has(document.id)
    ));
    if (pending.length === 0) return;

    pending.forEach((document) => autoStarted.current.add(document.id));
    interpretationQueue.current.push(...pending);

    const runNext = () => {
      while (mounted.current && activeInterpretations.current < 2) {
        const document = interpretationQueue.current.shift();
        if (!document) return;
        const generation = processingGeneration.current;
        activeInterpretations.current += 1;
        void interpretFormulationDocument(document.id).then((updated) => {
          if (!mounted.current || generation !== processingGeneration.current) return;
          setDocuments((current) => {
            const next = current.map((item) => item.id === updated.id ? updated : item);
            onDocumentsChanged?.(next);
            return next;
          });
        }).catch((caught) => {
          if (mounted.current && generation === processingGeneration.current) {
            setError(caught instanceof Error ? caught.message : "A retained document could not be interpreted.");
          }
        }).finally(() => {
          if (generation !== processingGeneration.current) return;
          activeInterpretations.current -= 1;
          runNext();
          if (
            mounted.current
            && activeInterpretations.current === 0
            && interpretationQueue.current.length === 0
          ) {
            void load();
          }
        });
      }
    };
    runNext();
  }, [documents, versionId]);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      void listSupplierDocuments({
        availableOnly: true,
        search: librarySearch.trim() || undefined,
      }).then((saved) => {
        if (active) setLibrary(saved);
      }).catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "Saved documents could not be searched.");
      });
    }, 200);
    return () => { active = false; window.clearTimeout(timer); };
  }, [librarySearch]);

  const attachedSavedIds = useMemo(
    () => new Set(documents.flatMap((item) => item.supplier_document_id ? [item.supplier_document_id] : [])),
    [documents],
  );
  const availableSaved = library.filter((item) => !attachedSavedIds.has(item.id));
  const materialKeyCounts = useMemo(() => {
    const counts = new Map<string, number>();
    documents.flatMap(supplierMaterialKeys).forEach((key) => counts.set(key, (counts.get(key) ?? 0) + 1));
    return counts;
  }, [documents]);
  const revisionConflictKeys = useMemo(
    () => new Set([...materialKeyCounts.entries()].filter(([, count]) => count > 1).map(([key]) => key)),
    [materialKeyCounts],
  );
  const unresolvedRevisionConflictKeys = useMemo(() => new Set(
    [...revisionConflictKeys].filter((key) => documents.filter((document) => (
      supplierMaterialKeys(document).includes(key) && document.governing_for_material
    )).length !== 1),
  ), [documents, revisionConflictKeys]);
  const savedById = useMemo(() => new Map(library.map((document) => [document.id, document])), [library]);
  const revisionGroups = useMemo<RevisionGroup[]>(() => [...revisionConflictKeys].map((key) => {
    const groupedDocuments = documents.filter((document) => supplierMaterialKeys(document).includes(key));
    const recommendation = revisionRecommendation(groupedDocuments, savedById);
    return {
      key,
      name: materialName(groupedDocuments[0], key),
      documents: groupedDocuments,
      recommendedDocumentId: recommendation.documentId,
      recommendationReason: recommendation.reason,
    };
  }), [documents, revisionConflictKeys, savedById]);
  const workflowStatus = useMemo<SupplierDocumentWorkflowStatus>(() => {
    const count = unresolvedRevisionConflictKeys.size;
    return {
      blocking: count > 0,
      unresolvedRevisionGroups: count,
      reason: count > 0
        ? `Choose the current revision for ${count === 1 ? "one supplier material" : `${count} supplier materials`} before screening.`
        : null,
    };
  }, [unresolvedRevisionConflictKeys]);
  useEffect(() => onWorkflowStatusChange?.(workflowStatus), [onWorkflowStatusChange, workflowStatus]);
  const workflowStates = useMemo(() => new Map(documents.map((document) => [
    document.id,
    documentWorkflowState(
      document,
      supplierMaterialKeys(document).some((key) => unresolvedRevisionConflictKeys.has(key)),
    ),
  ])), [documents, unresolvedRevisionConflictKeys]);
  const workflowCounts = useMemo(() => {
    const counts: Record<DocumentWorkflowState, number> = {
      processing: 0,
      ready: 0,
      choice_needed: 0,
      retry_needed: 0,
    };
    workflowStates.forEach((state) => { counts[state] += 1; });
    return counts;
  }, [workflowStates]);
  const workflowSummary = [
    workflowCounts.ready ? `${workflowCounts.ready} ready` : null,
    workflowCounts.processing ? `${workflowCounts.processing} processing` : null,
    workflowCounts.choice_needed ? `${workflowCounts.choice_needed} choice needed` : null,
    workflowCounts.retry_needed ? `${workflowCounts.retry_needed} retry needed` : null,
  ].filter(Boolean).join(" · ");
  const attentionCount = workflowCounts.choice_needed + workflowCounts.retry_needed;

  const loadManagedLibrary = async () => {
    setManagerLoading(true); setError(null);
    try {
      const saved = await listSupplierDocuments({ includeArchived: true });
      setManagedLibrary(saved);
      setMetadataDrafts(Object.fromEntries(saved.map((document) => [document.id, {
        supplier_name: document.supplier_name,
        trade_name: document.trade_name,
        product_code: document.product_code,
        document_revision_label: document.document_revision_label,
      }])));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The saved-document library could not be loaded.");
    } finally {
      setManagerLoading(false);
    }
  };

  const toggleLibraryManager = () => {
    const next = !managingLibrary;
    setManagingLibrary(next);
    if (next) void loadManagedLibrary();
  };

  const setLibraryArchived = async (document: SupplierDocument, archived: boolean) => {
    if (busyKey) return;
    setBusyKey(`archive:${document.id}`); setError(null);
    try {
      const updated = await updateSupplierDocument(document.id, document.revision, {
        library_status: archived ? "archived" : "available",
      });
      setManagedLibrary((current) => current.map((item) => item.id === updated.id ? updated : item));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The saved document could not be updated.");
    } finally {
      setBusyKey(null);
    }
  };

  const setPreviousRevision = async (document: SupplierDocument, predecessorId: string) => {
    if (busyKey) return;
    setBusyKey(`revision:${document.id}`); setError(null);
    try {
      const updated = await updateSupplierDocument(document.id, document.revision, {
        supersedes_supplier_document_id: predecessorId || null,
      });
      setManagedLibrary((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The document revision relationship could not be saved.");
    } finally {
      setBusyKey(null);
    }
  };

  const saveLibraryMetadata = async (document: SupplierDocument) => {
    if (busyKey) return;
    const draft = metadataDrafts[document.id];
    if (!draft) return;
    setBusyKey(`metadata:${document.id}`); setError(null);
    try {
      const updated = await updateSupplierDocument(document.id, document.revision, draft);
      setManagedLibrary((current) => current.map((item) => item.id === updated.id ? updated : item));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The saved supplier details could not be updated.");
    } finally {
      setBusyKey(null);
    }
  };

  const updateMetadataDraft = (documentId: string, field: keyof SupplierMetadataDraft, value: string) => {
    setMetadataDrafts((current) => ({
      ...current,
      [documentId]: {
        ...current[documentId],
        [field]: value.trim() ? value : null,
      },
    }));
  };

  const removeSavedDocument = async (document: SupplierDocument) => {
    if (busyKey || !window.confirm(`Permanently delete ${documentName(document)}? Existing formulation references must be detached first.`)) return;
    setBusyKey(`delete-library:${document.id}`); setError(null);
    try {
      await deleteSupplierDocument(document.id);
      setManagedLibrary((current) => current.filter((item) => item.id !== document.id));
      setLibrary((current) => current.filter((item) => item.id !== document.id));
      if (selectedSavedId === document.id) setSelectedSavedId("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The saved document could not be deleted.");
    } finally {
      setBusyKey(null);
    }
  };

  const upload = async (files: FileList | null) => {
    if (!files?.length || uploading) return;
    setUploading(true); setError(null); setNotice(null);
    try {
      const batch = await uploadFormulationDocuments(versionId, Array.from(files));
      setDocuments((current) => [...current, ...batch.documents.filter((item) => !current.some((existing) => existing.id === item.id))]);
      const failureMessage = batch.failures.length
        ? batch.failures.map((failure) => `${failure.filename}: ${failure.message}`).join(" ")
        : null;
      await load();
      if (failureMessage) setError(failureMessage);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The supporting document could not be uploaded.");
    } finally {
      if (uploadInput.current) uploadInput.current.value = "";
      setUploading(false);
    }
  };

  const attachSaved = async () => {
    if (!selectedSavedId || busyKey) return;
    setBusyKey("attach"); setError(null);
    try {
      const attached = await attachSupplierDocument(versionId, selectedSavedId);
      setDocuments((current) => {
        const next = [...current, attached];
        onDocumentsChanged?.(next);
        return next;
      });
      setSelectedSavedId("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The saved document could not be attached.");
    } finally {
      setBusyKey(null);
    }
  };

  const confirmRole = async (document: FormulationDocument, role: DocumentRole) => {
    if (!document.supplier_document_id || busyKey) return;
    setBusyKey(`confirm:${document.id}`); setError(null); setNotice(null);
    try {
      const saved = await getSupplierDocument(document.supplier_document_id);
      await updateSupplierDocument(saved.id, saved.revision, role === "sds_msds" || role === "supplier_composition" ? {
        confirmed_roles: [role],
        library_status: "available",
      } : {
        confirmed_roles: [role],
        library_status: "needs_confirmation",
      });
      const updated = await updateFormulationDocument(document.id, document.revision, {
        confirmed_roles: [role],
        governing_for_material: role === "sds_msds" || role === "supplier_composition",
      });
      setDocuments((current) => {
        const next = current.map((item) => item.id === updated.id ? updated : item);
        onDocumentsChanged?.(next);
        return next;
      });
      await load();
      if (role === "sds_msds" || role === "supplier_composition") {
        setNotice(`${document.original_filename} was saved for future formulations in this workspace.`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The document role could not be confirmed.");
    } finally {
      setBusyKey(null);
    }
  };

  const detach = async (document: FormulationDocument) => {
    if (busyKey) return;
    setBusyKey(`detach:${document.id}`); setError(null);
    try {
      await detachFormulationDocument(versionId, document.id);
      setDocuments((current) => {
        const next = current.filter((item) => item.id !== document.id);
        onDocumentsChanged?.(next);
        return next;
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The document could not be detached.");
    } finally {
      setBusyKey(null);
    }
  };

  const selectGoverning = async (document: FormulationDocument) => {
    if (busyKey) return;
    setBusyKey(`governing:${document.id}`); setError(null);
    try {
      const keys = new Set(supplierMaterialKeys(document));
      let nextDocuments = [...documents];
      const currentDocument = nextDocuments.find((item) => item.id === document.id) ?? document;
      const updated = currentDocument.governing_for_material
        ? currentDocument
        : await updateFormulationDocument(currentDocument.id, currentDocument.revision, {
          governing_for_material: true,
        });
      nextDocuments = nextDocuments.map((item) => item.id === updated.id ? updated : item);
      const selectedPeers = nextDocuments.filter((candidate) => (
        candidate.id !== document.id
        && candidate.governing_for_material
        && supplierMaterialKeys(candidate).some((key) => keys.has(key))
      ));
      for (const peer of selectedPeers) {
        const updatedPeer = await updateFormulationDocument(peer.id, peer.revision, {
          governing_for_material: false,
        });
        nextDocuments = nextDocuments.map((item) => item.id === updatedPeer.id ? updatedPeer : item);
      }
      setDocuments(nextDocuments);
      onDocumentsChanged?.(nextDocuments);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The current supplier file could not be selected.");
      await load();
    } finally {
      setBusyKey(null);
    }
  };

  const retry = async (document: FormulationDocument) => {
    if (busyKey) return;
    setBusyKey(`retry:${document.id}`); setError(null);
    try {
      const updated = await retryFormulationDocument(document.id);
      setDocuments((current) => {
        const next = current.map((item) => item.id === updated.id ? updated : item);
        onDocumentsChanged?.(next);
        return next;
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The retained document could not be processed.");
    } finally {
      setBusyKey(null);
    }
  };

  const openSource = async (document: FormulationDocument) => {
    if (!document.supplier_document_id || busyKey) return;
    setBusyKey(`source:${document.id}`); setError(null);
    try {
      const source = await getSupplierDocumentFile(document.supplier_document_id);
      const anchor = window.document.createElement("a");
      anchor.href = source.url;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.click();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The private source could not be opened.");
    } finally {
      setBusyKey(null);
    }
  };

  const manager = <section className="supplier-documents-panel" aria-labelledby="supplier-documents-title">
    <div className="supplier-documents-heading">
      <div>
        <h2 id="supplier-documents-title">Supplier files</h2>
        <p>Upload composition statements or SDS files that explain the trade names used in this formulation.</p>
      </div>
      {allowUploads ? <label className={`secondary-button supplier-upload-button ${uploading ? "is-disabled" : ""}`}>
        {uploading ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}
        {uploading ? "Uploading documents…" : "Add documents"}
        <input
          ref={uploadInput}
          type="file"
          multiple
          accept=".pdf,.csv,.tsv,.txt,.xlsx,.xls,.json"
          disabled={uploading}
          onChange={(event) => void upload(event.target.files)}
        />
      </label> : null}
    </div>

    {allowUploads ? <details className="supplier-library-disclosure">
      <summary><Library size={16} aria-hidden="true" /> Reuse a saved supplier file</summary>
      <p className="supplier-library-explainer">Regulens keeps the private original file and the ingredients extracted from it in your workspace. Reusing it avoids another upload. Each formulation keeps its own saved copy of the extracted information, so older screening results do not change.</p>
      <div className="supplier-library-row">
      <Library size={17} aria-hidden="true" />
      <label htmlFor="saved-supplier-search">Find a saved SDS or composition file</label>
      <input
        id="saved-supplier-search"
        type="search"
        value={librarySearch}
        placeholder="Supplier, trade name, product code, revision or filename"
        disabled={Boolean(busyKey)}
        onChange={(event) => setLibrarySearch(event.target.value)}
      />
      <label className="sr-only" htmlFor="saved-supplier-document">Saved supplier document</label>
      <select
        id="saved-supplier-document"
        value={selectedSavedId}
        disabled={Boolean(busyKey) || availableSaved.length === 0}
        onChange={(event) => setSelectedSavedId(event.target.value)}
      >
        <option value="">{availableSaved.length ? "Choose saved SDS or composition" : "No other saved documents"}</option>
        {availableSaved.map((item) => <option key={item.id} value={item.id}>
          {[documentName(item), item.supplier_name, item.product_code, item.document_revision_label,
            item.last_used_at ? `last used ${new Date(item.last_used_at).toLocaleDateString()}` : null]
            .filter((value, index, all) => Boolean(value) && all.indexOf(value) === index).join(" · ")}
        </option>)}
      </select>
      <button className="secondary-button" type="button" disabled={!selectedSavedId || Boolean(busyKey)} onClick={() => void attachSaved()}>
        {busyKey === "attach" ? <LoaderCircle className="spin" size={16} /> : <Paperclip size={16} />}
        Attach
      </button>
      <button className="secondary-button" type="button" aria-expanded={managingLibrary} onClick={toggleLibraryManager}>
        <Library size={16} />
        {managingLibrary ? "Close saved documents" : "View saved documents"}
      </button>
      </div>
    </details> : null}

    {managingLibrary ? <section className="supplier-library-manager" aria-labelledby="saved-supplier-documents-title">
      <div className="supplier-library-manager-heading">
        <div><h3 id="saved-supplier-documents-title">Saved SDS and supplier documents</h3><p>Archived revisions remain available to historical formulations but are hidden from new attachment searches.</p></div>
        <button className="secondary-button" type="button" disabled={managerLoading || Boolean(busyKey)} onClick={() => void loadManagedLibrary()}>
          {managerLoading ? <LoaderCircle className="spin" size={16} /> : <RotateCcw size={16} />} Refresh
        </button>
      </div>
      {managerLoading ? <div className="supplier-document-loading"><LoaderCircle className="spin" size={18} /> Loading saved documents</div> : null}
      {!managerLoading && managedLibrary.length === 0 ? <p className="supplier-library-manager-empty">No saved supplier documents yet.</p> : null}
      {managedLibrary.length ? <ul className="supplier-library-manager-list">
        {managedLibrary.map((document) => {
          const revisionCandidates = managedLibrary.filter((candidate) => candidate.id !== document.id && (
            (document.product_code && candidate.product_code === document.product_code)
            || (document.trade_name && candidate.trade_name?.toLocaleLowerCase() === document.trade_name.toLocaleLowerCase())
          ));
          return <li key={document.id}>
          <div><strong>{documentName(document)}</strong><span>{[document.supplier_name, document.product_code, document.document_revision_label, document.original_filename].filter((value, index, all) => Boolean(value) && all.indexOf(value) === index).join(" · ")}</span><small>{document.library_status === "archived" ? "Archived" : "Available for reuse"}</small>
            <details className="supplier-library-metadata"><summary>Edit saved details</summary><div>
              <label>Supplier<input value={metadataDrafts[document.id]?.supplier_name ?? ""} disabled={Boolean(busyKey)} onChange={(event) => updateMetadataDraft(document.id, "supplier_name", event.target.value)} /></label>
              <label>Trade name<input value={metadataDrafts[document.id]?.trade_name ?? ""} disabled={Boolean(busyKey)} onChange={(event) => updateMetadataDraft(document.id, "trade_name", event.target.value)} /></label>
              <label>Product code<input value={metadataDrafts[document.id]?.product_code ?? ""} disabled={Boolean(busyKey)} onChange={(event) => updateMetadataDraft(document.id, "product_code", event.target.value)} /></label>
              <label>Revision<input value={metadataDrafts[document.id]?.document_revision_label ?? ""} disabled={Boolean(busyKey)} onChange={(event) => updateMetadataDraft(document.id, "document_revision_label", event.target.value)} /></label>
              <button className="secondary-button" type="button" disabled={Boolean(busyKey)} onClick={() => void saveLibraryMetadata(document)}>{busyKey === `metadata:${document.id}` ? <LoaderCircle className="spin" size={16} /> : <CheckCircle2 size={16} />} Save details</button>
            </div></details>
            {revisionCandidates.length || document.supersedes_supplier_document_id ? <label className="supplier-revision-link"><span>Previous revision</span><select aria-label={`Previous revision for ${documentName(document)}${document.document_revision_label ? ` ${document.document_revision_label}` : ""}`} value={document.supersedes_supplier_document_id || ""} disabled={Boolean(busyKey)} onChange={(event) => void setPreviousRevision(document, event.target.value)}><option value="">Not linked</option>{revisionCandidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{[documentName(candidate), candidate.document_revision_label, candidate.original_filename].filter((value, index, all) => Boolean(value) && all.indexOf(value) === index).join(" · ")}</option>)}</select></label> : null}
          </div>
          <div className="supplier-document-item-actions">
            <button className="secondary-button" type="button" disabled={Boolean(busyKey)} onClick={() => void setLibraryArchived(document, document.library_status !== "archived")}>
              {busyKey === `archive:${document.id}` ? <LoaderCircle className="spin" size={16} /> : <Archive size={16} />}
              {document.library_status === "archived" ? "Restore" : "Archive"}
            </button>
            <button className="icon-button danger-icon-button" type="button" aria-label={`Permanently delete ${documentName(document)}`} disabled={Boolean(busyKey)} onClick={() => void removeSavedDocument(document)}>
              {busyKey === `delete-library:${document.id}` ? <LoaderCircle className="spin" size={16} /> : <Trash2 size={16} />}
            </button>
          </div>
        </li>;})}
      </ul> : null}
    </section> : null}

    {notice ? <div className="supplier-document-notice" role="status"><CheckCircle2 size={17} /><span>{notice}</span><button type="button" aria-label="Dismiss saved-document message" onClick={() => setNotice(null)}><X size={14} /></button></div> : null}
    {error ? <div className="supplier-document-error" role="alert"><AlertCircle size={17} /> <span>{error}</span><button type="button" onClick={() => void load()}>Retry</button></div> : null}

    {loading ? <div className="supplier-document-loading"><LoaderCircle className="spin" size={18} /> Loading source documents</div> : null}
    {!loading && documents.length === 0 ? <div className="supplier-document-empty">
      <FileStack size={21} />
      <div><strong>No supporting documents attached</strong><span>Ordinary INCI formulations still work normally. Add an SDS only when it helps explain a trade-name material.</span></div>
    </div> : null}

    {documents.length > 0 ? <div className="supplier-document-summary" role="status">
      <strong>{workflowSummary}</strong>
      <span>{attentionCount ? `${attentionCount} document${attentionCount === 1 ? "" : "s"} need action before screening` : workflowCounts.processing ? "Document processing is still in progress" : "All documents are ready"}</span>
    </div> : null}

    {revisionGroups.length > 0 ? <div className="supplier-revision-groups">
      {revisionGroups.map((group) => {
        const selected = group.documents.filter((document) => document.governing_for_material);
        const resolved = selected.length === 1;
        return <section className={`supplier-revision-group ${resolved ? "is-resolved" : "needs-choice"}`} key={group.key} aria-labelledby={`revision-group-${group.key}`}>
          <div className="supplier-revision-group-heading">
            <div>
              <span className="supplier-revision-kicker">{resolved ? "Current revision selected" : "Revision choice required"}</span>
              <h3 id={`revision-group-${group.key}`}>{group.name}</h3>
              <p>Both source files are retained. Only the selected revision is used in concentration calculations.</p>
            </div>
            <span className={`supplier-revision-state ${resolved ? "is-resolved" : ""}`}>{resolved ? "Ready" : "Choose one"}</span>
          </div>
          <div className="supplier-revision-options">
            {group.documents.map((document) => {
              const source = document.supplier_document_id ? savedById.get(document.supplier_document_id) : null;
              const recommended = group.recommendedDocumentId === document.id;
              const current = resolved && document.governing_for_material;
              const revision = document.document_revision_label || source?.document_revision_label;
              return <div className={`supplier-revision-option ${current ? "is-current" : ""}`} key={document.id}>
                <div>
                  <strong>{revision || document.original_filename}</strong>
                  <span>{[revision ? document.original_filename : null, source?.document_date ? new Date(source.document_date).toLocaleDateString() : null].filter(Boolean).join(" · ")}</span>
                  {recommended && group.recommendationReason ? <small>{group.recommendationReason}</small> : null}
                </div>
                <div>
                  {recommended ? <span className="supplier-recommended-badge">Recommended</span> : null}
                  {current ? <span className="supplier-current-badge"><CheckCircle2 size={13} /> Used in calculation</span> : <button className={recommended ? "primary-button" : "secondary-button"} type="button" disabled={Boolean(busyKey)} onClick={() => void selectGoverning(document)}>
                    {busyKey === `governing:${document.id}` ? <LoaderCircle className="spin" size={14} /> : null}
                    {recommended ? `Use ${revision || "recommended revision"}` : `Use ${revision || "this revision"}`}
                  </button>}
                </div>
              </div>;
            })}
          </div>
        </section>;
      })}
    </div> : null}

    {documents.length > 0 ? <ul className="supplier-document-list">
      {documents.map((document) => {
        const role = primaryRole(document);
        const automaticSupplier = automaticallyRecognisedSupplier(document);
        const documentMaterialKeys = supplierMaterialKeys(document);
        const hasRevisionConflict = documentMaterialKeys.some((key) => revisionConflictKeys.has(key));
        const revisionSelectionNeeded = documentMaterialKeys.some((key) => unresolvedRevisionConflictKeys.has(key));
        const interrupted = document.processing_status === "interrupted" || document.processing_status === "failed";
        const processing = ["uploaded", "parsing", "classifying", "extracting"].includes(document.processing_status);
        const needsRole = document.confirmed_roles.length === 0 && !automaticSupplier && !interrupted && !processing;
        const workflowState = workflowStates.get(document.id) ?? "choice_needed";
        const workflowLabel = {
          processing: "Processing",
          ready: "Ready",
          choice_needed: "Choice needed",
          retry_needed: "Retry needed",
        }[workflowState];
        return <li id={`supplier-document-${document.id}`} key={document.id}>
          <div className={`supplier-document-status ${interrupted ? "is-warning" : document.confirmed_roles.length || automaticSupplier ? "is-ready" : ""}`} aria-hidden="true">
            {processing ? <LoaderCircle className="spin" size={18} /> : interrupted ? <AlertCircle size={18} /> : document.confirmed_roles.length || automaticSupplier ? <CheckCircle2 size={18} /> : <FileStack size={18} />}
          </div>
          <div className="supplier-document-copy">
            <strong>{document.original_filename}</strong>
            <span>{workflowLabel} · {processing ? "Reading document" : `${roleLabels[role]}${automaticSupplier ? " · recognised automatically" : ""}`}{document.page_count ? ` · ${document.page_count} page${document.page_count === 1 ? "" : "s"}` : ""}</span>
            {interrupted ? <small>{document.error?.message || "Text extraction did not finish. The private file was kept for retry."}</small> : null}
            {needsRole ? <div className="supplier-role-actions" aria-label={`Confirm the role of ${document.original_filename}`}>
              <span>Confirm document type:</span>
              <button type="button" disabled={Boolean(busyKey)} onClick={() => void confirmRole(document, "supplier_composition")}>Supplier composition</button>
              <button type="button" disabled={Boolean(busyKey)} onClick={() => void confirmRole(document, "sds_msds")}>SDS / MSDS</button>
              <label>
                <span className="sr-only">Other document type</span>
                <select defaultValue="" disabled={Boolean(busyKey)} onChange={(event) => {
                  if (event.target.value) void confirmRole(document, event.target.value as DocumentRole);
                }}>
                  <option value="">Other document type…</option>
                  <option value="finished_product_formulation">Finished formulation</option>
                  <option value="ingredient_list">Ingredient list</option>
                  <option value="technical_document">Technical document</option>
                  <option value="unknown">Keep as unknown</option>
                </select>
              </label>
            </div> : null}
            {!interrupted && ["supplier_composition", "sds_msds"].includes(role) && !hasRevisionConflict && (!automaticSupplier && !document.governing_for_material) ? <label className="supplier-governing-toggle">
              <input
                type="radio"
                name={`current-supplier-file-${documentMaterialKeys[0] ?? document.id}`}
                checked={document.governing_for_material}
                disabled={Boolean(busyKey)}
                onClick={() => void selectGoverning(document)}
                onChange={() => undefined}
              />
              Use this file
            </label> : null}
            {hasRevisionConflict ? <small>{revisionSelectionNeeded
              ? "Waiting for the revision choice above."
              : document.governing_for_material
                ? "Current revision · used in the calculation."
                : "Previous revision · retained for audit only."}</small> : null}
          </div>
          <div className="supplier-document-item-actions">
            {document.supplier_document_id ? <button className="secondary-button" type="button" disabled={Boolean(busyKey)} onClick={() => void openSource(document)}>
              {busyKey === `source:${document.id}` ? <LoaderCircle className="spin" size={16} /> : <ExternalLink size={16} />}
              View source
            </button> : null}
            {(processing || (interrupted && document.error?.recoverable !== false)) && document.supplier_document_id ? <button className="secondary-button" type="button" disabled={Boolean(busyKey)} onClick={() => void retry(document)}>
              {busyKey === `retry:${document.id}` ? <LoaderCircle className="spin" size={16} /> : <RotateCcw size={16} />}
              {processing ? "Check or resume" : "Retry saved file"}
            </button> : null}
            <button className="icon-button" type="button" aria-label={`Detach ${document.original_filename}`} disabled={Boolean(busyKey)} onClick={() => void detach(document)}>
              {busyKey === `detach:${document.id}` ? <LoaderCircle className="spin" size={16} /> : <X size={16} />}
            </button>
          </div>
        </li>;
      })}
    </ul> : null}
  </section>;

  if (!compact) return manager;

  return <>
    <section className="source-documents-compact" aria-label="Supplier files">
      <div>
        <strong>Supplier files</strong>
        <span>{loading
          ? "Loading…"
          : documents.length
            ? workflowSummary
            : "No supporting documents attached"}</span>
      </div>
      <button className="text-button" type="button" onClick={() => setManagerOpen(true)}>Manage files</button>
    </section>
    {managerOpen ? <div className="workspace-drawer-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) setManagerOpen(false);
    }}>
      <aside className="workspace-drawer workspace-drawer-wide" role="dialog" aria-modal="true" aria-label="Manage supplier files">
        <div className="workspace-drawer-heading">
          <div><p className="eyebrow">Documents</p><h2>Manage supplier files</h2></div>
          <button className="icon-button" type="button" aria-label="Close document manager" onClick={() => setManagerOpen(false)}><X size={18} /></button>
        </div>
        {manager}
      </aside>
    </div> : null}
  </>;
});

SupplierDocumentsPanel.displayName = "SupplierDocumentsPanel";
