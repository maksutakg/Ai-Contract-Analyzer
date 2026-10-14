import { useState, type ReactNode } from "react";

import { SEARCHED_SOURCES, SEVERITY_LABEL, SEVERITY_ORDER, categoryLabel, limitationLabel } from "../labels";
import type { Clause, ContractReport, RiskFinding, Severity, YargiDecision } from "../types";

const EXCERPT_PREVIEW_CHARS = 320;

interface Props {
  fileName: string;
  report: ContractReport;
}

export function Report({ fileName, report }: Props) {
  const clauseIds = new Set(report.clauses.map((clause) => clause.id));
  const findingsByClause = groupBy(
    report.findings.filter((finding) => finding.clause_id && clauseIds.has(finding.clause_id)),
    (finding) => finding.clause_id!,
  );
  const unplaced = report.findings.filter(
    (finding) => !finding.clause_id || !clauseIds.has(finding.clause_id),
  );
  const decisionsByFinding = groupBy(
    report.related_decisions.filter((decision) => decision.finding_id),
    (decision) => decision.finding_id!,
  );

  return (
    <div className="report">
      <aside className="verdict" aria-label="Sonuç">
        <p className="verdict-file">{fileName}</p>
        <p className={`verdict-level tone-${report.risk_level}`}>
          {SEVERITY_LABEL[report.risk_level]} risk
        </p>
        <p className="verdict-score">Risk puanı {report.risk_score} / 100</p>

        <h2 className="verdict-heading">Riskler</h2>
        {report.findings.length === 0 ? (
          <p className="muted">Bu sözleşmede risk tespit edilmedi.</p>
        ) : (
          <ul className="verdict-findings">
            {sortBySeverity(report.findings).map((finding) => (
              <li key={finding.id}>
                <a href={`#finding-${finding.id}`}>
                  <SeverityMark severity={finding.severity} />
                  {categoryLabel(finding.category)}
                </a>
              </li>
            ))}
          </ul>
        )}

        <h2 className="verdict-heading">Analizi yapanlar</h2>
        <EngineStatus report={report} />

        {report.limitations.length > 0 && (
          <>
            <h2 className="verdict-heading">Bu raporun sınırları</h2>
            <ul className="limitations">
              {report.limitations.map((limitation) => (
                <li key={limitation}>{limitationLabel(limitation)}</li>
              ))}
            </ul>
          </>
        )}

        <p className="caution">
          Bu rapor bir ön incelemedir. Risk değerlendirmeleri, madde atıfları ve emsal kararlar bir
          hukukçu tarafından kontrol edilmelidir.
        </p>
      </aside>

      <div className="reading">
        {!report.yargi_source.startsWith("fake") && <SourceSeals decisions={report.related_decisions} />}

        <section className="summary" aria-labelledby="summary-heading">
          <h2 id="summary-heading">Özet</h2>
          <SummaryText text={report.contract_summary} />
        </section>

        <section aria-labelledby="document-heading">
          <h2 id="document-heading">Sözleşme ve notlar</h2>
          <div className="document">
            {report.clauses.map((clause) => (
              <ClauseRow
                key={clause.id}
                clause={clause}
                findings={findingsByClause.get(clause.id) ?? []}
                decisionsByFinding={decisionsByFinding}
              />
            ))}
          </div>
        </section>

        {unplaced.length > 0 && (
          <section aria-labelledby="general-heading">
            <h2 id="general-heading">Belirli bir maddeye bağlanamayan riskler</h2>
            <div className="margin-standalone">
              {unplaced.map((finding) => (
                <Note key={finding.id} finding={finding} decisions={decisionsByFinding.get(finding.id) ?? []} />
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function ClauseRow({
  clause,
  findings,
  decisionsByFinding,
}: {
  clause: Clause;
  findings: RiskFinding[];
  decisionsByFinding: Map<string, YargiDecision[]>;
}) {
  const worst = sortBySeverity(findings)[0]?.severity;
  return (
    <article id={`clause-${clause.id}`} className={`clause-row${worst ? ` flagged tone-${worst}` : ""}`}>
      <div className="clause">
        {clause.title && <h3 className="clause-title">{clause.title}</h3>}
        <p className="clause-text">{clause.text}</p>
      </div>
      <div className="margin">
        {sortBySeverity(findings).map((finding) => (
          <Note key={finding.id} finding={finding} decisions={decisionsByFinding.get(finding.id) ?? []} />
        ))}
      </div>
    </article>
  );
}

function Note({ finding, decisions }: { finding: RiskFinding; decisions: YargiDecision[] }) {
  return (
    <div id={`finding-${finding.id}`} className={`note tone-${finding.severity}`}>
      <p className="note-head">
        <SeverityMark severity={finding.severity} />
        <span className="note-category">{categoryLabel(finding.category)}</span>
      </p>
      <p className="note-text">{finding.explanation}</p>
      <p className="note-advice">
        <span className="note-advice-label">Öneri: </span>
        {finding.recommendation}
      </p>
      {decisions.map((decision) => (
        <Precedent key={`${decision.source}-${decision.title}`} decision={decision} />
      ))}
    </div>
  );
}

function Precedent({ decision }: { decision: YargiDecision }) {
  const [expanded, setExpanded] = useState(false);
  const excerpt = decision.excerpt ?? "";
  const long = excerpt.length > EXCERPT_PREVIEW_CHARS;
  const shown = expanded || !long ? excerpt : `${excerpt.slice(0, EXCERPT_PREVIEW_CHARS).trimEnd()}…`;

  return (
    <figure className="precedent">
      <figcaption>
        <span className="precedent-label">{decision.court ? `Dayanak: ${decision.court} kararı` : "Dayanak karar"}</span>
        <span className="precedent-title">{decision.title}</span>
      </figcaption>
      {excerpt && <blockquote className="precedent-excerpt">{shown}</blockquote>}
      <p className="precedent-actions">
        {long && (
          <button type="button" className="link-button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
            {expanded ? "Alıntıyı kısalt" : "Alıntının tamamını göster"}
          </button>
        )}
        {decision.url && (
          <a href={decision.url} target="_blank" rel="noopener noreferrer">
            Kararın kaynağını aç
          </a>
        )}
      </p>
    </figure>
  );
}

function SourceSeals({ decisions }: { decisions: YargiDecision[] }) {
  const counts = new Map<string, number>();
  for (const decision of decisions) {
    const court = decision.court ?? "Diğer";
    counts.set(court, (counts.get(court) ?? 0) + 1);
  }
  return (
    <section className="seals" aria-labelledby="seals-heading">
      <h2 id="seals-heading">Bu rapordaki emsal kararlar</h2>
      {counts.size > 0 ? (
        <ul className="seal-list">
          {[...counts].map(([court, count]) => (
            <li key={court} className="seal">
              <span className="seal-count">{count}</span>
              <span className="seal-name">{court}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Bu analizde risklerle yeterince ilgili emsal karar bulunamadı.</p>
      )}
      <p className="seals-note">
        Yargı MCP üzerinden canlı aranan kaynaklar: {SEARCHED_SOURCES.join(", ")}.
      </p>
    </section>
  );
}

function EngineStatus({ report }: { report: ContractReport }) {
  const rules = report.llm_engine.startsWith("rules");
  const fake = report.yargi_source.startsWith("fake");
  return (
    <dl className="engines">
      <div className={rules ? "engine is-degraded" : "engine"}>
        <dt>Risk değerlendirmesi</dt>
        <dd>{rules ? "Kural tabanlı (yapay zekâ kullanılmadı)" : `Yapay zekâ, ${report.llm_engine}`}</dd>
      </div>
      <div className={fake ? "engine is-degraded" : "engine"}>
        <dt>Emsal kararlar</dt>
        <dd>{fake ? "Örnek veri (gerçek arama yapılmadı)" : "Yargı MCP, canlı arama"}</dd>
      </div>
    </dl>
  );
}

function SeverityMark({ severity }: { severity: Severity }) {
  return <span className={`severity tone-${severity}`}>{SEVERITY_LABEL[severity]}</span>;
}

// Gemini summaries use a little Markdown (bullets, **bold**); render it without innerHTML.
function SummaryText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let items: string[] = [];
  const flush = () => {
    if (items.length) blocks.push(<ul key={blocks.length}>{items.map((item, i) => <li key={i}>{inline(item)}</li>)}</ul>);
    items = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^[*-]\s+(.*)$/);
    if (bullet) {
      items.push(bullet[1]);
      continue;
    }
    flush();
    if (line) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
  }
  flush();
  return <div className="summary-text">{blocks}</div>;
}

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  );
}

function sortBySeverity(findings: RiskFinding[]): RiskFinding[] {
  return [...findings].sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity));
}

function groupBy<T>(items: T[], key: (item: T) => string): Map<string, T[]> {
  const groups = new Map<string, T[]>();
  for (const item of items) groups.set(key(item), [...(groups.get(key(item)) ?? []), item]);
  return groups;
}
