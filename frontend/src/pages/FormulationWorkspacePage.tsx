import { Link, useParams } from "react-router-dom";
import { AgentPage } from "./AgentPage";

export function FormulationWorkspacePage() {
  const { caseId = "", versionId = "" } = useParams();
  return <><div className="case-workspace-breadcrumb"><Link to={`/cases/${caseId}`}>← Case Overview</Link></div><AgentPage caseId={caseId} versionId={versionId} /></>;
}
