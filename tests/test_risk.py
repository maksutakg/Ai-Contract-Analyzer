from law_rag.risk import risk_level_for_score
from law_rag.models import RiskFinding
from law_rag.risk import calculate_risk_score


def test_risk_level_keeps_low_eighties_high() -> None:
    assert risk_level_for_score(82) == "high"
    assert risk_level_for_score(90) == "critical"


def test_single_critical_finding_does_not_force_score_to_100() -> None:
    findings = [
        RiskFinding(
            id="finding-1",
            category="data_protection",
            severity="critical",
            explanation="KVKK sorumlulugu reddediliyor.",
            recommendation="Sorumluluk reddini kaldirin.",
            confidence=1.0,
        ),
        RiskFinding(
            id="finding-2",
            category="payment_interest",
            severity="low",
            explanation="Gecikme faizi yuksek olabilir.",
            recommendation="Faiz oranini kontrol edin.",
            confidence=0.9,
        ),
        RiskFinding(
            id="finding-3",
            category="intellectual_property",
            severity="medium",
            explanation="Hak devri belirsiz.",
            recommendation="Hak devrini netlestirin.",
            confidence=0.9,
        ),
    ]

    assert calculate_risk_score(findings) < 100
