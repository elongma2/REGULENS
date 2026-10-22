import { Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deleteFormulationVersion } from "../api/cases";
import { TypedDeleteDialog } from "../components/TypedDeleteDialog";
import { AgentPage } from "./AgentPage";

export function FormulationWorkspacePage() {
  const { caseId = "", versionId = "" } = useParams();
  const navigate = useNavigate();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
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
      <AgentPage caseId={caseId} versionId={versionId} />
    </div>
    <TypedDeleteDialog open={dialogOpen} title="Delete this formulation version?" description="This permanently removes its uploaded file, interpretation, clarifications, screening runs, finding reviews, formulation and finding notes, and linked follow-ups. Case-level notes remain." actionLabel="Delete formulation" busy={deleting} error={deleteError} onCancel={() => { if (!deleting) { setDialogOpen(false); setDeleteError(null); } }} onConfirm={() => void remove()} />
  </>;
}
