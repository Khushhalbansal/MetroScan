/*
  Recording an officer's decision over an automated finding.

  The dialog states plainly what the software found and what is about to be recorded
  instead, because the point of an override is that the two disagree and the record
  keeps both. The reason is mandatory and has a floor — "ok" recorded against a
  reversed violation is what a manufacturer's counsel gets to read out later.
*/

import { useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import type { Finding, FindingStatus } from "../api/types";
import { StatusMark } from "./StatusMark";
import "./OverrideDialog.css";

const MIN_REASON = 15;

// NA is absent on purpose: whether a rule applies is a question about the statute and
// any exemption, not an officer's discretion. The API refuses it too.
const CHOICES: FindingStatus[] = ["PASS", "FAIL", "NEEDS_REVIEW"];

interface Props {
  finding: Finding;
  onClose: () => void;
  onSubmit: (status: FindingStatus, reason: string) => Promise<void>;
}

export function OverrideDialog({ finding, onClose, onSubmit }: Props) {
  const machineSaid = finding.override?.original_status ?? finding.status;
  const [status, setStatus] = useState<FindingStatus>(
    CHOICES.find((c) => c !== finding.status) ?? "NEEDS_REVIEW",
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const first = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const short = reason.trim().length < MIN_REASON;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (short || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(status, reason.trim());
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="override-title"
        ref={dialog}
      >
        <p className="eyebrow">Officer decision</p>
        <h2 id="override-title" className="dialog__title">
          {finding.title}
        </h2>
        <p className="dialog__rule data">
          {finding.rule_id} · {finding.citation}
        </p>

        <p className="dialog__machine">
          The software recorded <StatusMark status={machineSaid} size="small" />. That
          stays on the record whatever you decide here.
        </p>

        <form onSubmit={submit}>
          <fieldset className="dialog__choices">
            <legend className="eyebrow">Record instead</legend>
            {CHOICES.map((choice, i) => (
              <button
                key={choice}
                ref={i === 0 ? first : undefined}
                type="button"
                className={`dialog__choice ${status === choice ? "is-chosen" : ""}`}
                aria-pressed={status === choice}
                disabled={choice === finding.status}
                onClick={() => setStatus(choice)}
              >
                <StatusMark status={choice} size="small" />
                {choice === finding.status && (
                  <span className="dialog__already">already recorded</span>
                )}
              </button>
            ))}
          </fieldset>

          <label className="dialog__label" htmlFor="override-reason">
            <span className="eyebrow">Why</span>
            <span className="dialog__help">
              What did you see on the package that the scan could not? This is kept with
              the finding and appears on the report.
            </span>
          </label>
          <textarea
            id="override-reason"
            className="dialog__reason"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Tax rider is printed on the reverse panel, verified on the pack in hand."
          />
          <p className={`dialog__count data ${short ? "is-short" : ""}`}>
            {reason.trim().length} / {MIN_REASON} characters minimum
          </p>

          {error && <p className="dialog__error">{error}</p>}

          <div className="dialog__actions">
            <button type="button" className="button" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="button button--primary" disabled={short || busy}>
              {busy ? "Recording" : "Record decision"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
