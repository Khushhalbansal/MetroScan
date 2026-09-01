/*
  The Measure carries a legal claim, so these are not rendering tests — they are checks
  that the component cannot state something the data does not support.
*/

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Measure, measureFromDetail } from "./Measure";

describe("the Measure", () => {
  it("states the shortfall when the type is below the limit", () => {
    render(<Measure measuredMm={1.4} requiredMm={2.0} animate={false} />);
    expect(screen.getByText("1.40 mm")).toBeInTheDocument();
    expect(screen.getByText(/short by 0.60 mm/)).toBeInTheDocument();
  });

  it("does not claim a shortfall when the type meets the limit", () => {
    render(<Measure measuredMm={2.4} requiredMm={2.0} animate={false} />);
    expect(screen.queryByText(/short by/)).not.toBeInTheDocument();
  });

  it("says nothing was measured rather than showing a zero", () => {
    // No scale in frame. A bar at zero would read as "measured 0 mm", which is a
    // finding nobody made — the requirement is shown, the reading is not.
    render(<Measure measuredMm={null} requiredMm={2.0} animate={false} />);
    expect(screen.getByText("not measurable")).toBeInTheDocument();
    expect(screen.getByText("2.0 mm")).toBeInTheDocument();
    expect(screen.queryByText(/short by/)).not.toBeInTheDocument();
  });

  it("describes itself to a screen reader in millimetres", () => {
    render(<Measure measuredMm={1.4} requiredMm={2.0} animate={false} />);
    expect(
      screen.getByRole("img", { name: /Measured 1.4 millimetres against a 2 millimetre/ }),
    ).toBeInTheDocument();
  });

  it("keeps the limit on the scale rather than at its very end", () => {
    // A 0.4 mm reading on a rule that stopped at 1 mm would look like a near miss.
    const { container } = render(
      <Measure measuredMm={0.4} requiredMm={1.0} animate={false} />,
    );
    const numerals = [...container.querySelectorAll(".measure__numeral")].map(
      (n) => n.textContent,
    );
    expect(numerals).toContain("6");
  });
});

describe("measureFromDetail", () => {
  it("builds a measure from a geometry finding", () => {
    expect(measureFromDetail({ measured_mm: 1, required_mm: 2, pdp_area_cm2: 155 })).toEqual({
      measuredMm: 1,
      requiredMm: 2,
      panelAreaCm2: 155,
    });
  });

  it("returns nothing for a finding that is not a measurement", () => {
    // Rendering a ruler for a presence check would be inventing a reading.
    expect(measureFromDetail({ missing: ["consumer_care_email"] })).toBeNull();
    expect(measureFromDetail({})).toBeNull();
  });

  it("treats an unparseable measurement as unmeasured, not as zero", () => {
    expect(measureFromDetail({ required_mm: 2, measured_mm: "?" })).toEqual({
      measuredMm: null,
      requiredMm: 2,
      panelAreaCm2: null,
    });
  });
});
