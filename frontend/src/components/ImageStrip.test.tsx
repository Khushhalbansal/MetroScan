/*
  The image strip.

  The behaviour that matters here is not that a button posts — it is that the officer is
  told, before they act, that changing a photograph re-runs the whole check, and that
  the last photograph cannot be removed at all.
*/

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { ScanImage } from "../api/types";
import { ImageStrip } from "./ImageStrip";

function image(over: Partial<ScanImage> = {}): ScanImage {
  return {
    image_id: "img-1",
    kind: "FRONT",
    filename: "front.png",
    width: 1224,
    height: 2136,
    blocks_read: 15,
    ...over,
  };
}

function mount(images: ScanImage[], props: Partial<Parameters<typeof ImageStrip>[0]> = {}) {
  const onScan = vi.fn();
  const onError = vi.fn();
  const onBusy = vi.fn();
  render(
    <ImageStrip
      scanId="scan-1"
      images={images}
      revision={1}
      busy={false}
      onBusy={onBusy}
      onScan={onScan}
      onError={onError}
      {...props}
    />,
  );
  return { onScan, onError, onBusy };
}

afterEach(() => vi.restoreAllMocks());

describe("the image strip", () => {
  it("says up front that changing a photograph re-runs the check", () => {
    mount([image()]);
    expect(
      screen.getByText(/Changing these re-runs the compliance check/),
    ).toBeInTheDocument();
  });

  it("will not let the last photograph be removed", () => {
    mount([image()]);
    const remove = screen.getByRole("button", { name: "Remove" });
    expect(remove).toBeDisabled();
    expect(remove).toHaveAccessibleName("Remove");
    expect(remove.getAttribute("title")).toMatch(/at least one photograph/);
  });

  it("confirms a removal with the consequence stated, not a bare prompt", async () => {
    mount([image({ image_id: "a" }), image({ image_id: "b", kind: "SIDE" })]);
    await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);

    // "the one that remains", not "the 1 that remain".
    expect(
      screen.getByText(/re-judge the pack from the one that remains/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove and re-check" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep it" })).toBeInTheDocument();
  });

  it("re-runs the check on removal and hands back the re-judged scan", async () => {
    const rejudged = { scan_id: "scan-1", revision: 2 } as never;
    const remove = vi.spyOn(api, "removeImage").mockResolvedValue(rejudged);
    const { onScan, onBusy } = mount([
      image({ image_id: "a" }),
      image({ image_id: "b", kind: "SIDE" }),
    ]);

    await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Remove and re-check" }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith("scan-1", "a"));
    expect(onBusy).toHaveBeenCalledWith(expect.stringMatching(/re-running the check/i));
    expect(onScan).toHaveBeenCalledWith(rejudged);
  });

  it("surfaces a refusal in place rather than throwing it up the page", async () => {
    const { ApiError } = await import("../api/client");
    vi.spyOn(api, "addImage").mockRejectedValue(
      new ApiError(409, "This scan already holds 8 photographs."),
    );
    const { onError } = mount([image()]);

    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    await userEvent.upload(input, new File(["x"], "extra.png", { type: "image/png" }));

    await waitFor(() =>
      expect(onError).toHaveBeenCalledWith("This scan already holds 8 photographs."),
    );
  });

  it("shows the reading number once the photographs have been edited", () => {
    mount([image()], { revision: 3 });
    expect(screen.getByText(/reading 3/)).toBeInTheDocument();
  });

  it("disables every control while a re-run is in flight", () => {
    mount([image({ image_id: "a" }), image({ image_id: "b" })], { busy: true });
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });
});
