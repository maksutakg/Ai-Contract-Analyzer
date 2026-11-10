"""Prompt builders for the Gemini/Gemma analyzer.

Gemma models are not assumed to support JSON mode, so every structured prompt
asks for plain JSON text that is parsed tolerantly.
"""

from .categories import allowed_categories_text
from .contract_types import role_label, roles_for
from .facts import FACTS_BY_TYPE
from .missing_clauses import ChecklistTopic
from .models import Clause, RiskFinding, YargiDecision

GRADER_EXCERPT_CHARS = 900


def summary_prompt(text: str, contract_type: str | None) -> str:
    prompt = (
        "Summarize this contract in Turkish for a legal reviewer. "
        "Use 120-180 words and at most 5 bullets. "
        "Identify only the contract purpose, parties, duration, price, payment, IP, termination, "
        "and dispute resolution if present. "
        "Do not include risk analysis, recommendations, case law, or repeated findings.\n\n"
    )
    if contract_type:
        prompt += f"Contract type: {contract_type}\n\n"
    return prompt + text


def summary_part_prompt(text: str, contract_type: str | None, part: int, total: int) -> str:
    prompt = (
        f"This is part {part} of {total} of a contract. Summarize this part in Turkish "
        "in at most 80 words for a legal reviewer. Keep only facts about purpose, parties, "
        "duration, price, payment, IP, termination and dispute resolution that appear in this part. "
        "Do not include risk analysis, recommendations, or case law.\n\n"
    )
    if contract_type:
        prompt += f"Contract type: {contract_type}\n\n"
    return prompt + text


def summary_combine_prompt(partial_summaries: list[str], contract_type: str | None) -> str:
    joined = "\n\n".join(
        f"Part {index}:\n{summary}" for index, summary in enumerate(partial_summaries, start=1)
    )
    prompt = (
        "The following are summaries of consecutive parts of one contract. Combine them into one "
        "summary in Turkish for a legal reviewer. Use 120-180 words and at most 5 bullets. "
        "Identify only the contract purpose, parties, duration, price, payment, IP, termination, "
        "and dispute resolution if present. Remove repetition. "
        "Do not include risk analysis, recommendations, case law, or repeated findings.\n\n"
    )
    if contract_type:
        prompt += f"Contract type: {contract_type}\n\n"
    return prompt + joined


def _party_block(contract_type: str | None, party: str | None) -> str:
    """Roles the model may use for disadvantaged_party, and whose side to take."""
    roles = roles_for(contract_type)
    if not roles:
        return (
            "disadvantaged_party must be \"both\" or the role of the party the clause works against "
            "in a few words (e.g. \"kiracı\").\n"
        )
    allowed = ", ".join(f"{role.id} ({role.label})" for role in roles)
    text = (
        f"disadvantaged_party must be one of: {allowed}, both. "
        "It names the side the clause works against.\n"
    )
    user = next((role for role in roles if role.id == party), None)
    if user is not None:
        text += (
            f"The user is the {user.id} ({user.label}). Protect the user's interests: still report "
            "material risks for the other side with the correct disadvantaged_party, but write every "
            f"recommendation as advice to the {user.label} (what they should ask for or change).\n"
        )
    return text


def classify_prompt(
    clause_payload: str,
    contract_type: str | None,
    max_findings: int,
    batch: int,
    total_batches: int,
    party: str | None = None,
) -> str:
    prompt = (
        "You are reviewing a Turkish contract for legal and procurement risk. "
        "Return ONLY a JSON array. Do not wrap it in markdown. Each item must have: "
        "category, severity, explanation, recommendation, confidence, clause_id, disadvantaged_party. "
        f"Return at most {max_findings} findings. Prefer material legal risks only. "
        "Return [] if these clauses contain no material risk. "
        "Keep explanation under 240 characters and recommendation under 240 characters. "
        "Write the explanation and recommendation fields in Turkish. "
        f"category must be one of {allowed_categories_text()}. "
        "severity must be one of low, medium, high, critical. confidence must be 0..1. "
        "clause_id must be one of the clause ids given below. "
        "Do not invent law numbers, article numbers, court names, or case numbers. "
        "Mention specific statutes or cases only if they appear in the clause text. "
        "Focus on enforceability, statutory limits, one-sided rights, privacy, payment, "
        "termination, deposit, eviction undertaking, rent increase, jurisdiction, data protection, "
        "intellectual property, force majeure, late payment interest, "
        "penalty clauses, liability and dispute resolution risks.\n"
    )
    prompt += _party_block(contract_type, party) + "\n"
    if contract_type:
        prompt += f"Contract type: {contract_type}\n\n"
    if total_batches > 1:
        prompt += f"These clauses are batch {batch} of {total_batches} of the contract.\n\n"
    return prompt + f"Clauses:\n{clause_payload}"


