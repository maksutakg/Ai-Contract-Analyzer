from law_rag.models import RiskFinding
from law_rag.risk import (
    calculate_risk_score,
    calculate_risk_score_legacy,
    risk_level_for_score,
    risk_level_for_score_legacy,
)


def _finding(severity: str, confidence: float = 1.0, finding_id: str = "finding-1") -> RiskFinding:
    return RiskFinding(
        id=finding_id,
        category="termination",
        severity=severity,
        explanation="Risk aciklamasi.",
        recommendation="Maddeyi duzenleyin.",
        confidence=confidence,
    )


def test_risk_level_thresholds_and_legacy_comparison() -> None:
    assert risk_level_for_score(0) == "low"
    assert risk_level_for_score(24) == "low"
    assert risk_level_for_score(25) == "medium"
    assert risk_level_for_score(49) == "medium"
    assert risk_level_for_score(50) == "high"
    assert risk_level_for_score(74) == "high"
    assert risk_level_for_score(75) == "critical"
    assert risk_level_for_score(82) == "critical"
    assert risk_level_for_score_legacy(82) == "high"
    assert risk_level_for_score_legacy(90) == "critical"


def test_noisy_or_risk_score_and_confidence_scaling() -> None:
    assert calculate_risk_score([]) == 0
    assert calculate_risk_score([_finding("low", 1.0)]) == 10
    assert calculate_risk_score([_finding("medium", 1.0)]) == 25
    assert calculate_risk_score([_finding("high", 1.0)]) == 45
    assert calculate_risk_score([_finding("critical", 1.0)]) == 70
    assert calculate_risk_score([_finding("critical", 0.5)]) == 35
    assert calculate_risk_score([_finding("critical", 1.0, "f1"), _finding("critical", 1.0, "f2")]) == 91


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

    score = calculate_risk_score(findings)
    assert score < 100
    assert score == 79
    assert calculate_risk_score_legacy(findings) == 93
