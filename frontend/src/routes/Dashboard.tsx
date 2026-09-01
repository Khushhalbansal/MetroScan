/*
  The enforcement overview.

  Built from the same instrument the rest of the product is built from: linear
  graduated readings, brass limit lines, no donuts and no gauges. A pie chart of
  compliance would be the template answer and would have nowhere to put the thing that
  matters most here — the scans that concluded nothing.

  Those are kept visible everywhere. A compliance rate computed over concluded scans
  only is honest; the same number presented without saying how many scans were left
  out is not, so the two always travel together.
*/

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { Dashboard as DashboardData } from "../api/types";
import { useInView } from "../lib/motion";
import "./Dashboard.css";

const WINDOWS = [
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
  { label: "One year", days: 365 },
];

/** A count, as an instrument reading rather than a card with a big number. */
function Reading({
  label,
  value,
  note,
  tone = "ink",
}: {
  label: string;
  value: string;
  note?: string;
  tone?: "ink" | "oxide" | "brass" | "patina";
}) {
  return (
    <div className="reading">
      <p className="eyebrow reading__label">{label}</p>
      <p className={`reading__value data reading__value--${tone}`}>{value}</p>
      {note && <p className="reading__note">{note}</p>}
    </div>
  );
}

/** A proportion drawn as a graduated bar with the three outcomes kept distinct. */
function VerdictBar({
  compliant,
  nonCompliant,
  inconclusive,
}: {
  compliant: number;
  nonCompliant: number;
  inconclusive: number;
}) {
  const total = compliant + nonCompliant + inconclusive;
  if (total === 0) return null;
  const pct = (n: number) => (100 * n) / total;

  return (
    <div className="bar" role="img" aria-label={`${compliant} compliant, ${nonCompliant} non-compliant, ${inconclusive} inconclusive`}>
      <div className="bar__track">
        {compliant > 0 && (
          <span className="bar__part bar__part--compliant" style={{ width: `${pct(compliant)}%` }} />
        )}
        {nonCompliant > 0 && (
          <span className="bar__part bar__part--fail" style={{ width: `${pct(nonCompliant)}%` }} />
        )}
        {inconclusive > 0 && (
          <span
            className="bar__part bar__part--inconclusive"
            style={{ width: `${pct(inconclusive)}%` }}
          />
        )}
      </div>
    </div>
  );
}

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [days, setDays] = useState(90);
  const [error, setError] = useState<string | null>(null);
  // The graduated bars and the day chart draw themselves from empty on first view
  // (design-direction.md v2: "Data draws itself once"). Reduced motion → present.
  const [drawRef, drawn] = useInView<HTMLDivElement>();

  useEffect(() => {
    let live = true;
    setError(null);
    api
      .dashboard(days)
      .then((result) => live && setData(result))
      .catch((e: unknown) =>
        live ? setError(e instanceof ApiError ? e.message : String(e)) : undefined,
      );
    return () => {
      live = false;
    };
  }, [days]);

  if (error) return <p className="notice notice--problem">{error}</p>;
  if (!data) return <p className="eyebrow">Reading the bench</p>;

  const { totals, calibration } = data;
  const maxViolation = Math.max(1, ...data.top_violations.map((v) => v.count));
  const maxDay = Math.max(1, ...data.daily.map((d) => d.scans));

  return (
    <div className={`dash ${drawn ? "is-drawn" : ""}`} ref={drawRef}>
      <header className="dash__head">
        <div>
          <p className="eyebrow">Enforcement</p>
          <h1 className="dash__title">Overview</h1>
          <p className="dash__window data">
            {data.window.since} to {data.window.until}
          </p>
        </div>
        <div className="dash__windows" role="group" aria-label="Period">
          {WINDOWS.map((w) => (
            <button
              key={w.days}
              type="button"
              className={`dash__window-chip ${days === w.days ? "is-on" : ""}`}
              aria-pressed={days === w.days}
              onClick={() => setDays(w.days)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </header>

      <div className="graduated" aria-hidden="true" />

      {totals.scans === 0 ? (
        <p className="dash__empty">
          No scans in this period. Run a compliance check and the enforcement picture
          builds from there.{" "}
          <Link to="/scans/new">Run compliance check</Link>
        </p>
      ) : (
        <>
          <section className="dash__readings" aria-label="Headline counts">
            <Reading label="Scans filed" value={String(totals.scans)} />
            <Reading
              label="Compliance rate"
              tone={totals.compliance_rate === null ? "brass" : "ink"}
              value={
                totals.compliance_rate === null
                  ? "no reading"
                  : `${totals.compliance_rate.toFixed(1)}%`
              }
              note={
                totals.compliance_rate === null
                  ? "No scan in this period reached a conclusion."
                  : `over ${totals.concluded} concluded scan${totals.concluded === 1 ? "" : "s"}`
              }
            />
            <Reading
              label="Violations standing"
              tone="oxide"
              value={String(totals.non_compliant)}
              note="packages with at least one failing rule"
            />
            <Reading
              label="Awaiting an officer"
              tone="brass"
              value={String(totals.open_reviews)}
              note={`across ${totals.inconclusive} inconclusive scan${
                totals.inconclusive === 1 ? "" : "s"
              }`}
            />
          </section>

          <section className="dash__panel">
            <h2 className="dash__panel-title">Outcomes</h2>
            <VerdictBar
              compliant={totals.compliant}
              nonCompliant={totals.non_compliant}
              inconclusive={totals.inconclusive}
            />
            <ul className="legend">
              <li className="legend__item">
                <span className="legend__swatch legend__swatch--compliant" />
                <span className="data">{totals.compliant}</span> compliant
              </li>
              <li className="legend__item">
                <span className="legend__swatch legend__swatch--fail" />
                <span className="data">{totals.non_compliant}</span> non-compliant
              </li>
              <li className="legend__item">
                <span className="legend__swatch legend__swatch--inconclusive" />
                <span className="data">{totals.inconclusive}</span> inconclusive —
                not counted in the rate
              </li>
            </ul>
          </section>

          {/* The most actionable number here, and the reason it gets its own panel:
              the fix is not software, it is a card in the frame. */}
          <section
            className={`dash__panel ${
              calibration.uncalibrated > 0 ? "dash__panel--attention" : ""
            }`}
          >
            <h2 className="dash__panel-title">Scale references in frame</h2>
            <p className="dash__lede">
              {calibration.uncalibrated === 0 ? (
                <>Every scan in this period carried a scale reference.</>
              ) : (
                <>
                  <strong>
                    {calibration.uncalibrated} of {calibration.scans} scans
                  </strong>{" "}
                  arrived with nothing of known size in the frame, so Rule 8 could not
                  be checked on them at all. Ask inspectors to lay the scale card beside
                  the pack.
                </>
              )}
            </p>
            {calibration.calibrated_rate !== null && (
              <div className="bar">
                <div className="bar__track">
                  <span
                    className="bar__part bar__part--compliant"
                    style={{ width: `${calibration.calibrated_rate}%` }}
                  />
                </div>
                <p className="bar__caption data">
                  {calibration.calibrated_rate.toFixed(1)}% measurable
                </p>
              </div>
            )}
          </section>

          <section className="dash__panel">
            <h2 className="dash__panel-title">Rules most often broken</h2>
            {data.top_violations.length === 0 ? (
              <p className="dash__lede">No rule failed in this period.</p>
            ) : (
              <ol className="violations">
                {data.top_violations.map((violation) => (
                  <li key={violation.rule_id} className="violations__row">
                    <Link
                      to={`/scans?rule_id=${violation.rule_id}`}
                      className="violations__link"
                    >
                      <span className="violations__names">
                        <span className="violations__title">{violation.title}</span>
                        <span className="violations__meta data">
                          {violation.rule_id} · {violation.citation} ·{" "}
                          {violation.severity.toLowerCase()}
                        </span>
                      </span>
                      <span className="violations__bar" aria-hidden="true">
                        <span
                          className="violations__fill"
                          style={{ width: `${(100 * violation.count) / maxViolation}%` }}
                        />
                      </span>
                      <span className="violations__count data">{violation.count}</span>
                    </Link>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <div className="dash__two">
            <section className="dash__panel">
              <h2 className="dash__panel-title">By category</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Category</th>
                    <th className="table__num">Scans</th>
                    <th className="table__num">Rate</th>
                    <th>Outcomes</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_category.map((row) => (
                    <tr key={row.category}>
                      <td>{row.category}</td>
                      <td className="table__num data">{row.scans}</td>
                      <td className="table__num data">
                        {row.compliance_rate === null ? (
                          <span className="table__none">none</span>
                        ) : (
                          `${row.compliance_rate.toFixed(0)}%`
                        )}
                      </td>
                      <td>
                        <VerdictBar
                          compliant={row.compliant}
                          nonCompliant={row.non_compliant}
                          inconclusive={row.inconclusive}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="dash__panel">
              <h2 className="dash__panel-title">Scans per day</h2>
              {data.daily.length === 0 ? (
                <p className="dash__lede">No scans in this period.</p>
              ) : (
                <div className="trend">
                  {data.daily.map((day) => (
                    <div key={day.date} className="trend__day" title={`${day.date}: ${day.scans}`}>
                      <div className="trend__stack" style={{ height: `${(100 * day.scans) / maxDay}%` }}>
                        {day.non_compliant > 0 && (
                          <span
                            className="trend__part trend__part--fail"
                            style={{ flexGrow: day.non_compliant }}
                          />
                        )}
                        {day.inconclusive > 0 && (
                          <span
                            className="trend__part trend__part--inconclusive"
                            style={{ flexGrow: day.inconclusive }}
                          />
                        )}
                        {day.compliant > 0 && (
                          <span
                            className="trend__part trend__part--compliant"
                            style={{ flexGrow: day.compliant }}
                          />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {data.daily.length > 0 && (
                <p className="trend__axis data">
                  <span>{data.daily[0].date}</span>
                  <span>{data.daily[data.daily.length - 1].date}</span>
                </p>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
