/*
  A status, carried by colour AND glyph AND word — never colour alone.

  An inspection file gets photocopied, faxed to a district office, and printed in
  greyscale. A status that is only a colour survives none of that, and about one in
  twelve men cannot distinguish the oxide from the patina on screen either.

  The glyphs are drawn rather than emoji so they inherit the ink colour and stay put
  across platforms.
*/

import type { FindingStatus, Verdict } from "../api/types";
import "./StatusMark.css";

const FINDING_WORDS: Record<FindingStatus, string> = {
  PASS: "Pass",
  FAIL: "Fail",
  NEEDS_REVIEW: "Needs review",
  NA: "Not applicable",
};

const VERDICT_WORDS: Record<Verdict, string> = {
  COMPLIANT: "Compliant",
  NON_COMPLIANT: "Non-compliant",
  INCONCLUSIVE: "Inconclusive",
};

function Glyph({ status }: { status: FindingStatus | Verdict }) {
  const common = { width: 12, height: 12, viewBox: "0 0 12 12", "aria-hidden": true };
  switch (status) {
    case "PASS":
    case "COMPLIANT":
      // A verification stamp's tick.
      return (
        <svg {...common}>
          <path d="M1.5 6.4 4.4 9.3 10.5 2.8" fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
      );
    case "FAIL":
    case "NON_COMPLIANT":
      return (
        <svg {...common}>
          <path d="M2 2 10 10 M10 2 2 10" fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
      );
    case "NEEDS_REVIEW":
    case "INCONCLUSIVE":
      // A half-graduation: the reading fell between two marks.
      return (
        <svg {...common}>
          <path d="M6 1 V11" stroke="currentColor" strokeWidth="2" />
          <path d="M2 6 H10" stroke="currentColor" strokeWidth="1" opacity="0.5" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <path d="M2 6 H10" stroke="currentColor" strokeWidth="2" />
        </svg>
      );
  }
}

export function StatusMark({
  status,
  size = "normal",
}: {
  status: FindingStatus;
  size?: "normal" | "small";
}) {
  return (
    <span className={`status status--${status} status--${size}`}>
      <Glyph status={status} />
      <span className="status__word">{FINDING_WORDS[status]}</span>
    </span>
  );
}

export function VerdictMark({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`verdict verdict--${verdict}`}>
      <Glyph status={verdict} />
      <span className="verdict__word">{VERDICT_WORDS[verdict]}</span>
    </span>
  );
}
