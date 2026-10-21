import { ExternalLink, Maximize2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { identitySourceEvidenceUrl } from "../api/screening";
import type { CatalogueIdentity } from "../types/screening";

interface IdentityFragment {
  entry: number;
  page: number;
  rawRecordId: string;
}

function fragments(identity: CatalogueIdentity): IdentityFragment[] {
  return identity.raw_record_ids.map((rawRecordId, index) => ({
    rawRecordId,
    entry: identity.source_entries[index] ?? identity.source_entries[0],
    page: identity.source_pages[index] ?? identity.source_pages[0],
  }));
}

export function IdentitySourceEvidence({ identity }: { identity: CatalogueIdentity }) {
  const records = fragments(identity);
  const [failedCrops, setFailedCrops] = useState<Set<string>>(() => new Set());
  const [activePage, setActivePage] = useState<IdentityFragment | null>(null);
  const [pageFailed, setPageFailed] = useState(false);

  useEffect(() => {
    if (!activePage) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setActivePage(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [activePage]);

  return (
    <section className="source-evidence-panel" aria-label="Accepted identity catalogue evidence">
      <p className="eyebrow">Accepted identity catalogue evidence</p>
      <p className="text-sm font-semibold text-slate-900">Accepted snapshot · {identity.source_version}</p>
      <p className="mt-1 text-xs text-slate-500">Identity reference only · {records.length} source {records.length === 1 ? "entry" : "entries"}</p>

      {records.map((record) => (
        <article className="mt-4" key={record.rawRecordId}>
          <p className="mb-2 text-xs font-medium text-slate-600">EU entry {record.entry} · Page {record.page}</p>
          {failedCrops.has(record.rawRecordId) ? (
            <div className="source-image-error" role="status">The accepted identity row could not be rendered. Its source provenance remains available.</div>
          ) : (
            <div className="source-image-scroll">
              <img
                className="source-crop-image"
                src={identitySourceEvidenceUrl(record.rawRecordId)}
                alt={`Accepted EU glossary row for entry ${record.entry}, ${identity.canonical_name}`}
                loading="lazy"
                onError={() => setFailedCrops((current) => new Set(current).add(record.rawRecordId))}
              />
            </div>
          )}
          <button
            type="button"
            className="secondary-button mt-3"
            onClick={() => { setPageFailed(false); setActivePage(record); }}
          >
            <Maximize2 size={14} /> View full accepted page
          </button>
        </article>
      ))}

      <p className="mt-4 text-xs leading-5 text-slate-600">
        This accepted EU glossary entry supports the ingredient name only. Regulatory findings are produced separately by the Singapore screening engine.
      </p>
      <a className="source-link" href={identity.source_url} target="_blank" rel="noreferrer">
        Open official identity source <ExternalLink size={14} />
      </a>

      {activePage && createPortal(
        <div className="page-modal" role="dialog" aria-modal="true" aria-label="Accepted identity source page">
          <button className="page-modal-backdrop" onClick={() => setActivePage(null)} aria-label="Close full identity source page" />
          <div className="page-modal-panel">
            <div className="page-modal-header">
              <div>
                <p className="text-sm font-semibold text-slate-900">Accepted EU glossary page</p>
                <p className="text-xs text-slate-500">Entry {activePage.entry} · Page {activePage.page} · {identity.source_version}</p>
                <a className="source-link" href={identitySourceEvidenceUrl(activePage.rawRecordId, "page")} target="_blank" rel="noreferrer">Open full-size page image <ExternalLink size={14} /></a>
              </div>
              <button autoFocus className="icon-button" onClick={() => setActivePage(null)} aria-label="Close full identity source page"><X size={18} /></button>
            </div>
            <div className="page-modal-body">
              {pageFailed ? (
                <div className="source-image-error">The accepted identity source page could not be rendered.</div>
              ) : (
                <img
                  src={identitySourceEvidenceUrl(activePage.rawRecordId, "page")}
                  alt={`Accepted EU glossary page ${activePage.page}`}
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
