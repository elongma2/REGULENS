import { AlertTriangle, Trash2, X } from "lucide-react";
import { useEffect, useRef } from "react";

export function CaseDeleteDialog({
  caseName,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  caseName: string | null;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const busyRef = useRef(busy);
  const cancelHandlerRef = useRef(onCancel);
  busyRef.current = busy;
  cancelHandlerRef.current = onCancel;

  useEffect(() => {
    if (!caseName) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    window.setTimeout(() => cancelRef.current?.focus(), 0);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        cancelHandlerRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input:not([disabled])") ?? []);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      window.setTimeout(() => previouslyFocused?.focus(), 0);
    };
  }, [caseName]);

  if (!caseName) return null;
  const headingId = "delete-case-heading";
  const descriptionId = "delete-case-description";
  return <div className="confirmation-dialog-backdrop">
    <div ref={dialogRef} className="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby={headingId} aria-describedby={descriptionId}>
      <header>
        <span className="confirmation-dialog-icon" aria-hidden="true"><AlertTriangle size={19} /></span>
        <div><h2 id={headingId}>Delete “{caseName}”?</h2><p id={descriptionId}>This permanently removes the case, formulation versions, screening runs, clarifications, reviewer records, notes, follow-ups, and uploaded files.</p></div>
        <button className="icon-button" type="button" aria-label="Close delete confirmation" disabled={busy} onClick={onCancel}><X size={17} /></button>
      </header>
      {error && <div className="dialog-error" role="alert">{error}</div>}
      <footer>
        <button ref={cancelRef} className="secondary-button" type="button" disabled={busy} onClick={onCancel}>Cancel</button>
        <button className="danger-button" type="button" disabled={busy} onClick={onConfirm}><Trash2 size={14} /> {busy ? "Deleting…" : error ? "Retry deletion" : "Delete case"}</button>
      </footer>
    </div>
  </div>;
}
