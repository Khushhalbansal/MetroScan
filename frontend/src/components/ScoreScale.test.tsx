/*
  The score is secondary to the verdict and meaningless without its coverage. These
  check that the component cannot be used to say otherwise.
*/

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScoreScale } from "./ScoreScale";
import { StatusMark, VerdictMark } from "./StatusMark";

describe("the score reading", () => {
  it("states that nothing was scored rather than showing a zero", () => {
    // A scan that read nothing must not report 0/100: a zero is a judgement about the
    // product, and "we could not assess this" is not a judgement about the product.
    render(<ScoreScale score={null} decided={0} applicable={14} />);
    expect(screen.getByText(/Not scored/)).toBeInTheDocument();
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
  });

  it("always shows the coverage beside the number", () => {
    // 100 over two decided rules is not the same claim as 100 over twenty.
    render(<ScoreScale score={100} decided={2} applicable={22} />);
    expect(screen.getByText("100.0")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("22")).toBeInTheDocument();
    expect(screen.getByText(/applicable rules decided/)).toBeInTheDocument();
  });

  it("shows the coverage even when nothing was decided", () => {
    render(<ScoreScale score={null} decided={0} applicable={14} />);
    expect(screen.getByText(/applicable rules decided/)).toBeInTheDocument();
  });
});

describe("status marks", () => {
  it.each([
    ["PASS", "Pass"],
    ["FAIL", "Fail"],
    ["NEEDS_REVIEW", "Needs review"],
    ["NA", "Not applicable"],
  ] as const)("carries %s as a word, not only a colour", (status, word) => {
    // An inspection file gets photocopied and printed in greyscale, and a status that
    // is only a colour survives neither.
    render(<StatusMark status={status} />);
    expect(screen.getByText(word)).toBeInTheDocument();
  });

  it("never presents an open question as a settled one", () => {
    render(<StatusMark status="NEEDS_REVIEW" />);
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.queryByText("Pass")).not.toBeInTheDocument();
    expect(screen.queryByText("Fail")).not.toBeInTheDocument();
  });

  it.each([
    ["COMPLIANT", "Compliant"],
    ["NON_COMPLIANT", "Non-compliant"],
    ["INCONCLUSIVE", "Inconclusive"],
  ] as const)("spells the %s verdict out", (verdict, word) => {
    render(<VerdictMark verdict={verdict} />);
    expect(screen.getByText(word)).toBeInTheDocument();
  });
});
