/*
  The compliance score as a calibrated scale reading — the same instrument as the
  Rule 8 rule, at a different scale.

  Deliberately not a donut and not a gauge. Those are the template answer, they break
  the ruler metaphor, and neither can show a threshold: the whole question about a
  score here is which side of the pass limit it falls on.

  The score never appears without its coverage. 100% over two decided rules is not the
  same claim as 100% over twenty, and a bare number invites the reader to treat the
  first as the second — so the coverage is part of this component, not a sibling a
  caller might forget.
*/

import { useEffect, useState } from "react";
import "./ScoreScale.css";

export interface ScoreScaleProps {
  /** Null when nothing could be decided. Renders as a stated absence, never a zero. */
  score: number | null;
  decided: number;
  applicable: number;
  threshold?: number;
}

export function ScoreScale({
  score,
  decided,
  applicable,
  threshold = 85,
}: ScoreScaleProps) {
  const [swept, setSwept] = useState(false);
  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setSwept(true);
      return;
    }
    const id = requestAnimationFrame(() => setSwept(true));
    return () => cancelAnimationFrame(id);
  }, []);

  if (score === null) {
    return (
      <div className="score score--unscored">
        <p className="score__none">
          <strong>Not scored.</strong> No rule could be decided from these images, so
          there is no reading to give.
        </p>
        <p className="score__coverage">
          <span className="data">0</span> of{" "}
          <span className="data">{applicable}</span> applicable rules decided
        </p>
      </div>
    );
  }

  const met = score >= threshold;
  const ticks = Array.from({ length: 21 }, (_, i) => i * 5);

  return (
    <div className="score">
      <div className="score__instrument">
        <div className="score__graduations" aria-hidden="true">
          {ticks.map((value) => (
            <span
              key={value}
              className={`score__tick ${value % 25 === 0 ? "score__tick--major" : ""}`}
              style={{ left: `${value}%` }}
            />
          ))}
        </div>
        <div className="score__track">
          <div
            className={`score__bar ${met ? "score__bar--met" : "score__bar--short"}`}
            style={{ width: swept ? `${score}%` : "0%" }}
          />
          <span
            className="score__limit"
            style={{ left: `${threshold}%` }}
            aria-hidden="true"
          />
        </div>
        <span className="score__limit-label eyebrow" style={{ left: `${threshold}%` }}>
          {threshold} pass
        </span>
      </div>

      <p className="score__reading">
        <strong className={`data score__value ${met ? "is-met" : "is-short"}`}>
          {score.toFixed(1)}
        </strong>
        <span className="score__denominator data"> / 100</span>
        <span className="score__coverage">
          {" "}
          over <span className="data">{decided}</span> of{" "}
          <span className="data">{applicable}</span> applicable rules decided
        </span>
      </p>
    </div>
  );
}
