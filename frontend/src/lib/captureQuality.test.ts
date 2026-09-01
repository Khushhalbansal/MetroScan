/*
  The live capture checks, pinned against synthetic frames.

  Each frame here is built pixel-by-pixel so the threshold it exercises is unambiguous:
  a linear ramp has no high-frequency detail and must read as soft; a mid-grey ground
  with a crisp checker patch must read as sharp, well-framed and carrying a scale
  reference; a 1 px checker is high-contrast noise and must NOT be mistaken for one.

  These are the checks the feature brief calls out by name: a blurry frame trips the
  focus prompt, a frame with no scale card trips that prompt (without any of this
  code being able to block a capture — it returns data, nothing more), and a clean
  frame with a visible card reports the reference and nothing else.
*/

import { describe, expect, it, vi } from "vitest";

import { analyseFrame, toFrame, type Frame } from "./captureQuality";

function frame(w: number, h: number): Frame {
  const data = new Uint8ClampedArray(w * h * 4);
  for (let i = 3; i < data.length; i += 4) data[i] = 255; // opaque
  return { data, width: w, height: h };
}

function set(f: Frame, x: number, y: number, v: number): void {
  if (x < 0 || y < 0 || x >= f.width || y >= f.height) return;
  const i = (y * f.width + x) * 4;
  f.data[i] = f.data[i + 1] = f.data[i + 2] = v;
}

function fill(f: Frame, v: number): void {
  for (let y = 0; y < f.height; y++) for (let x = 0; x < f.width; x++) set(f, x, y, v);
}

function rect(f: Frame, x0: number, y0: number, x1: number, y1: number, v: number): void {
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) set(f, x, y, v);
}

function box(f: Frame, x0: number, y0: number, x1: number, y1: number, v: number, t = 3): void {
  rect(f, x0, y0, x1, y0 + t, v);
  rect(f, x0, y1 - t, x1, y1, v);
  rect(f, x0, y0, x0 + t, y1, v);
  rect(f, x1 - t, y0, x1, y1, v);
}

function checker(f: Frame, x0: number, y0: number, size: number, cell: number): void {
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      const on = (Math.floor(x / cell) + Math.floor(y / cell)) % 2 === 0;
      set(f, x0 + x, y0 + y, on ? 0 : 255);
    }
}

function hstripes(f: Frame, x0: number, y0: number, w: number, rows: number, cell: number): void {
  for (let y = 0; y < rows; y++)
    for (let x = 0; x < w; x++) {
      const on = Math.floor(x / cell) % 2 === 0;
      set(f, x0 + x, y0 + y, on ? 70 : 155);
    }
}

/** A sharp, well-lit, well-framed pack. `withCard` adds a crisp checker patch that
 *  stands in for the printed scale card. */
function goodFrame(withCard: boolean): Frame {
  const f = frame(256, 192);
  fill(f, 128);
  box(f, 44, 26, 212, 166, 40); // the pack outline, clear of the 6% border band
  for (let row = 46; row < 150; row += 20) hstripes(f, 60, row, 150, 6, 4); // printed lines
  if (withCard) checker(f, 168, 120, 40, 8);
  return f;
}

describe("analyseFrame — focus", () => {
  it("reads a linear ramp as soft (no high-frequency detail)", () => {
    const f = frame(256, 192);
    for (let y = 0; y < f.height; y++)
      for (let x = 0; x < f.width; x++) set(f, x, y, Math.round((x / f.width) * 255));
    const report = analyseFrame(f)!;
    expect(report.sharpness.ok).toBe(false);
  });

  it("reads a crisp patterned frame as sharp", () => {
    const report = analyseFrame(goodFrame(true))!;
    expect(report.sharpness.ok).toBe(true);
  });
});

describe("analyseFrame — brightness", () => {
  it("flags a dark frame", () => {
    const f = frame(64, 48);
    fill(f, 20);
    expect(analyseFrame(f)!.brightness.state).toBe("dark");
  });

  it("flags a washed-out frame as bright, distinct from specular glare", () => {
    const f = frame(64, 48);
    fill(f, 235); // high, but below the blown-highlight cutoff
    const report = analyseFrame(f)!;
    expect(report.brightness.state).toBe("bright");
    expect(report.glare.ok).toBe(true);
  });

  it("reads an evenly-lit mid-grey frame as ok", () => {
    expect(analyseFrame(goodFrame(true))!.brightness.state).toBe("ok");
  });
});

