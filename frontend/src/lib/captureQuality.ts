/*
  Live capture guidance — the numbers behind the prompts.

  Runs client-side on a downscaled copy of the camera frame: a few times a second
  while the preview is live, and once on a shot before it is accepted. It is advisory
  only. Nothing here calibrates a measurement or reaches the pipeline — the backend's
  scale.py stays the sole authority on whether a photograph carries a usable scale
  reference, and a scan with no fiducial still resolves every Rule 8 finding to
  NEEDS_REVIEW exactly as before. All this does is let an officer notice a soft
  photograph, a cut-off pack or a missing scale card while the camera is still in
  hand, so the review outcome happens less often — never work around it after the fact.

  Kept deliberately cheap: a 256 px downscale and a handful of linear passes over
  ~49k pixels, with two small typed arrays and no other per-frame allocation. Every
  threshold below is pinned against a synthetic frame in captureQuality.test.ts.
*/

export interface Frame {
  data: Uint8ClampedArray;
  width: number;
  height: number;
}

export type BrightnessState = "ok" | "dark" | "bright";
export type FramingState = "ok" | "small" | "cropped";

export interface QualityReport {
  /** Laplacian variance on the downscaled luma. Higher is sharper. */
  sharpness: { value: number; ok: boolean };
  /** Mean luma, 0–255. */
  brightness: { value: number; state: BrightnessState };
  /** Fraction of the frame blown out to near-white — a specular-highlight proxy. */
  glare: { fraction: number; ok: boolean };
  /** Whether the pack reads as substantially in-frame and not sliced by an edge. */
  framing: { subjectFraction: number; edgeBleed: number; state: FramingState };
  /**
   * A hint that something crisp and card-like is in frame — a printed scale card or
   * an ID-1 card face. Not authoritative: a miss just shows the neutral nudge, and a
   * false hit still cannot make the backend measure anything.
   */
  fiducial: { detected: boolean; confidence: number };
}

// --- thresholds, all tuned against captureQuality.test.ts fixtures ---------------

/** Fixed downscale width, so the sharpness threshold means one thing across devices. */
export const ANALYSIS_WIDTH = 256;

const LAPLACIAN_VAR_MIN = 42;
const DARK_BELOW = 55;
const BRIGHT_ABOVE = 205;
const GLARE_LUMA = 248;
const GLARE_FRACTION_MAX = 0.045;
const EDGE_FLOOR = 18; // L1 gradient magnitude that counts as "detail"
const SUBJECT_MIN_FRACTION = 0.015;
const BORDER_BAND = 0.06; // fraction of width/height sampled as the frame edge
const EDGE_BLEED_RATIO = 1.15; // border detail vs interior detail
const EDGE_BLEED_SIDES = 2; // sides that must bleed before it reads as cropped

const FIDUCIAL_CELL = 16; // cell size, on the blurred luma
const FIDUCIAL_DARK = 70;
const FIDUCIAL_BRIGHT = 185;
const FIDUCIAL_BIMODAL_MIN = 0.16; // min(darkFrac, brightFrac) within a cell
const FIDUCIAL_EDGE_MIN = 0.18; // fraction of the cell that is a hard edge

const MIN_DIM = 24; // below this there is not enough frame to say anything

// --------------------------------------------------------------------------------

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

/** 3×3 box blur, separable. Cheap spatial-coherence filter: it barely touches the
 *  flats of a printed marker but pulls pixel noise toward mid-grey, which is what
 *  lets the fiducial hint tell a structured pattern from a noisy one. */
function boxBlur3(src: Uint8ClampedArray, w: number, h: number): Uint8ClampedArray {
  const tmp = new Float32Array(src.length);
  const out = new Uint8ClampedArray(src.length);
  for (let y = 0; y < h; y++) {
    const row = y * w;
    for (let x = 0; x < w; x++) {
      const a = src[row + (x > 0 ? x - 1 : 0)];
      const b = src[row + x];
      const c = src[row + (x < w - 1 ? x + 1 : w - 1)];
      tmp[row + x] = (a + b + c) / 3;
    }
  }
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) {
      const a = tmp[(y > 0 ? y - 1 : 0) * w + x];
      const b = tmp[y * w + x];
      const c = tmp[(y < h - 1 ? y + 1 : h - 1) * w + x];
      out[y * w + x] = (a + b + c) / 3;
    }
  }
  return out;
}

function detectFiducial(luma: Uint8ClampedArray, w: number, h: number): {
  detected: boolean;
  confidence: number;
} {
  if (w < FIDUCIAL_CELL * 2 || h < FIDUCIAL_CELL * 2) return { detected: false, confidence: 0 };
  const blur = boxBlur3(luma, w, h);
  let best = 0;
  let hits = 0;
  const cellPx = FIDUCIAL_CELL * FIDUCIAL_CELL;
  for (let cy = 0; cy + FIDUCIAL_CELL <= h; cy += FIDUCIAL_CELL) {
    for (let cx = 0; cx + FIDUCIAL_CELL <= w; cx += FIDUCIAL_CELL) {
      let dark = 0;
      let bright = 0;
      let edge = 0;
      for (let y = cy; y < cy + FIDUCIAL_CELL; y++) {
        for (let x = cx; x < cx + FIDUCIAL_CELL; x++) {
          const v = blur[y * w + x];
          if (v < FIDUCIAL_DARK) dark++;
          else if (v > FIDUCIAL_BRIGHT) bright++;
          const rx = x < w - 1 ? blur[y * w + x + 1] : v;
          const dy = y < h - 1 ? blur[(y + 1) * w + x] : v;
          if (Math.abs(rx - v) + Math.abs(dy - v) > 24) edge++;
        }
      }
      const bimodal = Math.min(dark, bright) / cellPx;
      const edgeFrac = edge / cellPx;
      if (bimodal >= FIDUCIAL_BIMODAL_MIN && edgeFrac >= FIDUCIAL_EDGE_MIN) {
        hits++;
        const score = bimodal + edgeFrac;
        if (score > best) best = score;
      }
    }
  }
  return { detected: hits >= 1, confidence: hits >= 1 ? clamp01(0.35 + best) : 0 };
}

