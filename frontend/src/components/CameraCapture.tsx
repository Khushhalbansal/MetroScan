/*
  Photographing a package with the device camera.

  The one structural rule here: a captured frame leaves this component as an ordinary
  File and joins the same array the file picker fills. Nothing downstream — upload,
  storage, OCR, measurement, the rule engine — can tell a captured photograph from a
  chosen one, because there is nothing to tell. A separate "camera upload" path would
  be a second way in, and a second way in is a second place for the scale rules to be
  bypassed.

  Frames are encoded as PNG rather than JPEG deliberately. Rule 8 is decided from the
  thickness of printed strokes a millimetre tall; JPEG's ringing around high-contrast
  edges is exactly the kind of artefact that moves an ink measurement, and a few extra
  megabytes cost nothing next to a wrong measurement.
*/

import { useCallback, useEffect, useRef, useState } from "react";

import { analyseFrame, toFrame, type QualityReport } from "../lib/captureQuality";
import { CaptureReadout } from "./CaptureReadout";
import "./CameraCapture.css";

// How often the live preview is sampled. Fast enough to feel immediate, slow enough
// that the work — a 256 px downscale and a few linear passes — is nowhere near a
// frame budget even on a modest phone.
const SAMPLE_MS = 320;

/** A compact fingerprint of what the readout would show, so the live loop only
 *  re-renders when a check actually crosses a threshold — not 3× a second. */
function signatureOf(report: QualityReport | null): string {
  if (!report) return "none";
  return [
    report.sharpness.ok ? "s" : "S",
    report.brightness.state[0],
    report.glare.ok ? "g" : "G",
    report.framing.state[0],
    report.fiducial.detected ? "f" : "F",
  ].join("");
}

type Stage =
  | { kind: "closed" }
  | { kind: "opening" }
  | { kind: "live" }
  | { kind: "captured"; url: string; file: File }
  | { kind: "unavailable"; reason: string; recoverable: boolean };

interface Props {
  /** Hands the accepted photograph to the caller as a File, like any other upload. */
  onCapture: (file: File) => void;
  /** Number already staged, so the control can name what it is adding. */
  count: number;
}

// Ask for the most detail the device will give. A 640x480 frame cannot resolve a
// 1 mm character, so a scan captured at that size would be measurable in principle
// and unmeasurable in practice.
const CONSTRAINTS: MediaStreamConstraints = {
  video: {
    facingMode: { ideal: "environment" },
    width: { ideal: 2560 },
    height: { ideal: 1440 },
  },
  audio: false,
};

function describe(error: unknown): { reason: string; recoverable: boolean } {
  const name = error instanceof DOMException ? error.name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return {
        reason:
          "This browser is blocking camera access for the page. Allow the camera in " +
          "the address bar and open the camera again, or choose photographs from the " +
          "device instead.",
        recoverable: true,
      };
    case "NotFoundError":
    case "OverconstrainedError":
      return {
        reason: "No camera was found on this device. Choose photographs instead.",
        recoverable: false,
      };
    case "NotReadableError":
      return {
        reason:
          "The camera is in use by another application. Close it and try again, or " +
          "choose photographs instead.",
        recoverable: true,
      };
    default:
      return {
        reason:
          "The camera could not be opened on this device. Choose photographs instead.",
        recoverable: false,
      };
  }
}

