/*
  The photographs a filed scan was judged from, and the controls to change them.

  Every control here re-runs the whole compliance check on the server. That is stated
  on the screen rather than hidden, because an officer deleting a blurred frame is not
  doing housekeeping — they are changing the evidence, and the verdict may move.

  While the re-run is in flight the findings on screen belong to the previous image set,
  so the whole examination is dimmed and labelled. A ledger that looks live while the
  evidence beneath it has already changed is exactly the stale state this feature exists
  to prevent.
*/

import { useRef, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ScanImage, ScanResult } from "../api/types";
import "./ImageStrip.css";

interface Props {
  scanId: string;
  images: ScanImage[];
  revision: number;
  /** True while the scan is being re-judged; disables every control. */
  busy: boolean;
  onBusy: (reason: string | null) => void;
  onScan: (scan: ScanResult) => void;
  onError: (message: string | null) => void;
}

const MAX_IMAGES = 8;

export function ImageStrip({
  scanId,
  images,
  revision,
  busy,
  onBusy,
  onScan,
  onError,
}: Props) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const addInput = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const replacingId = useRef<string | null>(null);

  const run = async (reason: string, action: () => Promise<ScanResult>) => {
    onError(null);
    onBusy(reason);
    try {
      onScan(await action());
    } catch (error: unknown) {
      onError(error instanceof ApiError ? error.message : String(error));
    } finally {
      onBusy(null);
      setConfirming(null);
    }
  };

  const add = (file: File) =>
    run("Adding the photograph and re-running the check", () => api.addImage(scanId, file));

  const replace = (file: File) => {
    const imageId = replacingId.current;
    if (!imageId) return;
    return run("Retaking the photograph and re-running the check", () =>
      api.replaceImage(scanId, imageId, file),
    );
  };

  const remove = (imageId: string) =>
    run("Removing the photograph and re-running the check", () =>
      api.removeImage(scanId, imageId),
    );

  const atLimit = images.length >= MAX_IMAGES;
  const last = images.length <= 1;

  return (
    <section className="strip">
      <header className="strip__head">
        <h2 className="strip__title">Photographs</h2>
        <p className="strip__note">
          {revision > 1 && (
            <span className="strip__revision data">reading {revision} · </span>
          )}
          Changing these re-runs the compliance check.
        </p>
      </header>

      <ul className="strip__list">
        {images.map((image) => (
          <li key={image.image_id} className="strip__item">
            <div className="strip__meta">
              <span className="strip__kind">{image.kind.toLowerCase()}</span>
              <span className="strip__dims data">
                {image.width}×{image.height} px · {image.blocks_read} regions read
              </span>
              {image.filename && (
                <span className="strip__file data">{image.filename}</span>
              )}
            </div>

            {confirming === image.image_id ? (
              <div className="strip__confirm">
                <p className="strip__confirm-text">
                  {images.length - 1 === 1
                    ? "Remove this photograph and re-judge the pack from the one that remains?"
                    : `Remove this photograph and re-judge the pack from the ${
                        images.length - 1
                      } that remain?`}
                </p>
                <div className="strip__confirm-actions">
                  <button
                    type="button"
                    className="button button--danger"
                    disabled={busy}
                    onClick={() => void remove(image.image_id)}
                  >
                    Remove and re-check
                  </button>
                  <button
                    type="button"
                    className="button"
                    disabled={busy}
                    onClick={() => setConfirming(null)}
                  >
                    Keep it
                  </button>
                </div>
              </div>
            ) : (
              <div className="strip__actions">
                <button
                  type="button"
                  className="strip__action"
                  disabled={busy}
                  onClick={() => {
                    replacingId.current = image.image_id;
                    replaceInput.current?.click();
                  }}
                >
                  Retake
                </button>
                <button
                  type="button"
                  className="strip__action strip__action--remove"
                  disabled={busy || last}
                  title={
                    last ? "A scan must keep at least one photograph." : undefined
                  }
                  onClick={() => setConfirming(image.image_id)}
                >
                  Remove
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>

      <button
        type="button"
        className="strip__add"
        disabled={busy || atLimit}
        onClick={() => addInput.current?.click()}
      >
        {atLimit
          ? `${MAX_IMAGES} photographs is the limit for one check`
          : "Add a photograph and re-check"}
      </button>

      <input
        ref={addInput}
        type="file"
        className="visually-hidden"
        accept="image/jpeg,image/png,image/webp"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) void add(file);
        }}
      />
      <input
        ref={replaceInput}
        type="file"
        className="visually-hidden"
        accept="image/jpeg,image/png,image/webp"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) void replace(file);
        }}
      />
    </section>
  );
}
