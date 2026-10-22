import { AlertTriangle, Trash2, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

export function TypedDeleteDialog({ open, title, description, actionLabel, busy, error, onCancel, onConfirm }: {
  open: boolean; title: string; description: string; actionLabel: string; busy: boolean; error: string | null;
  onCancel: () => void; onConfirm: () => void;
}) {
  const [confirmation, setConfirmation] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const busyRef = useRef(busy);
  const cancelRef = useRef(onCancel);
  const headingId = useId(); const descriptionId = useId();
  busyRef.current = busy; cancelRef.current = onCancel;
  useEffect(() => {
    if (!open) { setConfirmation(""); return; }
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    window.setTimeout(() => inputRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) { event.preventDefault(); cancelRef.current(); return; }
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled])") ?? []);
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); window.setTimeout(() => previous?.focus(), 0); };
  }, [open]);
  if (!open) return null;
  return <div className="confirmation-dialog-backdrop"><div ref={dialogRef} className="confirmation-dialog typed-delete-dialog" role="dialog" aria-modal="true" aria-labelledby={headingId} aria-describedby={descriptionId}>
    <header><span className="confirmation-dialog-icon" aria-hidden="true"><AlertTriangle size={19} /></span><div><h2 id={headingId}>{title}</h2><p id={descriptionId}>{description}</p></div><button className="icon-button" type="button" aria-label="Close delete confirmation" disabled={busy} onClick={onCancel}><X size={17} /></button></header>
    <div className="typed-delete-body"><label htmlFor={`${headingId}-confirmation`}>Type <strong>DELETE</strong> to confirm</label><input ref={inputRef} id={`${headingId}-confirmation`} autoComplete="off" spellCheck={false} value={confirmation} disabled={busy} onChange={(event) => setConfirmation(event.target.value)} /></div>
    {error && <div className="dialog-error" role="alert">{error}</div>}
    <footer><button className="secondary-button" type="button" disabled={busy} onClick={onCancel}>Cancel</button><button className="danger-button" type="button" disabled={busy || confirmation !== "DELETE"} onClick={onConfirm}><Trash2 size={14} /> {busy ? "Deleting…" : error ? "Retry deletion" : actionLabel}</button></footer>
  </div></div>;
}
