/*
  The retention prompt.

  What matters here is not that a button posts — it is that "no case is open" is
  confirmed with its consequence spelled out before it takes effect, that "yes" needs
  no confirmation because it only ever retains, and that the answer already on file is
  not offered as a fresh choice.
*/

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { Retention } from "../api/types";
import { RetentionPanel } from "./RetentionPanel";

function retention(over: Partial<Retention> = {}): Retention {
  return {
    case_open: null,
    decided_at: null,
    decided_by_id: null,
    eligible_for_deletion: false,
    eligible_on: null,
    summary: "Not yet reviewed for retention.",
    ...over,
  };
}

function mount(over: Partial<Retention> = {}) {
  const onScan = vi.fn();
  render(<RetentionPanel scanId="scan-1" retention={retention(over)} onScan={onScan} />);
  return { onScan };
}

afterEach(() => vi.restoreAllMocks());

describe("the retention prompt", () => {
  it("asks the one question that governs auto-deletion", () => {
    mount();
    expect(screen.getByText("Is a case still open on this scan?")).toBeInTheDocument();
    expect(screen.getByText(/Not yet reviewed/)).toBeInTheDocument();
  });

  it("records 'yes' immediately, with no confirmation step", async () => {
    const set = vi.spyOn(api, "setRetention").mockResolvedValue({ scan_id: "scan-1" } as never);
    const { onScan } = mount();

    await userEvent.click(screen.getByRole("button", { name: "Yes — keep it" }));

    await waitFor(() => expect(set).toHaveBeenCalledWith("scan-1", true));
    expect(onScan).toHaveBeenCalled();
  });

  it("confirms 'no' with the deletion consequence stated before it posts", async () => {
    const set = vi.spyOn(api, "setRetention").mockResolvedValue({ scan_id: "scan-1" } as never);
    mount();

    await userEvent.click(screen.getByRole("button", { name: "No — case closed" }));
    expect(set).not.toHaveBeenCalled();
    expect(
      screen.getByText(/eligible for automatic deletion once the retention window passes/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "No case is open" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith("scan-1", false));
  });

  it("does not offer the answer already on file", () => {
    mount({ case_open: true, decided_at: "2026-08-01T00:00:00Z", decided_by_id: "u1" });
    expect(screen.getByRole("button", { name: "Yes — keep it" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "No — case closed" })).toBeEnabled();
  });

  it("shows when a closed scan becomes eligible, and when it was answered", () => {
    mount({
      case_open: false,
      decided_at: "2026-08-01T00:00:00Z",
      decided_by_id: "u1",
      eligible_on: "2026-08-31T00:00:00Z",
      summary:
        "No case is open. Eligible for auto-deletion on 2026-08-31 — 30 days after the decision was recorded.",
    });
    // The eligible date rides in the summary the server composes.
    expect(screen.getByText(/Eligible for auto-deletion on 2026-08-31/)).toBeInTheDocument();
    // The panel adds when the answer was given.
    expect(screen.getByText(/Answered/)).toHaveTextContent("2026-08-01");
  });

  it("surfaces a refusal in place rather than throwing it up the page", async () => {
    const { ApiError } = await import("../api/client");
    vi.spyOn(api, "setRetention").mockRejectedValue(new ApiError(403, "Not your scan to decide."));
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Yes — keep it" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Not your scan to decide."),
    );
  });
});