def clause_line(clause_id: str, text: str) -> str:
    return f"{clause_id}: {text}"


def clause_lines(clause: Clause, budget: int) -> list[str]:
    """Render a clause as one line, or several same-id lines if it exceeds the budget."""
    line = clause_line(clause.id, clause.text)
    if len(line) <= budget:
        return [line]
    step = max(1, budget - len(clause.id) - 20)
    lines: list[str] = []
    for start in range(0, len(clause.text), step):
        piece = clause.text[start : start + step]
        lines.append(clause_line(clause.id, f"(continued) {piece}" if start else piece))
    return lines


def legal_query_prompt(finding: RiskFinding) -> str:
    return (
        "You are an expert Turkish legal researcher. "
        "Based on the following contract risk finding, generate a single optimized search query "
        "to find relevant Turkish Court of Cassation (Yargıtay), Council of State (Danıştay), "
        "or KVKK decisions on a legal database.\n\n"
        "Follow these constraints:\n"
        "1. The query must be in Turkish.\n"
        "2. Use exact match double quotes for key legal concepts (e.g. \"cezai şart\", \"veri işleyen\").\n"
        "3. Keep the query under 10 words.\n"
        "4. Return ONLY the search query text, no explanation, no quotes around the whole query.\n\n"
        f"Risk Category: {finding.category}\n"
        f"Explanation: {finding.explanation}\n"
        f"Recommendation: {finding.recommendation}\n"
    )


def rewrite_query_prompt(finding: RiskFinding, previous_queries: list[str], feedback: str) -> str:
    tried = "\n".join(f"- {query}" for query in previous_queries)
    return (
        "You are an expert Turkish legal researcher searching a Turkish court decision database "
        "(Yargıtay, Danıştay, KVKK). Previous search queries for the contract risk below did not "
        "return a relevant decision.\n\n"
        f"Risk Category: {finding.category}\n"
        f"Explanation: {finding.explanation}\n\n"
        f"Queries already tried:\n{tried}\n\n"
        f"Why they failed:\n{feedback}\n\n"
        "Write ONE new Turkish search query that is different from all queries already tried. "
        "Usually broaden it: drop over-specific or quoted phrases, keep at most one quoted core "
        "legal concept, prefer statutory or doctrinal terms courts actually use. "
        "Keep it under 8 words. Return ONLY the query text, no explanation."
    )


def grade_prompt(finding: RiskFinding, decisions: list[YargiDecision]) -> str:
    candidates = "\n\n".join(
        f"[{index}] {decision.title}\n{(decision.excerpt or '')[:GRADER_EXCERPT_CHARS]}"
        for index, decision in enumerate(decisions, start=1)
    )
    return (
        "You are grading Turkish court decisions for a contract risk finding (Corrective RAG). "
        "For EACH candidate decision decide whether it helps a lawyer assess this specific risk:\n"
        "- relevant: the decision addresses the same legal issue.\n"
        "- ambiguous: related area but a different issue, or too little text to be sure.\n"
        "- irrelevant: a different legal issue.\n\n"
        f"Risk Category: {finding.category}\n"
        f"Explanation: {finding.explanation}\n\n"
        f"Candidates:\n{candidates}\n\n"
        "Return ONLY a JSON array, one object per candidate, with keys "
        "index (the number in brackets), label (relevant, ambiguous or irrelevant) and "
        "reason (one short sentence in Turkish). Do not wrap it in markdown."
    )


