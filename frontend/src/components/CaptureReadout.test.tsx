/*
  The frame-check readout.

  The line this guards: advisory, and only advisory. The component renders no control
  of any kind, so it is structurally incapable of blocking a capture — the tests
  assert that, alongside each prompt the feature brief names appearing when its check
  is out of tolerance and nothing appearing when the frame is clean.
*/

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { QualityReport } from "../lib/captureQuality";
import { CaptureReadout } from "./CaptureReadout";

function report(
  o: Partial<{
    sharpOk: boolean;
    brightness: "ok" | "dark" | "bright";
    glareOk: boolean;
    framing: "ok" | "small" | "cropped";
    fiducial: boolean;
  }> = {},
): QualityReport {
  const fiducial = o.fiducial ?? true;
  return {
    sharpness: { value: 200, ok: o.sharpOk ?? true },
    brightness: { value: 128, state: o.brightness ?? "ok" },
    glare: { fraction: 0.01, ok: o.glareOk ?? true },
    framing: { subjectFraction: 0.2, edgeBleed: 1, state: o.framing ?? "ok" },
    fiducial: { detected: fiducial, confidence: fiducial ? 0.7 : 0 },
  };
}

describe("the frame-check readout", () => {
  it("renders nothing before the first frame has been analysed", () => {
    const { container } = render(<CaptureReadout report={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("has no interactive elements — it cannot gate the shutter", () => {
    const { container } = render(<CaptureReadout report={report({ sharpOk: false, fiducial: false })} />);
    expect(container.querySelectorAll("button, input, select, textarea, [disabled]")).toHaveLength(0);
  });

  it("confirms the scale reference and shows no faults on a clean frame", () => {
    const { container } = render(<CaptureReadout report={report()} />);
    expect(screen.getByText("Scale reference detected.")).toBeInTheDocument();
    expect(container.querySelectorAll('[data-tone="fault"]')).toHaveLength(0);
    expect(screen.queryByText(/hold steady and retake/)).not.toBeInTheDocument();
    expect(screen.queryByText(/cut off/)).not.toBeInTheDocument();
  });

  it("prompts to retake a blurry frame", () => {
    render(<CaptureReadout report={report({ sharpOk: false })} />);
    expect(
      screen.getByText("Image looks blurry — hold steady and retake."),
    ).toBeInTheDocument();
  });

  it("prompts, without blocking, when no scale reference is in shot", () => {
    render(<CaptureReadout report={report({ fiducial: false })} />);
    expect(screen.getByText(/No scale reference detected/)).toBeInTheDocument();
    expect(screen.getByText(/still capture without one/)).toBeInTheDocument();
    expect(screen.getByText(/marked as not measurable/)).toBeInTheDocument();
  });

  it("prompts on a cut-off pack", () => {
    render(<CaptureReadout report={report({ framing: "cropped" })} />);
    expect(
      screen.getByText("Package appears cut off — fit the whole pack in frame."),
    ).toBeInTheDocument();
  });

  it("prompts on a pack that is too small in frame", () => {
    render(<CaptureReadout report={report({ framing: "small" })} />);
    expect(screen.getByText(/looks small in frame/)).toBeInTheDocument();
  });

  it("prompts on a dark frame", () => {
    render(<CaptureReadout report={report({ brightness: "dark" })} />);
    expect(screen.getByText("Too dark — improve lighting.")).toBeInTheDocument();
  });

  it("prompts on a washed-out frame", () => {
    render(<CaptureReadout report={report({ brightness: "bright" })} />);
    expect(screen.getByText(/Too bright/)).toBeInTheDocument();
  });

  it("prompts on glare", () => {
    render(<CaptureReadout report={report({ glareOk: false })} />);
    expect(
      screen.getByText("Glare detected — adjust angle or lighting."),
    ).toBeInTheDocument();
  });

  it("stacks every prompt when several checks are out of tolerance at once", () => {
    const { container } = render(
      <CaptureReadout
        report={report({ sharpOk: false, brightness: "dark", glareOk: false, framing: "cropped", fiducial: false })}
      />,
    );
    // focus, framing, light, glare, scale — all five.
    expect(container.querySelectorAll('[data-tone="fault"]')).toHaveLength(5);
  });
});