/**
 * Judge one downscaled frame. Returns `null` when there is not enough of a frame to
 * say anything (too small, or an empty buffer).
 */
export function analyseFrame(frame: Frame): QualityReport | null {
  const { data, width: w, height: h } = frame;
  if (w < MIN_DIM || h < MIN_DIM || data.length < w * h * 4) return null;

  const luma = new Uint8ClampedArray(w * h);
  let lumaSum = 0;
  let blown = 0;
  for (let p = 0, i = 0; p < luma.length; p++, i += 4) {
    // Rec. 601 weights in fixed point; the exact coefficients do not matter here.
    const v = (data[i] * 77 + data[i + 1] * 150 + data[i + 2] * 29) >> 8;
    luma[p] = v;
    lumaSum += v;
    if (v >= GLARE_LUMA) blown++;
  }

  const bandX = Math.max(2, Math.round(w * BORDER_BAND));
  const bandY = Math.max(2, Math.round(h * BORDER_BAND));

  let lapSum = 0;
  let lapSqSum = 0;
  let lapN = 0;
  let interiorEdges = 0;
  let interiorMag = 0;
  let interiorN = 0;
  const side = { top: 0, bottom: 0, left: 0, right: 0 };
  const sideN = { top: 0, bottom: 0, left: 0, right: 0 };

  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const idx = y * w + x;
      const c = luma[idx];
      const l = luma[idx - 1];
      const r = luma[idx + 1];
      const u = luma[idx - w];
      const d = luma[idx + w];

      const lap = 4 * c - l - r - u - d;
      lapSum += lap;
      lapSqSum += lap * lap;
      lapN++;

      const mag = Math.abs(r - l) + Math.abs(d - u);
      const inTop = y < bandY;
      const inBottom = y >= h - bandY;
      const inLeft = x < bandX;
      const inRight = x >= w - bandX;

      if (inTop) {
        side.top += mag;
        sideN.top++;
      }
      if (inBottom) {
        side.bottom += mag;
        sideN.bottom++;
      }
      if (inLeft) {
        side.left += mag;
        sideN.left++;
      }
      if (inRight) {
        side.right += mag;
        sideN.right++;
      }
      if (!inTop && !inBottom && !inLeft && !inRight) {
        interiorMag += mag;
        if (mag > EDGE_FLOOR) interiorEdges++;
        interiorN++;
      }
    }
  }

  const lapMean = lapSum / lapN;
  const lapVar = lapSqSum / lapN - lapMean * lapMean;

  const meanLuma = lumaSum / luma.length;
  let brightnessState: BrightnessState = "ok";
  if (meanLuma < DARK_BELOW) brightnessState = "dark";
  else if (meanLuma > BRIGHT_ABOVE) brightnessState = "bright";

  const glareFraction = blown / luma.length;

  const subjectFraction = interiorN > 0 ? interiorEdges / interiorN : 0;
  const interiorMeanMag = interiorN > 0 ? interiorMag / interiorN : 0;
  let bleedSides = 0;
  let worstBleed = 0;
  for (const key of ["top", "bottom", "left", "right"] as const) {
    const sideMean = sideN[key] > 0 ? side[key] / sideN[key] : 0;
    const ratio = interiorMeanMag > 0.5 ? sideMean / interiorMeanMag : 0;
    if (ratio > worstBleed) worstBleed = ratio;
    if (sideMean > EDGE_FLOOR && ratio > EDGE_BLEED_RATIO) bleedSides++;
  }
  let framingState: FramingState = "ok";
  if (subjectFraction < SUBJECT_MIN_FRACTION) framingState = "small";
  else if (bleedSides >= EDGE_BLEED_SIDES) framingState = "cropped";

  return {
    sharpness: { value: lapVar, ok: lapVar >= LAPLACIAN_VAR_MIN },
    brightness: { value: meanLuma, state: brightnessState },
    glare: { fraction: glareFraction, ok: glareFraction <= GLARE_FRACTION_MAX },
    framing: { subjectFraction, edgeBleed: worstBleed, state: framingState },
    fiducial: detectFiducial(luma, w, h),
  };
}

type FrameSource = CanvasImageSource & {
  videoWidth?: number;
  videoHeight?: number;
  naturalWidth?: number;
  naturalHeight?: number;
  width?: number;
  height?: number;
};

/**
 * Draw a video element or an image onto a small offscreen canvas and read it back as
 * a {@link Frame}. Returns `null` when there is nothing to read yet (zero-size
 * source) or no 2D canvas is available — the analysis simply pauses rather than
 * throwing, which is also why it is inert under jsdom.
 */
export function toFrame(source: FrameSource, targetWidth = ANALYSIS_WIDTH): Frame | null {
  const sw = source.videoWidth || source.naturalWidth || source.width || 0;
  const sh = source.videoHeight || source.naturalHeight || source.height || 0;
  if (!sw || !sh) return null;

  const scale = Math.min(1, targetWidth / sw);
  const w = Math.max(1, Math.round(sw * scale));
  const h = Math.max(1, Math.round(sh * scale));

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  try {
    ctx.drawImage(source, 0, 0, w, h);
    const { data } = ctx.getImageData(0, 0, w, h);
    return { data, width: w, height: h };
  } catch {
    // A tainted canvas, or a headless environment with no real 2D backend.
    return null;
  }
}