# ------------------------------------------------------- statutory fact extraction
_FACT_DESCRIPTIONS = {
    "premises_kind": 'kind of leased premises: "residential" (konut) or "workplace" (çatılı işyeri)',
    "monthly_rent": "monthly rent as a number in TL",
    "deposit_amount": "security deposit (depozito / güvence bedeli) as a number in TL",
    "deposit_months": "security deposit expressed as number of months of rent",
    "rent_increase_percent": "fixed yearly rent increase percentage as a number (e.g. 25 for %25)",
    "rent_increase_index": 'index the rent increase is tied to: "tufe_12m_avg", "tufe", "ufe" or "other"',
    "eviction_undertaking": 'eviction undertaking (tahliye taahhüdü): "with_contract" if given with/at the date of the contract, "after_handover" if after handover, else "unknown"',
    "late_payment_penalty": "true if a penalty (cezai şart) applies when rent is paid late",
    "acceleration_clause": "true if later rents become due at once when rent is paid late (muacceliyet)",
    "probation_months": "probation period (deneme süresi) in months",
    "collective_agreement": "true if a collective labour agreement (toplu iş sözleşmesi) is referenced",
    "notice_weeks": "termination notice period (bildirim / ihbar süresi) in weeks",
    "non_compete_years": "post-employment non-compete (rekabet yasağı) duration in years",
}


def facts_prompt(clause_payload: str, contract_type: str | None) -> str:
    names = FACTS_BY_TYPE.get(contract_type or "", ())
    wanted = "\n".join(f"- {name}: {_FACT_DESCRIPTIONS[name]}" for name in names)
    return (
        "Extract facts from the Turkish contract clauses below. Do NOT judge legality and do NOT "
        "mention any law. Return ONLY a JSON array, no markdown. Each item: "
        '{"fact": <name>, "value": <number, true/false or the allowed string>, "clause_id": <id>}. '
        "Include a fact only if the text states it; omit facts that are not stated. "
        "Convert durations to the requested unit.\n\n"
        f"Facts to extract:\n{wanted}\n\n"
        f"Clauses:\n{clause_payload}"
    )


# -------------------------------------------------------- missing clause detection
def missing_clauses_prompt(clause_payload: str, topics: tuple[ChecklistTopic, ...]) -> str:
    listed = "\n".join(f"- {topic.id}: {topic.title}" for topic in topics)
    return (
        "Decide for each topic below whether the Turkish contract contains a clause that "
        "substantively covers it (a passing mention is not enough). Return ONLY a JSON array, "
        'no markdown, one item per topic: {"topic": <id>, "present": true/false}.\n\n'
        f"Topics:\n{listed}\n\n"
        f"Contract clauses (titles and text, possibly shortened):\n{clause_payload}"
    )


# ------------------------------------------------------------------ clause rewrite
def rewrite_clauses_prompt(
    items: list[tuple[Clause, list[RiskFinding]]],
    contract_type: str | None,
    party: str | None,
) -> str:
    blocks = []
    for clause, findings in items:
        issues = "\n".join(f"  - [{finding.category}] {finding.explanation}" for finding in findings)
        blocks.append(f"clause_id: {clause.id}\nText: {clause.text}\nIssues:\n{issues}")
    user = role_label(contract_type, party)
    side = (
        f"Draft from the perspective of the {user} (the user), keeping the clause fair and enforceable. "
        if user
        else "Draft a balanced version that is fair to both parties. "
    )
    return (
        "You are a Turkish contract lawyer. For EACH clause below write a replacement clause in "
        "Turkish (with correct Turkish characters) that fixes all listed issues while keeping the "
        "clause's commercial purpose, plus a one- or two-sentence Turkish rationale. "
        + side
        + "Do not cite law numbers or article numbers. Keep each replacement under 700 characters. "
        "Return ONLY a JSON array, no markdown, one item per clause: "
        '{"clause_id": <id>, "suggested_text": <text>, "rationale": <text>}.\n\n'
        + (f"Contract type: {contract_type}\n\n" if contract_type else "")
        + "\n\n".join(blocks)
    )
