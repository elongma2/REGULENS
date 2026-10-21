import { ExternalLink, Maximize2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { sourceEvidenceUrl } from "../api/screening";
import { acceptedSnapshotLabel } from "../lib/presentation";
import type { RuleEvaluation, SourceSnapshot } from "../types/screening";

export function SourceEvidence({ evaluation, source }: { evaluation: RuleEvaluation; source?: SourceSnapshot }) {
  const [cropFailed, setCropFailed] = useState(false);
  const [pageFailed, setPageFailed] = useState(false);
  const [showPage, setShowPage] = useState(false);
  const evidence = evaluation.evidence;

  useEffect(() => {
    if (!showPage) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setShowPage(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [showPage]);

  return (
    <section className="source-evidence-panel" aria-label="Official source evidence">
      <p className="eyebrow">Official source evidence</p>
      <p className="text-sm font-semibold text-slate-900">{acceptedSnapshotLabel(evaluation)}</p>
      <p className="mt-1 text-xs text-slate-500">
        {evidence.regulatory_section} · Ref {evidence.reference_number} · Page {evidence.source_pages.join(", ")}
      </p>
      {cropFailed ? (
        <div className="source-image-error" role="status">The accepted source row could not be rendered. The exact source wording remains available above.</div>
      ) : (
        <div className="source-image-scroll">
          <img
            className="source-crop-image"
            src={sourceEvidenceUrl(evidence.raw_record_id)}
            alt={`Accepted PDF row for ${evidence.regulatory_section}, reference ${evidence.reference_number}`}
            loading="lazy"
            onError={() => setCropFailed(true)}
          />
        </div>
      )}
      <div className="mt-3 text-xs leading-5 text-slate-500">
        <div>{source?.title ?? evidence.source_document}</div>
        <div>{evidence.source_version ?? evidence.document_revision ?? "Version recorded in accepted baseline"}</div>
      </div>
      <div className="source-actions">
        <button type="button" className="secondary-button" onClick={() => { setPageFailed(false); setShowPage(true); }}>
          <Maximize2 size={14} /> View full accepted {evidence.source_pages.length > 1 ? "pages" : "page"}
        </button>
        <a className="source-link mt-0" href={evidence.source_url} target="_blank" rel="noreferrer">
          Open official source <ExternalLink size={14} />
        </a>
      </div>

      {showPage && createPortal(
        <div className="page-modal" role="dialog" aria-modal="true" aria-label="Accepted source page">
          <button className="page-modal-backdrop" onClick={() => setShowPage(false)} aria-label="Close full source page" />
          <div className="page-modal-panel">
            <div className="page-modal-header">
              <div>
                <p className="text-sm font-semibold text-slate-900">Accepted source {evidence.source_pages.length > 1 ? "pages" : "page"}</p>
                <p className="text-xs text-slate-500">{acceptedSnapshotLabel(evaluation)} · Page {evidence.source_pages.join(", ")}</p>
                <a className="source-link" href={sourceEvidenceUrl(evidence.raw_record_id, "page")} target="_blank" rel="noreferrer">Open full-size page image <ExternalLink size={14} /></a>
              </div>
              <button autoFocus className="icon-button" onClick={() => setShowPage(false)} aria-label="Close full source page"><X size={18} /></button>
            </div>
            <div className="page-modal-body">
              {pageFailed ? (
                <div className="source-image-error">The accepted source page could not be rendered.</div>
              ) : (
                <img
                  src={sourceEvidenceUrl(evidence.raw_record_id, "page")}
                  alt={`Accepted PDF page ${evidence.source_pages.join(", ")}`}
                  onError={() => setPageFailed(true)}
                />
              )}
            </div>
          </div>
        </div>, document.body
      )}
    </section>
  );
}
