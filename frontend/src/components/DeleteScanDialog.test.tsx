/*
  The delete confirmation.

  What matters: the officer is told delete means "withheld from the repository, record
  and evidence kept" before anything happens; the reason is optional and passed through
  trimmed (or omitted when blank); a server refusal is shown in place; and the
  case-open override note appears only when a case is actually open.
*/

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DeleteScanDialog } from "./DeleteScanDialog";

function mount(props: Partial<Parameters<typeof DeleteScanDialog>[0]> = {}) {
  const onClose = vi.fn();
  const onConfirm = vi.fn().mockResolvedValue(undefined);
  render(
    <DeleteScanDialog
      productName="Roasted Chana Masala"
      caseOpen={false}
      onClose={onClose}
      onConfirm={onConfirm}
      {...props}
    />,
  );
  return { onClose, onConfirm };
}

describe("the delete confirmation", () => {
  it("spells out that the record and evidence are kept", () => {
    mount();
    expect(screen.getByText(/Delete the scan of Roasted Chana Masala\?/)).toBeInTheDocument();
    expect(screen.getByText(/stay in the database/)).toBeInTheDocument();
    expect(screen.getByText(/audit trail/)).toBeInTheDocument();
  });

  it("passes a trimmed reason through on confirm", async () => {
    const { onConfirm } = mount();
    await userEvent.type(screen.getByLabelText(/Reason/), "  duplicate capture  ");
    await userEvent.click(screen.getByRole("button", { name: "Delete scan" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("duplicate capture"));
  });

  it("omits the reason entirely when it is left blank", async () => {
    const { onConfirm } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Delete scan" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith(undefined));
  });

  it("caps the reason at 64 characters", () => {
    mount();
    expect(screen.getByLabelText(/Reason/)).toHaveAttribute("maxlength", "64");
  });

  it("cancels without deleting", async () => {
    const { onClose, onConfirm } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("does not mention case-open when no case is open", () => {
    mount({ caseOpen: false });
    expect(screen.queryByText(/A case is marked open/)).not.toBeInTheDocument();
  });

  it("shows the case-open override note when a case is open", () => {
    mount({ caseOpen: true });
    expect(screen.getByText(/A case is marked open on this scan/)).toBeInTheDocument();
    expect(screen.getByText(/scheduled auto-deletion job never would/)).toBeInTheDocument();
  });

  it("surfaces a server refusal in place instead of throwing", async () => {
    const { ApiError } = await import("../api/client");
    const onConfirm = vi
      .fn()
      .mockRejectedValue(new ApiError(403, "You can only delete scans you filed."));
    render(
      <DeleteScanDialog
        productName="X"
        caseOpen={false}
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete scan" }));
    await waitFor(() =>
      expect(screen.getByText("You can only delete scans you filed.")).toBeInTheDocument(),
    );
  });
});
