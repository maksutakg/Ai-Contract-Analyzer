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

  it("shows which engines ran and translates limitations", () => {
    render(<Report fileName="x.docx" report={report} />);

    expect(screen.getByText(`Yapay zekâ, ${report.llm_engine}`)).toBeTruthy();
    expect(screen.getByText("Yargı MCP, canlı arama")).toBeTruthy();
    expect(screen.getByText("Emsal karar yalnız en ciddi 4 risk için arandı (toplam 5).")).toBeTruthy();
  });

  it("flags rule-based analysis and sample precedents", () => {
    render(
      <Report
        fileName="x.docx"
        report={{ ...report, llm_engine: "rules (GEMINI_API_KEY is not set)", yargi_source: "fake (USE_REMOTE_YARGI is false)" }}
      />,
    );

    expect(screen.getByText("Kural tabanlı (yapay zekâ kullanılmadı)")).toBeTruthy();
    expect(screen.getByText("Örnek veri (gerçek arama yapılmadı)")).toBeTruthy();
  });

  it("keeps findings without a matching clause and survives no precedents", () => {
    const orphan = { ...report.findings[0], id: "finding-x", clause_id: null, explanation: "Maddeye bağlanamayan risk" };
    render(<Report fileName="x.docx" report={{ ...report, findings: [orphan], related_decisions: [] }} />);

    const section = screen.getByRole("heading", { name: "Belirli bir maddeye bağlanamayan riskler" }).parentElement!;
    expect(within(section).getByText("Maddeye bağlanamayan risk")).toBeTruthy();
  });

  it("names the issuing institution and stamps a seal per institution", () => {
    render(<Report fileName="x.docx" report={report} />);

    expect(screen.getAllByText("Dayanak: Yargıtay kararı")).toHaveLength(3);
    const seals = screen.getByRole("heading", { name: "Bu rapordaki emsal kararlar" }).parentElement!;
    expect(within(seals).getByText("Yargıtay").previousSibling?.textContent).toBe("3");
    expect(within(seals).getByText("Yerel mahkeme").previousSibling?.textContent).toBe("1");
  });
});
