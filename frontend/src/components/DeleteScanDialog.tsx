/*
  Confirming a manual scan deletion.

  Delete here is a soft delete: the scan, its photographs and its findings stay in
  the database and the removal is written to the audit trail. What changes is that
  the scan leaves the working repository. The dialog says that plainly, because
  "delete" usually means "gone" and here it does not.

  A case being open does not block this. The scheduled auto-deletion job defers to
  the retention answer; a person with authority deleting a scan by hand is the
  deliberate exception to it, so the dialog notes when that is what is happening.
*/

import { useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import "./DeleteScanDialog.css";

const REASON_MAX = 64;

interface Props {
  productName: string | null;
  /** True when the officer has recorded that a case is open on this scan. */
  caseOpen: boolean;
  onClose: () => void;
  onConfirm: (reason: string | undefined) => Promise<void>;
}

export function DeleteScanDialog({ productName, caseOpen, onClose, onConfirm }: Props) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cancel = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim() || undefined);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div
      className="scrim"
      role="presentation"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <p className="eyebrow">Delete scan</p>
        <h2 id="delete-title" className="dialog__title">
          Delete the scan of {productName ?? "this product"}?
        </h2>

        <p className="delete__body">
          The scan leaves the repository listing. Its photographs, findings and history
          stay in the database, and the deletion is recorded in the audit trail with
          your name against it — nothing is destroyed.
        </p>

        {caseOpen && (
          <p className="delete__caseopen">
            A case is marked open on this scan. A manual delete overrides that; the
            scheduled auto-deletion job never would.
          </p>
        )}

        <form onSubmit={submit}>
          <label className="dialog__label" htmlFor="delete-reason">
            <span className="eyebrow">Reason (optional)</span>
          </label>
          <input
            id="delete-reason"
            className="delete__reason"
            type="text"
            maxLength={REASON_MAX}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Duplicate capture"
          />

          {error && <p className="dialog__error">{error}</p>}

          <div className="dialog__actions">
            <button type="button" className="button" ref={cancel} onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="button button--danger"
              disabled={busy}
            >
              {busy ? "Deleting" : "Delete scan"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
