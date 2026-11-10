"""Contract risk scoring.

Current score (noisy-OR): each finding is treated as an independent chance that
the contract causes a problem, p_i = SEVERITY_PROBABILITY[severity] * confidence,
and the score is 100 * (1 - prod(1 - p_i)). Adding findings always raises the
score but it approaches 100 only gradually instead of saturating.

The previous formula is kept as `calculate_risk_score_legacy` /
`risk_level_for_score_legacy` so the two can be compared on a dataset.
"""

from math import prod

from .models import RiskFinding, RiskLevel

SEVERITY_PROBABILITY: dict[str, float] = {
    "low": 0.10,
    "medium": 0.25,
    "high": 0.45,
    "critical": 0.70,
}

# A score at or above the threshold gets that level.
MEDIUM_RISK_THRESHOLD = 25
HIGH_RISK_THRESHOLD = 50
CRITICAL_RISK_THRESHOLD = 75


def risk_level_for_score(score: int) -> RiskLevel:
    if score < MEDIUM_RISK_THRESHOLD:
        return "low"
    if score < HIGH_RISK_THRESHOLD:
        return "medium"
    if score < CRITICAL_RISK_THRESHOLD:
        return "high"
    return "critical"


def calculate_risk_score(findings: list[RiskFinding]) -> int:
    if not findings:
        return 0
    survival = prod(
        1.0 - SEVERITY_PROBABILITY[finding.severity] * finding.confidence for finding in findings
    )
    return max(0, min(100, round(100 * (1.0 - survival))))


# --------------------------------------------------------------------- legacy
LEGACY_SEVERITY_WEIGHTS: dict[str, int] = {
    "low": 15,
    "medium": 35,
    "high": 65,
    "critical": 85,
}
# Backward-compatible alias for the old constant name.
SEVERITY_WEIGHTS = LEGACY_SEVERITY_WEIGHTS


def risk_level_for_score_legacy(score: int) -> RiskLevel:
    if score < 25:
        return "low"
    if score < 50:
        return "medium"
    if score < 90:
        return "high"
    return "critical"


def calculate_risk_score_legacy(findings: list[RiskFinding]) -> int:
    """Old formula: max(average, highest) + min(20, 4 * (n - 1)), capped at 100."""
    if not findings:
        return 0

    weighted_scores = [
        LEGACY_SEVERITY_WEIGHTS[finding.severity] * finding.confidence for finding in findings
    ]
    average_score = sum(weighted_scores) / len(weighted_scores)
    highest_score = max(weighted_scores)
    density_bonus = min(20, max(0, len(findings) - 1) * 4)
    score = max(average_score, highest_score) + density_bonus
    return min(100, round(score))
