from law_rag.facts import extract_facts_rule_based
from law_rag.models import Clause, ExtractedFact, RiskFinding
from law_rag.statutes import ground_findings
from law_rag.statutory_rules import merge_violations, run_statutory_checks


def test_deposit_explanation_formats_thousands_with_dots() -> None:
    facts = [
        ExtractedFact(name="premises_kind", value="residential"),
        ExtractedFact(name="monthly_rent", value=20000.0, clause_id="clause-2"),
        ExtractedFact(name="deposit_amount", value=100000.0, clause_id="clause-3"),
    ]

    checks = run_statutory_checks(facts, "lease", None)
    deposit_check = next(check for check in checks if check.rule_id == "lease_deposit_cap")

    assert deposit_check.status == "violation"
    assert deposit_check.extracted_value == "100.000 TL (5 aylık kira)"
    assert "100.000 TL" in deposit_check.explanation


def test_lease_deposit_ok_and_needs_review_when_premises_unknown() -> None:
    ok_checks = run_statutory_checks(
        [ExtractedFact(name="deposit_months", value=2.0, clause_id="clause-1")],
        "lease",
        None,
    )
    ok_deposit = next(c for c in ok_checks if c.rule_id == "lease_deposit_cap")
    assert ok_deposit.status == "ok"
    assert ok_deposit.legal_basis.article == "m.342"

    review_checks = run_statutory_checks(
        [ExtractedFact(name="deposit_months", value=4.0, clause_id="clause-1")],
        "lease",
        None,
    )
    review_deposit = next(c for c in review_checks if c.rule_id == "lease_deposit_cap")
    assert review_deposit.status == "needs_review"


def test_lease_rent_increase_cap_with_and_without_cpi() -> None:
    unset = run_statutory_checks(
        [
            ExtractedFact(name="premises_kind", value="residential"),
            ExtractedFact(name="rent_increase_percent", value=60.0, clause_id="clause-2"),
        ],
        "lease",
        None,
    )
    assert next(c for c in unset if c.rule_id == "lease_rent_increase_cap").status == "needs_review"

    violated = run_statutory_checks(
        [
            ExtractedFact(name="premises_kind", value="workplace"),
            ExtractedFact(name="rent_increase_percent", value=60.0, clause_id="clause-2"),
        ],
        "lease",
        45.0,
    )
    rent_check = next(c for c in violated if c.rule_id == "lease_rent_increase_cap")
    assert rent_check.status == "violation"
    assert rent_check.legal_basis.article == "m.344"

    tufe_ok = run_statutory_checks(
        [ExtractedFact(name="rent_increase_index", value="tufe_12m_avg", clause_id="clause-2")],
        "lease",
        None,
    )
    assert next(c for c in tufe_ok if c.rule_id == "lease_rent_increase_cap").status == "ok"


def test_lease_penalty_acceleration_and_eviction_undertaking() -> None:
    checks = run_statutory_checks(
        [
            ExtractedFact(name="premises_kind", value="residential"),
            ExtractedFact(name="late_payment_penalty", value=True, clause_id="clause-4"),
            ExtractedFact(name="acceleration_clause", value=True, clause_id="clause-4"),
            ExtractedFact(name="eviction_undertaking", value="with_contract", clause_id="clause-5"),
        ],
        "lease",
        None,
    )
    penalty = next(c for c in checks if c.rule_id == "lease_penalty_acceleration")
    eviction = next(c for c in checks if c.rule_id == "lease_eviction_undertaking_date")

    assert penalty.status == "violation"
    assert penalty.legal_basis.article == "m.346"
    assert eviction.status == "violation"
    assert eviction.legal_basis.article == "m.352/1"


def test_employment_probation_notice_and_non_compete_rules() -> None:
    checks = run_statutory_checks(
        [
            ExtractedFact(name="probation_months", value=4.0, clause_id="clause-1"),
            ExtractedFact(name="notice_weeks", value=1.0, clause_id="clause-2"),
            ExtractedFact(name="non_compete_years", value=3.0, clause_id="clause-3"),
        ],
        "employment",
        None,
    )
    by_id = {c.rule_id: c for c in checks}

    assert by_id["employment_probation_cap"].status == "violation"
    assert by_id["employment_probation_cap"].legal_basis.article == "m.15"
    assert by_id["employment_notice_minimum"].status == "violation"
    assert by_id["employment_notice_minimum"].legal_basis.article == "m.17"
    assert by_id["employment_non_compete_cap"].status == "violation"
    assert by_id["employment_non_compete_cap"].legal_basis.article == "m.445"

    with_cba = run_statutory_checks(
        [
            ExtractedFact(name="probation_months", value=4.0, clause_id="clause-1"),
            ExtractedFact(name="collective_agreement", value=True, clause_id="clause-1"),
            ExtractedFact(name="notice_weeks", value=4.0, clause_id="clause-2"),
            ExtractedFact(name="non_compete_years", value=2.0, clause_id="clause-3"),
        ],
        "employment",
        None,
    )
    by_id_cba = {c.rule_id: c for c in with_cba}
    assert by_id_cba["employment_probation_cap"].status == "needs_review"
    assert by_id_cba["employment_notice_minimum"].status == "needs_review"
    assert by_id_cba["employment_non_compete_cap"].status == "ok"


def test_merge_violations_replaces_same_clause_and_category_finding_and_grounds_statutes() -> None:
    clauses = [
        Clause(id="clause-1", title="MADDE 1", text="Konut kira sözleşmesidir."),
        Clause(id="clause-2", title="MADDE 2", text="Depozito 5 aylık kira bedelidir."),
    ]
    analyzer_findings = [
        RiskFinding(
            id="finding-1",
            category="deposit_forfeiture",
            severity="medium",
            explanation="Depozito yüksek.",
            recommendation="Düşürün.",
            confidence=0.8,
            clause_id="clause-2",
            detected_by="llm",
        )
    ]
    facts = extract_facts_rule_based(clauses, "lease")
    checks = run_statutory_checks(facts, "lease", None)

    merged, updated_checks = merge_violations(analyzer_findings, checks, ["clause-1", "clause-2"])
    grounded = ground_findings(merged, "lease")

    assert len(grounded) == 1
    assert grounded[0].confidence == 1.0
    assert grounded[0].detected_by == "statutory_rule"
    assert grounded[0].statutory_check_id == "lease_deposit_cap"
    assert grounded[0].legal_references[0].law_number == "6098"
    assert grounded[0].legal_references[0].article == "m.342"
    deposit_check = next(c for c in updated_checks if c.rule_id == "lease_deposit_cap")
    assert deposit_check.finding_id == "finding-1"
