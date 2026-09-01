/*
  The frame check, shown as the readout on the side of the camera.

  Instrument-panel language, not a toast: an eyebrow that says what is being read, and
  a short list of only what is out of tolerance, each line a mark plus the fact and
  the fix. When the frame is clean and a scale reference is in shot it settles to a
  single confirming line.

  This component has no interactive elements and no network surface. It cannot gate a
  capture — the shutter stays live whatever it says — and it reports nothing to the
  backend. Its whole job is to let an officer catch a soft or unscaled shot before it
  is taken, so the NEEDS_REVIEW outcome the pipeline already produces for an unscaled
  pack simply happens less often.
*/

import type { QualityReport } from "../lib/captureQuality";
import "./CaptureReadout.css";

const SCALE_ABSENT =
  "No scale reference detected — place a coin or the printed scale card beside the " +
  "pack for an accurate measurement. You can still capture without one, but " +
  "font-size findings will be marked as not measurable.";

interface Cue {
  key: string;
  tone: "fault" | "ok";
  text: string;
}

function cues(report: QualityReport): Cue[] {
  const out: Cue[] = [];

  if (!report.sharpness.ok) {
    out.push({ key: "focus", tone: "fault", text: "Image looks blurry — hold steady and retake." });
  }
  if (report.framing.state === "cropped") {
    out.push({
      key: "framing",
      tone: "fault",
      text: "Package appears cut off — fit the whole pack in frame.",
    });
  } else if (report.framing.state === "small") {
    out.push({
      key: "framing",
      tone: "fault",
      text: "Package looks small in frame — move closer to fill it.",
    });
  }
  if (report.brightness.state === "dark") {
    out.push({ key: "light", tone: "fault", text: "Too dark — improve lighting." });
  } else if (report.brightness.state === "bright") {
    out.push({
      key: "light",
      tone: "fault",
      text: "Too bright — reduce light or angle away from it.",
    });
  }
  if (!report.glare.ok) {
    out.push({ key: "glare", tone: "fault", text: "Glare detected — adjust angle or lighting." });
  }

  out.push(
    report.fiducial.detected
      ? { key: "scale", tone: "ok", text: "Scale reference detected." }
      : { key: "scale", tone: "fault", text: SCALE_ABSENT },
  );
  return out;
}

const MARK: Record<Cue["tone"], string> = { fault: "▲", ok: "✓" };

interface Props {
  report: QualityReport | null;
}

export function CaptureReadout({ report }: Props) {
  if (!report) return null;

  const items = cues(report);
  const clear = items.every((c) => c.tone === "ok");

  return (
    <div className={`readout ${clear ? "readout--clear" : ""}`} role="status" aria-live="polite">
      <p className="readout__eyebrow eyebrow">Frame check{clear ? " · within tolerance" : ""}</p>
      <ul className="readout__lines">
        {items.map((c) => (
          <li
            key={c.key}
            className={`readout__line readout__line--${c.tone}`}
            data-tone={c.tone}
          >
            <span className="readout__mark" aria-hidden="true">
              {MARK[c.tone]}
            </span>
            <span className="readout__text">{c.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
