import { useState, type ReactNode } from "react";

import { SEVERITY_LABEL, SEVERITY_ORDER, categoryLabel } from "../labels";
import { courtName } from "../sources";
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
      <aside className="verdict" aria-label="Result">
        <p className="verdict-file">{fileName}</p>
        <p className={`verdict-level tone-${report.risk_level}`}>
          {SEVERITY_LABEL[report.risk_level]} risk
        </p>
        <p className="verdict-score">Risk score {report.risk_score} of 100</p>

        <h2 className="verdict-heading">Risks</h2>
        {report.findings.length === 0 ? (
          <p className="muted">No risks were found in this contract.</p>
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

        {!report.yargi_source.startsWith("fake") && <CaseLawTally decisions={report.related_decisions} />}

        <h2 className="verdict-heading">How this report was made</h2>
        <EngineStatus report={report} />

        {report.limitations.length > 0 && (
          <>
            <h2 className="verdict-heading">Limits of this report</h2>
            <ul className="limitations">
              {report.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </>
        )}

        <p className="caution">
          This is a first review, not legal advice. A lawyer should check the risk assessments, any
          statutory references and the decisions cited.
        </p>
      </aside>

      <div className="reading">
        <section className="summary" aria-labelledby="summary-heading">
          <h2 id="summary-heading">Summary</h2>
          <SummaryText text={report.contract_summary} />
        </section>

        <section aria-labelledby="document-heading">
          <h2 id="document-heading">Contract and notes</h2>
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
            <h2 id="general-heading">Risks not tied to a single clause</h2>
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
        <span className="note-advice-label">Recommendation: </span>
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
        <span className="precedent-label">{courtName(decision.court)}</span>
        <span className="precedent-title">{decision.title}</span>
      </figcaption>
      {excerpt && <blockquote className="precedent-excerpt">{shown}</blockquote>}
      <p className="precedent-actions">
        {long && (
          <button type="button" className="link-button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
            {expanded ? "Show less" : "Show the full excerpt"}
          </button>
        )}
        {decision.url && (
          <a href={decision.url} target="_blank" rel="noopener noreferrer">
            Open the decision
          </a>
        )}
      </p>
    </figure>
  );
}

function CaseLawTally({ decisions }: { decisions: YargiDecision[] }) {
  const counts = new Map<string, number>();
  for (const decision of decisions) {
    const name = courtName(decision.court);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return (
    <>
      <h2 className="verdict-heading">Case law cited</h2>
      {counts.size > 0 ? (
        <dl className="tally">
          {[...counts].map(([name, count]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{count}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="muted">No decision was close enough to these risks to cite.</p>
      )}
    </>
  );
}

function EngineStatus({ report }: { report: ContractReport }) {
  const rules = report.llm_engine.startsWith("rules");
  const fake = report.yargi_source.startsWith("fake");
  return (
    <dl className="engines">
      <div className={rules ? "engine is-degraded" : "engine"}>
        <dt>Risk assessment</dt>
        <dd>{rules ? "Rule-based checks (no AI model was used)" : `AI model ${report.llm_engine}`}</dd>
      </div>
      <div className={fake ? "engine is-degraded" : "engine"}>
        <dt>Case law</dt>
        <dd>{fake ? "Sample data (no live search was made)" : "Live search through Yargı MCP"}</dd>
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
