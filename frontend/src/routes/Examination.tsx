/*
  The examination view — the core screen, and the one the whole product is for.

  A split bench: the evidence sticky on the left, the findings ledger scrolling on the
  right. Hovering a ledger row pulses its box on the image; hovering a box highlights
  its row. The link runs both ways because an officer works in both directions — from
  a suspicion to the evidence, and from something odd on the pack to the rule it
  breaks.
*/

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Finding, ScanResult } from "../api/types";
import { DeleteScanDialog } from "../components/DeleteScanDialog";
import { EvidencePlate } from "../components/EvidencePlate";
import { ImageStrip } from "../components/ImageStrip";
import { Measure, measureFromDetail } from "../components/Measure";
import { OverrideDialog } from "../components/OverrideDialog";
import { RetentionPanel } from "../components/RetentionPanel";
import { ScoreScale } from "../components/ScoreScale";
import { StatusMark, VerdictMark } from "../components/StatusMark";
import "./Examination.css";

const ORDER: Record<string, number> = { FAIL: 0, NEEDS_REVIEW: 1, PASS: 2, NA: 3 };

export function Examination() {
  const { scanId = "" } = useParams();
  const navigate = useNavigate();
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [deleting, setDeleting] = useState(false);
  // A load failure replaces the page; an action failure is shown in place. Blanking
  // the examination because a photograph could not be removed would lose the officer's
  // position in a ledger they may have been reading for several minutes.
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [overriding, setOverriding] = useState<Finding | null>(null);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  // Set while an image edit is re-running the pipeline server-side.
  const [reprocessing, setReprocessing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ledger = useRef<HTMLOListElement>(null);

  useEffect(() => {
    let live = true;
    api
      .scan(scanId)
      .then((result) => live && setScan(result))
      .catch((e: unknown) =>
        live ? setError(e instanceof ApiError ? e.message : String(e)) : undefined,
      );
    return () => {
      live = false;
    };
  }, [scanId]);

  const findings = useMemo(() => {
    if (!scan) return [];
    return [...scan.findings].sort(
      (a, b) => (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9) || a.rule_id.localeCompare(b.rule_id),
    );
  }, [scan]);

  // Boxes come only from findings that actually cited a region. Nothing is inferred.
  const boxes = useMemo(
    () =>
      findings
        .filter((f) => f.evidence.located && f.evidence.bbox && f.status !== "NA")
        .map((f) => ({
          ruleId: f.rule_id,
          bbox: f.evidence.bbox!,
          status: f.status,
          imageId: f.evidence.image_id!,
        })),
    [findings],
  );

  const focusRow = useCallback((ruleId: string) => {
    setActive(ruleId);
    ledger.current
      ?.querySelector(`[data-rule="${ruleId}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);

  const runReport = async () => {
    setBusy(true);
    try {
      await api.generateReport(scanId);
      setReportUrl(await api.authedBlob(api.reportPdfUrl(scanId)));
    } catch (e: unknown) {
      setActionError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="notice notice--problem">
        <p>{error}</p>
        <Link to="/scans">Back to the repository</Link>
      </div>
    );
  }

  if (!scan) {
    return <p className="eyebrow">Opening scan</p>;
  }

  const { assessment, calibration } = scan;

  return (
    <div className="exam">
      <header className="exam__head">
        <div>
          <p className="eyebrow">
            <Link to="/scans" className="exam__back">
              Repository
            </Link>{" "}
            / Scan
          </p>
          <h1 className="exam__title">{scan.product_name ?? "Unnamed product"}</h1>
          <p className="exam__provenance data">
            {scan.scan_id.slice(0, 12)} · {scan.scan_date} · ruleset {scan.ruleset_version}
          </p>
        </div>

        <div className="exam__actions">
          <button
            type="button"
            className="button button--primary"
            onClick={runReport}
            disabled={busy}
          >
            {busy ? "Preparing report" : "Prepare report"}
          </button>
          {reportUrl && (
            <a className="button" href={reportUrl} download={`compliance-${scanId.slice(0, 8)}.pdf`}>
              Save PDF
            </a>
          )}
          {!scan.deleted_at && (
            <button
              type="button"
              className="button exam__delete"
              onClick={() => setDeleting(true)}
            >
              Delete scan
            </button>
          )}
        </div>
      </header>

      {scan.deleted_at && (
        <p className="notice notice--problem">
          <strong>This scan has been deleted.</strong> It no longer appears in the
          repository; its record and evidence are kept for the audit trail.
          {scan.deleted_reason ? ` Reason given: “${scan.deleted_reason}”.` : ""}
        </p>
      )}

      <section className="exam__verdict" aria-label="Assessment">
        <div className="exam__verdict-mark">
          <VerdictMark verdict={assessment.verdict} />
          {assessment.overridden > 0 && (
            <p className="exam__after">
              after {assessment.overridden} officer decision
              {assessment.overridden === 1 ? "" : "s"} — the software found{" "}
              <strong>{assessment.automated_verdict.replace("_", " ").toLowerCase()}</strong>
            </p>
          )}
        </div>
        <ScoreScale
          score={assessment.score}
          decided={assessment.rules_decided}
          applicable={assessment.rules_applicable}
        />
      </section>

      {!calibration.calibrated && (
        <p className="notice notice--review">
          <strong>No millimetre measurement was possible.</strong> Nothing of known size
          was found in these photographs, so character heights could not be recovered and
          every Rule 8 finding is left for you. Re-photograph the pack with the scale
          card, an ID-1 card, or a ₹5 or ₹10 coin lying flat beside it.
        </p>
      )}

      {scan.notes.map((note) => (
        <p key={note} className="notice notice--review">
          {note}
        </p>
      ))}

      {actionError && (
        <p className="notice notice--problem" role="alert">
          {actionError}
        </p>
      )}

      <RetentionPanel scanId={scan.scan_id} retention={scan.retention} onScan={setScan} />

      {reprocessing && (
        <p className="exam__reprocessing" role="status">
          <span>
            {reprocessing}. The findings below are from the previous photographs until
            it finishes.
          </span>
        </p>
      )}

      <div className={`exam__bench ${reprocessing ? "is-stale" : ""}`}>
        <div className="exam__evidence">
          <EvidencePlate
            scanId={scan.scan_id}
            images={scan.images}
            boxes={boxes}
            active={active}
            onHover={setActive}
            onSelect={focusRow}
          />
          <ImageStrip
            scanId={scan.scan_id}
            images={scan.images}
            revision={scan.revision}
            busy={reprocessing !== null}
            onBusy={setReprocessing}
            onScan={(updated) => {
              setScan(updated);
              // The report on file was rendered from the previous image set.
              setReportUrl(null);
            }}
            onError={setActionError}
          />
        </div>

        <div className="exam__ledger-wrap">
          <div className="graduated" aria-hidden="true" />
          <h2 className="exam__ledger-title">
            Findings
            <span className="exam__counts">
              <span className="exam__count exam__count--fail">{assessment.failed} failing</span>
              <span className="exam__count exam__count--review">
                {assessment.needs_review} to review
              </span>
            </span>
          </h2>

          <ol className="ledger" ref={ledger}>
            {findings.map((finding, index) => {
              const measure = measureFromDetail(finding.detail);
              const isActive = active === finding.rule_id;
              return (
                <li
                  key={finding.rule_id}
                  data-rule={finding.rule_id}
                  className={`ledger__row ledger__row--${finding.status} ${
                    isActive ? "is-active" : ""
                  }`}
                  /* A beat behind the annotation boxes (which start at 0 and run
                     ~55ms apart), so the eye is walked image → ledger. */
                  style={{ animationDelay: `${150 + Math.min(index, 12) * 28}ms` }}
                  onMouseEnter={() => setActive(finding.rule_id)}
                  onMouseLeave={() => setActive(null)}
                  onFocus={() => setActive(finding.rule_id)}
                  onBlur={() => setActive(null)}
                  tabIndex={0}
                >
                  <div className="ledger__head">
                    <StatusMark status={finding.status} />
                    <span className="ledger__rule data">{finding.rule_id}</span>
                  </div>

                  <h3 className="ledger__title">{finding.title}</h3>
                  <p className="ledger__cite data">
                    {finding.citation} · {finding.severity.toLowerCase()}
                  </p>
                  <p className="ledger__message">{finding.message}</p>

                  {measure && (
                    <Measure
                      measuredMm={measure.measuredMm}
                      requiredMm={measure.requiredMm}
                      citation={typeof finding.detail.table === "string" ? finding.detail.table : null}
                      panelAreaCm2={measure.panelAreaCm2}
                    />
                  )}

                  {finding.evidence.located && finding.evidence.raw_text && (
                    <p className="ledger__read">
                      <span className="eyebrow">read as</span>
                      <span className="ledger__quote data">{finding.evidence.raw_text}</span>
                      <span className="ledger__conf data">
                        confidence {finding.evidence.confidence?.toFixed(2)}
                      </span>
                    </p>
                  )}

                  {!finding.evidence.located && finding.status === "FAIL" && finding.evidence.note && (
                    <p className="ledger__absent">{finding.evidence.note}</p>
                  )}

                  {finding.remediation && (
                    <p className="ledger__fix">
                      <span className="eyebrow">to correct</span> {finding.remediation}
                    </p>
                  )}

                  {finding.override && (
                    <div className="ledger__override">
                      <p className="eyebrow">Officer decision</p>
                      <p>
                        Recorded as <strong>{finding.override.original_status}</strong> by the
                        software; set to <strong>{finding.status}</strong> by an officer.
                      </p>
                      <p className="ledger__reason">“{finding.override.reason}”</p>
                    </div>
                  )}

                  {finding.status !== "NA" && (
                    <button
                      type="button"
                      className="ledger__overrule"
                      onClick={() => setOverriding(finding)}
                    >
                      {finding.override ? "Revise decision" : "Record a decision"}
                    </button>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      </div>

      {overriding && (
        <OverrideDialog
          finding={overriding}
          onClose={() => setOverriding(null)}
          onSubmit={async (status, reason) => {
            const updated = await api.overrideFinding(scanId, overriding.rule_id, status, reason);
            setScan(updated);
            setOverriding(null);
          }}
        />
      )}

      {deleting && (
        <DeleteScanDialog
          productName={scan.product_name}
          caseOpen={scan.retention.case_open === true}
          onClose={() => setDeleting(false)}
          onConfirm={async (reason) => {
            await api.deleteScan(scanId, reason);
            setDeleting(false);
            navigate("/scans");
          }}
        />
      )}
    </div>
  );
}
