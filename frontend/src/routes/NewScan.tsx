/*
  Running a compliance check.

  The one thing this screen has to get across before anything else: put something of
  known size in the frame, or Rule 8 cannot be checked at all. That is not a tip in
  small print, it is the difference between a measurement and a guess — so it sits
  above the file picker with the same weight as the picker itself.

  Note there is no field here for a scale, a millimetres-per-pixel, or a panel area.
  The API does not accept one. A form that let an officer type a scale would let them
  manufacture measured-looking findings for a photograph with no reference in it.
*/

import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { CameraCapture } from "../components/CameraCapture";
import { CaptureGuidance } from "../components/CaptureGuidance";
import "./NewScan.css";

// Mirrors MAX_IMAGES in backend/app/services/imaging.py. Stopping here means the
// officer is told before waiting through an upload the server will refuse.
const MAX_IMAGES = 8;

export function NewScan() {
  const [files, setFiles] = useState<File[]>([]);
  const [productName, setProductName] = useState("");
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("");
  const [imported, setImported] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const atLimit = files.length >= MAX_IMAGES;

  const addFiles = useCallback((incoming: File[]) => {
    setFiles((current) => [...current, ...incoming].slice(0, MAX_IMAGES));
  }, []);

  // Named separately so the camera's single-file callback reads plainly at the call
  // site; both funnel into the same array.
  const addFile = useCallback((file: File) => addFiles([file]), [addFiles]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!files.length || !productName.trim() || busy) return;

    const form = new FormData();
    for (const file of files) form.append("images", file);
    form.append("product_name", productName.trim());
    if (brand.trim()) form.append("brand", brand.trim());
    if (category.trim()) form.append("category", category.trim());
    form.append("is_imported", String(imported));

    setBusy(true);
    setError(null);
    try {
      const scan = await api.createScan(form);
      navigate(`/scans/${scan.scan_id}`);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="check">
      <p className="eyebrow">New check</p>
      <h1 className="check__title">Run a compliance check</h1>

      <div className="graduated" aria-hidden="true" />

      <div className="check__scale-note">
        <p className="check__scale-head">
          Put something of known size in the frame.
        </p>
        <p className="check__scale-body">
          Character heights are a physical measurement, and a photograph carries no scale
          of its own. Lay the printable scale card, an ID-1 card (Aadhaar, PAN, a debit
          card) or a ₹5 or ₹10 coin flat beside the pack, in the same plane as the label.
          Without one, every Rule 8 finding comes back for your review rather than
          decided — nothing is guessed.
        </p>
      </div>

      <CaptureGuidance />

      <form className="check__form" onSubmit={submit}>
        <div className="check__field">
          <label className="check__label" htmlFor="product">
            Product name
          </label>
          <input
            id="product"
            className="check__input"
            required
            value={productName}
            onChange={(e) => setProductName(e.target.value)}
            placeholder="Roasted Chana Masala"
          />
          <p className="check__help">
            Re-scans of the same product sit on one timeline, so use the name as printed.
          </p>
        </div>

        <div className="check__pair">
          <div className="check__field">
            <label className="check__label" htmlFor="brand">
              Brand <span className="check__optional">optional</span>
            </label>
            <input
              id="brand"
              className="check__input"
              value={brand}
              onChange={(e) => setBrand(e.target.value)}
            />
          </div>
          <div className="check__field">
            <label className="check__label" htmlFor="category">
              Category <span className="check__optional">optional</span>
            </label>
            <input
              id="category"
              className="check__input"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="FOOD"
            />
          </div>
        </div>

        <label className="check__toggle">
          <input
            type="checkbox"
            checked={imported}
            onChange={(e) => setImported(e.target.checked)}
          />
          <span>
            Imported package
            <span className="check__help">
              Adds the country-of-origin and importer checks.
            </span>
          </span>
        </label>

        <div className="check__field">
          <span className="check__label">Photographs</span>

          {/* Two ways to put a photograph on the bench, one destination. A captured
              frame and a chosen file are both Files in `files`; nothing after this
              point knows which is which. */}
          <CameraCapture onCapture={addFile} count={files.length} />

          <button
            type="button"
            className="check__drop"
            onClick={() => input.current?.click()}
          >
            <span className="check__drop-main">Choose photographs from this device</span>
            <span className="check__help">
              Front, back and any panel carrying declarations. Up to {MAX_IMAGES}.
            </span>
          </button>
          <input
            ref={input}
            type="file"
            className="visually-hidden"
            accept="image/jpeg,image/png,image/webp"
            multiple
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []));
              // Clear the control so choosing the same file twice still fires change.
              e.target.value = "";
            }}
          />

          {files.length > 0 && (
            <ul className="staged">
              {files.map((file, index) => (
                <li key={`${file.name}-${index}`} className="staged__row">
                  <span className="staged__name data">{file.name}</span>
                  <span className="staged__size data">
                    {(file.size / 1024 / 1024).toFixed(1)} MB
                  </span>
                  <button
                    type="button"
                    className="staged__remove"
                    onClick={() => setFiles(files.filter((_, i) => i !== index))}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}

          {atLimit && (
            <p className="check__help">
              {MAX_IMAGES} photographs is the limit for one check. Remove one to add
              another.
            </p>
          )}
        </div>

        {error && (
          <p className="notice notice--problem" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          className="button button--primary check__submit"
          disabled={busy || !files.length || !productName.trim()}
        >
          {busy ? "Running compliance check" : "Run compliance check"}
        </button>
        {busy && (
          <p className="check__waiting">
            Reading the label. This takes a few seconds per photograph.
          </p>
        )}
      </form>
    </div>
  );
}