export function CameraCapture({ onCapture, count }: Props) {
  const [stage, setStage] = useState<Stage>({ kind: "closed" });
  // Live, advisory frame quality. Never gates a capture; see CaptureReadout.
  const [quality, setQuality] = useState<QualityReport | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const lastSignature = useRef("none");

  const release = useCallback(() => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  }, []);

  // The camera light must go out when the officer navigates away, not whenever the
  // browser gets round to collecting the object.
  useEffect(() => release, [release]);

  // Attach the stream once React has actually committed the <video>.
  //
  // Doing this straight after setStage — even in a microtask — is a race: the ref is
  // still null until the commit, so the assignment lands on nothing and the viewfinder
  // stays black with the camera running behind it. An effect keyed on the stage is the
  // only point at which the element is guaranteed to exist.
  useEffect(() => {
    if (stage.kind !== "live" || !video.current || !stream.current) return;
    video.current.srcObject = stream.current;
    // play() only returns a Promise on newer engines; older WebViews — and the kind
    // of embedded browser a field device may well be running — return undefined, and
    // calling .catch on that throws inside the effect and takes the viewfinder with
    // it. An autoplay refusal is not fatal either way: the frame paints on the next
    // user gesture.
    const started: unknown = video.current.play();
    if (started instanceof Promise) started.catch(() => {});
  }, [stage.kind]);

  // Sample the live preview a few times a second for the advisory readout. The work
  // is done on a downscaled copy off-screen (toFrame); when no frame is available
  // yet, or no 2D canvas is present, this is a cheap no-op. It reads pixels only —
  // it never touches the captured File or the pipeline.
  useEffect(() => {
    if (stage.kind !== "live") return;
    lastSignature.current = "none";
    const id = window.setInterval(() => {
      const element = video.current;
      if (!element) return;
      const frame = toFrame(element);
      if (!frame) return;
      const report = analyseFrame(frame);
      const signature = signatureOf(report);
      if (signature === lastSignature.current) return;
      lastSignature.current = signature;
      setQuality(report);
    }, SAMPLE_MS);
    return () => window.clearInterval(id);
  }, [stage.kind]);

  const open = useCallback(async () => {
    // getUserMedia is absent, not merely refused, on an insecure origin — so this is
    // a different failure from a denied permission and gets a different sentence.
    if (!navigator.mediaDevices?.getUserMedia) {
      setStage({
        kind: "unavailable",
        reason:
          "This browser will not open a camera on an insecure connection. Use the " +
          "bench over HTTPS, or choose photographs from the device instead.",
        recoverable: false,
      });
      return;
    }

    setQuality(null);
    setStage({ kind: "opening" });
    try {
      const media = await navigator.mediaDevices.getUserMedia(CONSTRAINTS);
      stream.current = media;
      // The effect above wires this to the <video> once React has committed it.
      setStage({ kind: "live" });
    } catch (error) {
      release();
      setStage({ kind: "unavailable", ...describe(error) });
    }
  }, [release]);

  const close = useCallback(() => {
    release();
    setQuality(null);
    setStage({ kind: "closed" });
  }, [release]);

  const capture = useCallback(() => {
    const element = video.current;
    if (!element || !element.videoWidth) return;

    const canvas = document.createElement("canvas");
    canvas.width = element.videoWidth;
    canvas.height = element.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.drawImage(element, 0, 0, canvas.width, canvas.height);

    canvas.toBlob((blob) => {
      if (!blob) return;
      const name = `capture-${new Date().toISOString().replace(/[:.]/g, "-")}.png`;
      const file = new File([blob], name, { type: "image/png" });
      // Drop the live reading; the still is re-checked once it has decoded (onLoad).
      setQuality(null);
      setStage({ kind: "captured", url: URL.createObjectURL(blob), file });
      // The preview is a still; the camera is not needed again unless retaken.
      release();
    }, "image/png");
  }, [release]);

  const retake = useCallback(() => {
    if (stage.kind === "captured") URL.revokeObjectURL(stage.url);
    void open();
  }, [stage, open]);

  const accept = useCallback(() => {
    if (stage.kind !== "captured") return;
    onCapture(stage.file);
    URL.revokeObjectURL(stage.url);
    setQuality(null);
    setStage({ kind: "closed" });
  }, [stage, onCapture]);

  if (stage.kind === "closed") {
    return (
      <button type="button" className="capture__open" onClick={() => void open()}>
        <span className="capture__open-main">
          {count === 0 ? "Photograph the pack" : "Photograph another panel"}
        </span>
        <span className="capture__open-hint">
          Uses this device's camera. The photograph is added to the set below.
        </span>
      </button>
    );
  }

  if (stage.kind === "unavailable") {
    return (
      <div className="capture__unavailable" role="status">
        <p className="capture__unavailable-text">{stage.reason}</p>
        {stage.recoverable && (
          <button type="button" className="button" onClick={() => void open()}>
            Open the camera again
          </button>
        )}
        <button type="button" className="capture__dismiss" onClick={close}>
          Dismiss
        </button>
      </div>
    );
  }

  return (
    <div className="capture">
      <div className="capture__frame">
        {stage.kind === "opening" && (
          <p className="capture__waiting eyebrow">Opening the camera</p>
        )}

        {stage.kind === "live" && (
          <video ref={video} className="capture__video" playsInline muted />
        )}

        {stage.kind === "captured" && (
          <img
            className="capture__still"
            src={stage.url}
            alt="The photograph just taken"
            onLoad={(event) => {
              // Re-check the shot itself, once, before it is accepted.
              const frame = toFrame(event.currentTarget);
              if (frame) setQuality(analyseFrame(frame));
            }}
          />
        )}

        {/* The sighting frame: graduated corner marks, the same instrument as the
            Rule 8 rule. It marks the working area, it does not decorate it. */}
        <svg className="capture__reticle" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <path d="M4 14 V4 H14 M86 4 H96 V14 M96 86 V96 H86 M14 96 H4 V86" />
        </svg>
        <div className="capture__graduations" aria-hidden="true" />
      </div>

      {(stage.kind === "live" || stage.kind === "captured") && (
        <CaptureReadout report={quality} />
      )}

      <div className="capture__controls">
        {stage.kind === "live" && (
          <>
            <button type="button" className="button button--primary" onClick={capture}>
              Capture
            </button>
            <button type="button" className="button" onClick={close}>
              Close camera
            </button>
          </>
        )}

        {stage.kind === "captured" && (
          <>
            <button type="button" className="button button--primary" onClick={accept}>
              Use this photograph
            </button>
            <button type="button" className="button" onClick={() => void retake()}>
              Retake
            </button>
            <button type="button" className="button" onClick={close}>
              Discard
            </button>
          </>
        )}

        {stage.kind === "opening" && (
          <button type="button" className="button" onClick={close}>
            Cancel
          </button>
        )}
      </div>

      {stage.kind === "live" && (
        <p className="capture__note">
          Fill the frame with the declaration panel, and keep the scale card flat in the
          same plane as the label.
        </p>
      )}
    </div>
  );
}
