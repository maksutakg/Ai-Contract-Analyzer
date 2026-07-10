from .models import RiskFinding, RiskLevel


SEVERITY_WEIGHTS = {
    "low": 15,
    "medium": 35,
    "high": 65,
    "critical": 85,
}


def risk_level_for_score(score: int) -> RiskLevel:
    if score < 25:
        return "low"
    if score < 50:
        return "medium"
    if score < 90:
        return "high"
    return "critical"


def calculate_risk_score(findings: list[RiskFinding]) -> int:
    if not findings:
        return 0

    weighted_scores = [
        SEVERITY_WEIGHTS[finding.severity] * finding.confidence for finding in findings
    ]
    average_score = sum(weighted_scores) / len(weighted_scores)
    highest_score = max(weighted_scores)
    density_bonus = min(20, max(0, len(findings) - 1) * 4)
    score = max(average_score, highest_score) + density_bonus
    return min(100, round(score))
