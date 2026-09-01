/*
  The repository: every scan on file.

  A list view is exactly where a lone score gets skimmed as a grade, so no row shows a
  number without the coverage that qualifies it, and the verdict leads.
*/

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ScanPage, Verdict } from "../api/types";
import { VerdictMark } from "../components/StatusMark";
import "./Repository.css";

const FILTERS: Array<{ label: string; value: Verdict | "" }> = [
  { label: "All scans", value: "" },
  { label: "Non-compliant", value: "NON_COMPLIANT" },
  { label: "Inconclusive", value: "INCONCLUSIVE" },
  { label: "Compliant", value: "COMPLIANT" },
];

export function Repository() {
  const [page, setPage] = useState<ScanPage | null>(null);
  const [verdict, setVerdict] = useState<Verdict | "">("");
  const [ruleId, setRuleId] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    api
      .scans({ verdict: verdict || undefined, rule_id: ruleId || undefined, limit: 50 })
      .then((result) => live && setPage(result))
      .catch((e: unknown) =>
        live ? setError(e instanceof ApiError ? e.message : String(e)) : undefined,
      );
    return () => {
      live = false;
    };
  }, [verdict, ruleId]);

  return (
    <div className="repo">
      <header className="repo__head">
        <div>
          <p className="eyebrow">Repository</p>
          <h1 className="repo__title">Scans on file</h1>
        </div>
        <Link to="/scans/new" className="button button--primary">
          Run compliance check
        </Link>
      </header>

      <div className="graduated" aria-hidden="true" />

      <div className="repo__filters">
        <div className="repo__chips" role="group" aria-label="Filter by verdict">
          {FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              className={`repo__chip ${verdict === filter.value ? "is-on" : ""}`}
              aria-pressed={verdict === filter.value}
              onClick={() => setVerdict(filter.value)}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <label className="repo__rule-filter">
          <span className="eyebrow">Failed rule</span>
          <input
            className="repo__input data"
            value={ruleId}
            placeholder="MRP_SINGLE_VALUE"
            onChange={(e) => setRuleId(e.target.value.toUpperCase())}
          />
        </label>
      </div>

      {error && <p className="notice notice--problem">{error}</p>}

      {page && page.scans.length === 0 && (
        <p className="repo__empty">
          {verdict || ruleId
            ? "No scan on file matches that filter."
            : "No scans yet. Upload label photographs to run the first compliance check."}
        </p>
      )}

      {page && page.scans.length > 0 && (
        <>
          <p className="repo__total eyebrow">
            {page.total} scan{page.total === 1 ? "" : "s"}
          </p>
          <ul className="repo__list">
            {page.scans.map((scan) => (
              <li key={scan.scan_id} className={`repo__row repo__row--${scan.verdict}`}>
                <Link to={`/scans/${scan.scan_id}`} className="repo__link">
                  <span className="repo__product">
                    {scan.product_name ?? "Unnamed product"}
                  </span>
                  <VerdictMark verdict={scan.verdict} />
                  <span className="repo__numbers">
                    {scan.score === null ? (
                      <span className="repo__unscored">not scored</span>
                    ) : (
                      <span className="data repo__score">{scan.score.toFixed(1)}</span>
                    )}
                    <span className="repo__coverage data">
                      {scan.rules_decided}/{scan.rules_applicable} decided
                    </span>
                  </span>
                  <span className="repo__tallies">
                    {scan.failed > 0 && (
                      <span className="repo__tally repo__tally--fail">{scan.failed} failing</span>
                    )}
                    {scan.needs_review > 0 && (
                      <span className="repo__tally repo__tally--review">
                        {scan.needs_review} to review
                      </span>
                    )}
                    {scan.eligible_for_deletion && (
                      <span className="repo__tally repo__tally--retain">
                        eligible for deletion
                      </span>
                    )}
                  </span>
                  <span className="repo__date data">{scan.scan_date}</span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
