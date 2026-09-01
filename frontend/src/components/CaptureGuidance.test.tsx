/*
  The guidance plates, and the line between an illustration and evidence.

  The risk this file guards is not that the panel looks wrong. It is that a reference
  image ends up attached to a scan — a drawing of a package filed as a photograph of
  one. The plates are static assets under /guidance/, evidence lives behind
  /api/v1/scans/..., and these tests assert the separation rather than trusting it.
*/

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CaptureGuidance } from "./CaptureGuidance";

describe("the capture guidance plates", () => {
  it("stays collapsed until an officer asks for it", () => {
    render(<CaptureGuidance />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("shows four plates when opened", async () => {
    // Queried as elements, not by role: each plate carries alt="" on purpose. The
    // heading and the consequence beneath it describe the drawing in full, so the
    // image is decorative in the accessibility tree and repeating it in alt text
    // would only make a screen reader say everything twice.
    const { container } = render(<CaptureGuidance />);
    await userEvent.click(screen.getByRole("button"));

    expect(container.querySelectorAll("img")).toHaveLength(4);
  });

  it("says why each setup matters, not just what to do", async () => {
    // "Hold the camera steady" is a tip. "Type measures shorter than it is" is a
    // consequence an officer can weigh.
    render(<CaptureGuidance />);
    await userEvent.click(screen.getByRole("button"));

    expect(screen.getByText(/measures shorter than it is/)).toBeInTheDocument();
    expect(screen.getByText(/carries no scale of its own/)).toBeInTheDocument();
    expect(screen.getByText(/reads as nothing at all/)).toBeInTheDocument();
  });

  it("draws every plate from the static guidance path, never from the scan API", async () => {
    const { container } = render(<CaptureGuidance />);
    await userEvent.click(screen.getByRole("button"));

    const figures = [...container.querySelectorAll("img")];
    expect(figures).toHaveLength(4);
    for (const figure of figures) {
      const src = figure.getAttribute("src") ?? "";
      expect(src.startsWith("/guidance/")).toBe(true);
      // Evidence is served from the authenticated scan routes. A plate pointing there
      // would mean a drawing was being presented as a photograph of a package.
      expect(src).not.toContain("/api/");
      expect(src).not.toContain("/scans/");
    }
  });

  it("never uploads anything", async () => {
    // The panel has no network surface at all: no fetch, no form, no file input.
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { container } = render(<CaptureGuidance />);
    await userEvent.click(screen.getByRole("button"));

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(container.querySelector("input[type=file]")).toBeNull();
    expect(container.querySelector("form")).toBeNull();
    fetchSpy.mockRestore();
  });

  it("tells the officer the plates are not kept with a scan", async () => {
    render(<CaptureGuidance />);
    await userEvent.click(screen.getByRole("button"));
    expect(
      screen.getByText(/not photographed, uploaded or kept with any scan/),
    ).toBeInTheDocument();
  });

  it("collapses again", async () => {
    render(<CaptureGuidance />);
    const toggle = screen.getByRole("button");
    await userEvent.click(toggle);
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
