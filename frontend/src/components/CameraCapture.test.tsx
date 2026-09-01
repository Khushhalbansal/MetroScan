/*
  The camera, and the ways it fails.

  A capture control that dies quietly when permission is refused is worse than none at
  all: the officer taps it, nothing happens, and there is no sign that choosing files
  would work. So every failure path here is asserted to produce a sentence and leave
  the file picker reachable.
*/

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CameraCapture } from "./CameraCapture";

const originalMediaDevices = navigator.mediaDevices;

function setMediaDevices(value: unknown) {
  Object.defineProperty(navigator, "mediaDevices", {
    value,
    configurable: true,
    writable: true,
  });
}

function fakeStream() {
  const track = { stop: vi.fn() };
  return { stream: { getTracks: () => [track] } as unknown as MediaStream, track };
}

afterEach(() => {
  setMediaDevices(originalMediaDevices);
  vi.restoreAllMocks();
});

describe("opening the camera", () => {
  it("offers to photograph the pack before anything is staged", () => {
    render(<CameraCapture onCapture={vi.fn()} count={0} />);
    expect(screen.getByText("Photograph the pack")).toBeInTheDocument();
  });

  it("names the next photograph once one is already staged", () => {
    render(<CameraCapture onCapture={vi.fn()} count={1} />);
    expect(screen.getByText("Photograph another panel")).toBeInTheDocument();
  });

  it("asks for a resolution that can actually resolve a millimetre", async () => {
    const { stream } = fakeStream();
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    setMediaDevices({ getUserMedia });

    render(<CameraCapture onCapture={vi.fn()} count={0} />);
    await userEvent.click(screen.getByText("Photograph the pack"));

    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    const video = getUserMedia.mock.calls[0][0].video;
    // A 640x480 frame cannot resolve 1 mm type; a scan taken at that size would be
    // measurable in principle and unmeasurable in practice.
    expect(video.width.ideal).toBeGreaterThanOrEqual(1920);
    expect(video.facingMode.ideal).toBe("environment");
  });

  it("keeps the shutter live — the frame-check guidance never gates a capture", async () => {
    const { stream } = fakeStream();
    setMediaDevices({ getUserMedia: vi.fn().mockResolvedValue(stream) });

    render(<CameraCapture onCapture={vi.fn()} count={0} />);
    await userEvent.click(screen.getByText("Photograph the pack"));

    // The Capture button is present and enabled the moment the preview is live,
    // independent of anything the advisory readout might say.
    const capture = await screen.findByRole("button", { name: "Capture" });
    expect(capture).toBeEnabled();
  });

  it("releases the camera when the control is closed", async () => {
    const { stream, track } = fakeStream();
    setMediaDevices({ getUserMedia: vi.fn().mockResolvedValue(stream) });

    render(<CameraCapture onCapture={vi.fn()} count={0} />);
    await userEvent.click(screen.getByText("Photograph the pack"));
    await screen.findByText("Close camera");
    await userEvent.click(screen.getByText("Close camera"));

    // The camera light must go out when the officer is done with it.
    expect(track.stop).toHaveBeenCalled();
  });
});

describe("when the camera cannot be used", () => {
  it("explains a refused permission and offers to try again", async () => {
    setMediaDevices({
      getUserMedia: vi.fn().mockRejectedValue(new DOMException("no", "NotAllowedError")),
    });

    render(<CameraCapture onCapture={vi.fn()} count={0} />);
    await userEvent.click(screen.getByText("Photograph the pack"));

    expect(await screen.findByRole("status")).toHaveTextContent(/blocking camera access/);
    expect(screen.getByText(/choose photographs/i)).toBeInTheDocument();
    expect(screen.getByText("Open the camera again")).toBeInTheDocument();
  });

  it("says plainly when the device has no camera, and does not offer a retry", async () => {
    setMediaDevices({
      getUserMedia: vi.fn().mockRejectedValue(new DOMException("no", "NotFoundError")),
    });

    render(<CameraCapture onCapture={vi.fn()} count={0} />);
    await userEvent.click(screen.getByText("Photograph the pack"));

    expect(await screen.findByRole("status")).toHaveTextContent(/No camera was found/);
    expect(screen.queryByText("Open the camera again")).not.toBeInTheDocument();
  });

  it("names the insecure-origin case rather than reporting a denied permission", async () => {
    // getUserMedia is absent, not refused, on http:// — a different problem with a
    // different fix, and telling an officer to "allow the camera" would be a dead end.
    setMediaDevices(undefined);

    render(<CameraCapture onCapture={vi.fn()} count={0} />);
    await userEvent.click(screen.getByText("Photograph the pack"));

    expect(await screen.findByRole("status")).toHaveTextContent(/insecure connection/);
  });

  it("recovers to the closed state so the file picker is still reachable", async () => {
    setMediaDevices({
      getUserMedia: vi.fn().mockRejectedValue(new DOMException("no", "NotFoundError")),
    });

    render(<CameraCapture onCapture={vi.fn()} count={0} />);
    await userEvent.click(screen.getByText("Photograph the pack"));
    await userEvent.click(await screen.findByText("Dismiss"));

    expect(screen.getByText("Photograph the pack")).toBeInTheDocument();
  });
});
