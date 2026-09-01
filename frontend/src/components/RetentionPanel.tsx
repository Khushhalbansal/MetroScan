/*
  The retention decision.

  One explicit question governs whether a filed scan is ever auto-deleted: does the
  officer say a case is still open on it? Not the verdict, not the age — this answer.
  A compliant scan an officer marks "case open" is kept exactly like any other.

    case_open = true   kept indefinitely. Only a manual delete can remove it.
    case_open = false  auto-deletable once the retention window runs out, counted
                       from the moment this answer was given — not from the scan date.
    unanswered         kept. Silence is never read as consent to delete.

  Choosing "no" starts a deletion clock, so it is confirmed with the date stated.
  Choosing "yes" only ever retains, so it applies at once. Every change is
  audit-logged server-side with the previous answer.
*/

import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { Retention, ScanResult } from "../api/types";
import "./RetentionPanel.css";

interface Props {
  scanId: string;
  retention: Retention;
  onScan: (scan: ScanResult) => void;
}

type Tone = "open" | "eligible" | "closed" | "undecided";

function toneOf(r: Retention): Tone {
  if (r.case_open === true) return "open";
  if (r.case_open === null) return "undecided";
  return r.eligible_for_deletion ? "eligible" : "closed";
}

export function RetentionPanel({ scanId, retention, onScan }: Props) {
  const [confirmingClose, setConfirmingClose] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const decide = async (caseOpen: boolean) => {
    setBusy(true);
    setError(null);
    try {
      onScan(await api.setRetention(scanId, caseOpen));
      setConfirmingClose(false);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const tone = toneOf(retention);
  const decidedOn = retention.decided_at?.slice(0, 10) ?? null;

  return (
    <section className={`retention retention--${tone}`} aria-label="Retention">
      <p className="eyebrow">Retention</p>
      <p className="retention__summary">{retention.summary}</p>

      {decidedOn && (
        <p className="retention__detail">
          Answered <span className="data">{decidedOn}</span>
        </p>
      )}

      {confirmingClose ? (
        <div className="retention__confirm">
          <p className="retention__confirm-text">
            Record that no case is open. This scan then becomes eligible for automatic
            deletion once the retention window passes from today. You can reopen it
            before then to stop that.
          </p>
          <div className="retention__actions">
            <button
              type="button"
              className="button button--danger"
              disabled={busy}
              onClick={() => void decide(false)}
            >
              No case is open
            </button>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => setConfirmingClose(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="retention__ask">
          <p className="retention__question">Is a case still open on this scan?</p>
          <div className="retention__actions">
            <button
              type="button"
              className="button button--primary"
              disabled={busy || retention.case_open === true}
              onClick={() => void decide(true)}
            >
              Yes — keep it
            </button>
            <button
              type="button"
              className="button"
              disabled={busy || retention.case_open === false}
              onClick={() => setConfirmingClose(true)}
            >
              No — case closed
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="retention__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
