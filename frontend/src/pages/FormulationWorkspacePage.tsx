import { Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deleteFormulationVersion } from "../api/cases";
import { SupplierDocumentsPanel, type SupplierDocumentsPanelHandle, type SupplierDocumentWorkflowStatus } from "../components/SupplierDocumentsPanel";
import { TradeMaterialAssemblyPanel, type TradeMaterialAssemblyPanelHandle } from "../components/TradeMaterialAssemblyPanel";
import type { AssemblyIssue, FormulationDocument } from "../types/cases";
import { TypedDeleteDialog } from "../components/TypedDeleteDialog";
import { AgentPage } from "./AgentPage";

export function FormulationWorkspacePage() {
  const { caseId = "", versionId = "" } = useParams();
  const navigate = useNavigate();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [sourceDocuments, setSourceDocuments] = useState<FormulationDocument[]>([]);
  const [handledMaterialRowIds, setHandledMaterialRowIds] = useState<string[]>([]);
  const [assemblyRevision, setAssemblyRevision] = useState<number | null>(null);
  const [agentFocusRequest, setAgentFocusRequest] = useState<{ rowId: string; requestId: number } | null>(null);
  const [supplierWorkflow, setSupplierWorkflow] = useState<SupplierDocumentWorkflowStatus>({
    blocking: false,
    unresolvedRevisionGroups: 0,
    reason: null,
  });
  const supplierDocuments = useRef<SupplierDocumentsPanelHandle>(null);
  const materialAssembly = useRef<TradeMaterialAssemblyPanelHandle>(null);
  const openIssueTarget = (issue: AssemblyIssue) => {
    const rowId = issue.constituent_ids
      .find((id) => id.startsWith("agent:"))
      ?.slice("agent:".length);
    if (rowId) {
      setAgentFocusRequest({ rowId, requestId: Date.now() });
      return;
    }
    if (issue.document_ids[0]) supplierDocuments.current?.openManager(issue.document_ids[0]);
  };
  const remove = async () => {
    setDeleting(true); setDeleteError(null);
    try {
      await deleteFormulationVersion(versionId);
      navigate(`/cases/${caseId}`, { replace: true, state: { deletedFormulation: true } });
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : "The formulation version could not be deleted.");
      setDeleting(false);
    }
  };
  return <>
    <div aria-hidden={dialogOpen}>
      <div className="case-workspace-breadcrumb"><Link to={`/cases/${caseId}`}>← Case Overview</Link><button className="danger-text-button" type="button" onClick={() => { setDialogOpen(true); setDeleteError(null); }}><Trash2 size={14} /> Delete formulation</button></div>
      <SupplierDocumentsPanel ref={supplierDocuments} compact versionId={versionId} onDocumentsChanged={setSourceDocuments} onWorkflowStatusChange={setSupplierWorkflow} />
      <TradeMaterialAssemblyPanel ref={materialAssembly} compact versionId={versionId} documents={sourceDocuments} onHandledMaterialRowIdsChange={setHandledMaterialRowIds} onAssemblyRevisionChange={setAssemblyRevision} onIssueAction={openIssueTarget} />
      <AgentPage compact caseId={caseId} versionId={versionId} handledMaterialRowIds={handledMaterialRowIds} assemblyRevision={assemblyRevision} focusRowRequest={agentFocusRequest} screeningBlockedReason={supplierWorkflow.reason} onResolveScreeningBlock={() => supplierDocuments.current?.openManager()} beforeRunScreening={() => materialAssembly.current?.savePendingChanges() ?? Promise.resolve()} onIdentitySuggestionDecision={(targetId, decision) => {
        const handler = materialAssembly.current;
        if (!handler) return Promise.reject(new Error("Material calculations are unavailable."));
        return handler.decideIdentitySuggestion(targetId, decision).then(() => undefined);
      }} />
    </div>
    <TypedDeleteDialog open={dialogOpen} title="Delete this formulation version?" description="This permanently removes its uploaded file, interpretation, clarifications, screening runs, finding reviews, formulation and finding notes, and linked follow-ups. Case-level notes remain." actionLabel="Delete formulation" busy={deleting} error={deleteError} onCancel={() => { if (!deleting) { setDialogOpen(false); setDeleteError(null); } }} onConfirm={() => void remove()} />
  </>;
}
