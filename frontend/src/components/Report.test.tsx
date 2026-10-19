// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import realReport from "../fixtures/report.json";
import type { ContractReport } from "../types";
import { Report } from "./Report";

// A real /api/v1/contracts/analyze response; typing it here is the drift check against models.py.
const report: ContractReport = realReport as ContractReport;

afterEach(cleanup);

describe("Report", () => {
  it("places each finding beside its clause together with its precedent", () => {
    render(<Report fileName="hizmet_sozlesmesi.docx" report={report} />);

    const penalty = report.findings.find((finding) => finding.category === "penalty_clause")!;
    const row = document.getElementById(`clause-${penalty.clause_id}`)!;
    const decision = report.related_decisions.find((d) => d.finding_id === penalty.id)!;

    expect(within(row).getByText(penalty.explanation)).toBeTruthy();
    expect(within(row).getByText(decision.title)).toBeTruthy();
  });

  it("shows which engines ran and the limitations", () => {
    render(<Report fileName="x.docx" report={report} />);

    expect(screen.getByText(`AI model ${report.llm_engine}`)).toBeTruthy();
    expect(screen.getByText("Live search through Yargı MCP")).toBeTruthy();
    expect(screen.getByText("Precedent search covered only the 4 most severe of 5 findings.")).toBeTruthy();
  });

  it("flags rule-based analysis and sample precedents", () => {
    render(
      <Report
        fileName="x.docx"
        report={{ ...report, llm_engine: "rules (GEMINI_API_KEY is not set)", yargi_source: "fake (USE_REMOTE_YARGI is false)" }}
      />,
    );

    expect(screen.getByText("Rule-based checks (no AI model was used)")).toBeTruthy();
    expect(screen.getByText("Sample data (no live search was made)")).toBeTruthy();
  });

  it("keeps findings without a matching clause and survives no precedents", () => {
    const orphan = { ...report.findings[0], id: "finding-x", clause_id: null, explanation: "Risk without a clause" };
    render(<Report fileName="x.docx" report={{ ...report, findings: [orphan], related_decisions: [] }} />);

    const section = screen.getByRole("heading", { name: "Risks not tied to a single clause" }).parentElement!;
    expect(within(section).getByText("Risk without a clause")).toBeTruthy();
  });

  it("names the issuing institution on each precedent and tallies them", () => {
    render(<Report fileName="x.docx" report={report} />);

    const tally = screen.getByRole("heading", { name: "Case law cited" }).nextElementSibling!;
    expect(within(tally as HTMLElement).getByText("Court of Cassation (Yargıtay)").nextElementSibling?.textContent).toBe("3");
    expect(within(tally as HTMLElement).getByText("First-instance courts").nextElementSibling?.textContent).toBe("1");
    expect(document.querySelectorAll(".precedent-label")).toHaveLength(4);
  });
});
