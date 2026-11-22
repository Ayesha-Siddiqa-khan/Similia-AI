"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** A modal yes/no question. Nothing happens until the confirm button is pressed; Cancel and Esc do nothing. */
export function ConfirmDialog({ id, title, children, confirmLabel, busyLabel, busy, danger = false, onCancel, onConfirm }: { id: string; title: string; children: ReactNode; confirmLabel: string; busyLabel: string; busy: boolean; danger?: boolean; onCancel: () => void; onConfirm: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) {
      if (typeof element.showModal === "function") element.showModal();
      else element.setAttribute("open", "");
    }
    return () => { if (element?.open && typeof element.close === "function") element.close(); };
  }, []);
  return (
    <dialog ref={dialog} className="modal" aria-modal="true" aria-labelledby={`${id}-title`} onCancel={onCancel}>
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
      <div className="button-row">
        <button autoFocus type="button" className="button secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="button" className={`button ${danger ? "danger" : "primary"}`} onClick={onConfirm} disabled={busy}>{busy ? busyLabel : confirmLabel}</button>
      </div>
    </dialog>
  );
}