describe("analyseFrame — glare", () => {
  it("flags a large blown-out highlight", () => {
    const f = goodFrame(false);
    rect(f, 90, 70, 165, 140, 255); // ~7.6% of the frame at full white
    expect(analyseFrame(f)!.glare.ok).toBe(false);
  });

  it("does not flag a small bright detail", () => {
    expect(analyseFrame(goodFrame(true))!.glare.ok).toBe(true);
  });
});

describe("analyseFrame — framing", () => {
  it("reads a near-empty frame as the subject being too small", () => {
    const f = frame(256, 192);
    fill(f, 130);
    rect(f, 122, 92, 134, 104, 60); // a speck in the middle
    expect(analyseFrame(f)!.framing.state).toBe("small");
  });

  it("reads detail running hard into the edges as cropped", () => {
    const f = frame(256, 192);
    fill(f, 128);
    // A pack whose edges are sliced by the frame on every side.
    box(f, 0, 0, 256, 192, 30, 8);
    for (let row = 12; row < 180; row += 16) hstripes(f, 2, row, 252, 6, 4);
    expect(analyseFrame(f)!.framing.state).toBe("cropped");
  });

  it("reads a pack sitting inside the frame as ok", () => {
    expect(analyseFrame(goodFrame(true))!.framing.state).toBe("ok");
  });
});

describe("analyseFrame — scale reference hint", () => {
  it("detects a crisp card-like patch", () => {
    const report = analyseFrame(goodFrame(true))!;
    expect(report.fiducial.detected).toBe(true);
    expect(report.fiducial.confidence).toBeGreaterThan(0);
  });

  it("reports no reference when the card is absent", () => {
    expect(analyseFrame(goodFrame(false))!.fiducial.detected).toBe(false);
  });

  it("is not fooled by high-contrast pixel noise", () => {
    const f = frame(256, 192);
    for (let y = 0; y < f.height; y++)
      for (let x = 0; x < f.width; x++) set(f, x, y, (x + y) % 2 === 0 ? 0 : 255);
    expect(analyseFrame(f)!.fiducial.detected).toBe(false);
  });
});

describe("analyseFrame — a good frame with a card trips nothing else", () => {
  it("every other check reads ok", () => {
    const r = analyseFrame(goodFrame(true))!;
    expect(r.sharpness.ok).toBe(true);
    expect(r.brightness.state).toBe("ok");
    expect(r.glare.ok).toBe(true);
    expect(r.framing.state).toBe("ok");
    expect(r.fiducial.detected).toBe(true);
  });
});

describe("analyseFrame — guards", () => {
  it("returns null for a frame too small to judge", () => {
    expect(analyseFrame(frame(10, 10))).toBeNull();
  });
});

describe("analyseFrame — cost", () => {
  it("stays well inside a live-preview budget on a 256×192 frame", () => {
    const f = goodFrame(true);
    analyseFrame(f); // warm up
    const runs = 200;
    const start = performance.now();
    for (let i = 0; i < runs; i++) analyseFrame(f);
    const perCall = (performance.now() - start) / runs;
    // Sampled ~3×/sec; a frame is ~16 ms. This has a very wide margin — the assertion
    // exists to catch a future change that makes the pass structure super-linear.
    expect(perCall).toBeLessThan(6);
  });
});

describe("toFrame", () => {
  it("returns null when there is nothing to draw", () => {
    expect(toFrame({ videoWidth: 0, videoHeight: 0 } as never)).toBeNull();
  });

  it("returns null when no 2D canvas backend is available (headless)", () => {
    // Documents that the whole analysis pauses cleanly rather than throwing when a
    // real canvas is not there — the reason it is inert under jsdom.
    const getContext = vi
      .spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(null);
    expect(toFrame({ videoWidth: 200, videoHeight: 150 } as never)).toBeNull();
    getContext.mockRestore();
  });
});
