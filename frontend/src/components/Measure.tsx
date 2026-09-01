/*
  The Measure — a Rule 8 finding rendered as an actual millimetre rule.

  This is the one thing the product does that nothing else does, so it gets the
  boldness budget and everything around it stays quiet.

  The reason it is a ruler and not a badge is substantive. Rule 8 does not ask whether
  a label looks right; it asks whether a letter is at least N millimetres tall, where N
  depends on the area of the principal display panel. A red pill reading "font too
  small" throws away every part of that: how short, against what limit, on a panel of
  what size. A graduated scale with a brass limit line keeps all of it, and an officer
  can check the reading by holding a rule against the pack.

  Drawn in SVG so the graduations stay crisp at any width, and mirrored by
  backend/app/reports/measure.py so screen and paper are the same instrument.
*/

import { useEffect, useRef, useState } from "react";

import { useTilt } from "../lib/motion";
import "./Measure.css";

export interface MeasureProps {
  /** Null when the scan could not measure — no scale in frame, or nothing found. */
  measuredMm: number | null;
  requiredMm: number;
  citation?: string | null;
  panelAreaCm2?: number | null;
  /** Suppresses the index sweep when the row is rendered off-screen. */
  animate?: boolean;
}

const MIN_SCALE_MM = 6;
const HEADROOM = 1.35;

// Viewbox units. Height covers ticks, the bar, the limit flag and the numerals.
const W = 1000;
const H = 78;
const BASELINE = 42;

function scaleMax(measured: number | null, required: number): number {
  const largest = Math.max(required, measured ?? 0);
  return Math.max(MIN_SCALE_MM, Math.floor(largest * HEADROOM) + 1);
}

export function Measure({
  measuredMm,
  requiredMm,
  citation,
  panelAreaCm2,
  animate = true,
}: MeasureProps) {
  const max = scaleMax(measuredMm, requiredMm);
  const x = (mm: number) => (Math.min(mm, max) / max) * W;

  const compliant = measuredMm !== null && measuredMm >= requiredMm;
  const shortfall =
    measuredMm !== null && measuredMm < requiredMm
      ? Math.round((requiredMm - measuredMm) * 100) / 100
      : null;

  // The index sweeps once to its reading. Not decoration: it is the gesture of a
  // needle settling, which is what the number means.
  const [swept, setSwept] = useState(!animate);
  const frame = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!animate) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setSwept(true);
      return;
    }
    frame.current = requestAnimationFrame(() => setSwept(true));
    return () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    };
  }, [animate]);

  const ticks: Array<{ mm: number; major: boolean }> = [];
  for (let step = 0; step <= max * 2; step += 1) {
    ticks.push({ mm: step / 2, major: step % 2 === 0 });
  }

  const barWidth = measuredMm === null ? 0 : x(measuredMm);
  const reading =
    measuredMm === null ? "not measurable" : `${measuredMm.toFixed(2)} mm`;

  // A ≤6° pointer-follow tilt on the plane the rule sits on (design-direction.md
  // v2). The graduations, limit line and numerals ride the plane without skewing.
  const tilt = useTilt<HTMLElement>(6);

  return (
    <figure className="measure" ref={tilt}>
      <svg
        className="measure__rule"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={
          measuredMm === null
            ? `Not measured. Rule 8 requires ${requiredMm} millimetres.`
            : `Measured ${measuredMm} millimetres against a ${requiredMm} millimetre minimum.`
        }
      >
        {/* graduations — tall at whole millimetres, short between */}
        {ticks.map(({ mm, major }) => (
          <line
            key={mm}
            x1={x(mm)}
            x2={x(mm)}
            y1={major ? BASELINE - 20 : BASELINE - 10}
            y2={BASELINE}
            className={major ? "measure__tick measure__tick--major" : "measure__tick"}
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {/* the scale line */}
        <line
          x1="0"
          x2={W}
          y1={BASELINE}
          y2={BASELINE}
          className="measure__baseline"
          vectorEffect="non-scaling-stroke"
        />

        {/* the measurement, shaded to the index; oxide when it falls short */}
        {measuredMm !== null && (
          <rect
            x="0"
            y={BASELINE + 3}
            width={swept ? barWidth : 0}
            height="11"
            className={compliant ? "measure__bar measure__bar--met" : "measure__bar"}
          />
        )}

        {/* the brass limit line at the height the rule requires */}
        <line
          x1={x(requiredMm)}
          x2={x(requiredMm)}
          y1={BASELINE - 26}
          y2={BASELINE + 20}
          className="measure__limit"
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      {/* numerals sit outside the SVG so they never stretch with it */}
      <div className="measure__numerals" aria-hidden="true">
        {ticks
          .filter((t) => t.major)
          .map(({ mm }) => (
            <span
              key={mm}
              className="measure__numeral data"
              style={{ left: `${(mm / max) * 100}%` }}
            >
              {mm}
            </span>
          ))}
      </div>

      <figcaption className="measure__caption">
        <span className="measure__reading">
          <span className="eyebrow">measured</span>{" "}
          <strong
            className={`data measure__value ${
              measuredMm === null
                ? "measure__value--unknown"
                : compliant
                  ? "measure__value--met"
                  : "measure__value--short"
            }`}
          >
            {reading}
          </strong>
          {shortfall !== null && (
            <span className="measure__shortfall"> short by {shortfall.toFixed(2)} mm</span>
          )}
        </span>
        <span className="measure__limit-label">
          <span className="eyebrow">required</span>{" "}
          <strong className="data measure__value measure__value--limit">
            {requiredMm.toFixed(1)} mm
          </strong>
          {citation && <span className="measure__cite"> · {citation}</span>}
          {panelAreaCm2 ? (
            <span className="measure__cite"> · panel {Math.round(panelAreaCm2)} cm²</span>
          ) : null}
        </span>
      </figcaption>
    </figure>
  );
}

/**
 * Build a Measure from a finding's detail, or null when the finding is not a
 * measurement. Rendering a ruler for a presence check would be inventing a reading.
 */
export function measureFromDetail(
  detail: Record<string, unknown>,
): { measuredMm: number | null; requiredMm: number; panelAreaCm2: number | null } | null {
  const required = detail.required_mm;
  if (typeof required !== "number") return null;
  const measured = detail.measured_mm;
  const area = detail.pdp_area_cm2;
  return {
    measuredMm: typeof measured === "number" ? measured : null,
    requiredMm: required,
    panelAreaCm2: typeof area === "number" ? area : null,
  };
}
