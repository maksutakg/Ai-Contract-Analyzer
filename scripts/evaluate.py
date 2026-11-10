import argparse
import asyncio
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from eval_models import AnnotatedContract, EvalDataset
from law_rag.analyzer_base import ContractAnalyzer
from law_rag.call_gate import CallGate
from law_rag.chat_index import (
    LEXICAL_MIN_COVERAGE,
    LEXICAL_MIN_SCORE,
    ChatIndex,
    RetrievalMode,
    build_index,
    lexical_scores,
    rank_chunks,
    retrieve,
)
from law_rag.config import Settings
from law_rag.crag import keyword_grade
from law_rag.embeddings import Embedder, FakeEmbedder, GeminiEmbedder, cosine
from law_rag.fake_analyzer import FakeContractAnalyzer
from law_rag.graph import analyze_contract
from law_rag.graph_steps import applicable
from law_rag.llm import GeminiContractAnalyzer
from law_rag.models import ContractReport, RiskFinding, YargiDecision
from law_rag.risk import (
    calculate_risk_score,
    calculate_risk_score_legacy,
    risk_level_for_score,
    risk_level_for_score_legacy,
)
from law_rag.yargi_client import FakeYargiClient

DEFAULT_DATASET = SCRIPTS_DIR / "eval_data" / "sample_dataset.json"


def _safe_div(num: float, den: float) -> float:
    return round(num / den, 4) if den else 0.0


def _prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def load_dataset(path: Path = DEFAULT_DATASET) -> EvalDataset:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return EvalDataset.model_validate(raw)


async def run_contracts(
    dataset: EvalDataset,
    analyzer: ContractAnalyzer,
    app_settings: Settings,
) -> dict[str, ContractReport]:
    reports: dict[str, ContractReport] = {}
    yargi_client = FakeYargiClient()
    for contract in dataset.contracts:
        reports[contract.contract_id] = await analyze_contract(
            file_name=f"{contract.contract_id}.txt",
            file_type="docx",
            raw_text=contract.raw_text,
            contract_type=contract.contract_type,
            party=contract.party,
            analyzer=analyzer,
            yargi_client=yargi_client,
            app_settings=app_settings,
        )
    return reports


def score_risk_detection(
    dataset: EvalDataset,
    reports: dict[str, ContractReport],
) -> dict[str, Any]:
    strict_tp = strict_fp = strict_fn = 0
    clause_tp = clause_fp = clause_fn = 0
    cat_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    per_contract: list[dict[str, Any]] = []

    for contract in dataset.contracts:
        report = reports[contract.contract_id]
        predicted_pairs = {
            (finding.clause_id, finding.category)
            for finding in report.findings
            if finding.clause_id
        }
        expected_pairs = {
            (item.clause_id, item.category)
            for item in contract.expected_findings
        }
        c_tp = len(predicted_pairs & expected_pairs)
        c_fp = len(predicted_pairs - expected_pairs)
        c_fn = len(expected_pairs - predicted_pairs)
        strict_tp += c_tp
        strict_fp += c_fp
        strict_fn += c_fn

        for _, cat in predicted_pairs & expected_pairs:
            cat_counts[cat][0] += 1
        for _, cat in predicted_pairs - expected_pairs:
            cat_counts[cat][1] += 1
        for _, cat in expected_pairs - predicted_pairs:
            cat_counts[cat][2] += 1

        pred_clauses = {cid for cid, _ in predicted_pairs}
        exp_clauses = {cid for cid, _ in expected_pairs}
        clause_tp += len(pred_clauses & exp_clauses)
        clause_fp += len(pred_clauses - exp_clauses)
        clause_fn += len(exp_clauses - pred_clauses)

        per_contract.append(
            {
                "contract_id": contract.contract_id,
                "predicted": sorted([f"{c}:{cat}" for c, cat in predicted_pairs]),
                "expected": sorted([f"{c}:{cat}" for c, cat in expected_pairs]),
                "metrics": _prf(c_tp, c_fp, c_fn),
            }
        )

    per_category = {
        cat: _prf(counts[0], counts[1], counts[2])
        for cat, counts in sorted(cat_counts.items())
    }
    return {
        "strict_pair": _prf(strict_tp, strict_fp, strict_fn),
        "clause_level": _prf(clause_tp, clause_fp, clause_fn),
        "per_category": per_category,
        "per_contract": per_contract,
    }


async def evaluate_crag_grader(
    dataset: EvalDataset,
    analyzer: ContractAnalyzer | None,
) -> dict[str, Any]:
    labels = ("relevant", "ambiguous", "irrelevant")
    confusion: dict[str, dict[str, int]] = {
        gold: {pred: 0 for pred in labels} for gold in labels
    }
    total = 0
    correct = 0

    for contract in dataset.contracts:
        by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
        for idx, example in enumerate(contract.decision_examples):
            by_key[(example.finding_category, example.finding_explanation)].append(idx)

        for (category, explanation), indices in by_key.items():
            finding = RiskFinding(
                id="eval-finding",
                category=category,
                severity="high",
                explanation=explanation,
                recommendation="İnceleyin.",
            )
            decisions = [
                YargiDecision(
                    source="Eval",
                    title=contract.decision_examples[i].decision_title,
                    relevance="eval",
                    excerpt=contract.decision_examples[i].decision_excerpt,
                )
                for i in indices
            ]
            if analyzer is None:
                assessments = [keyword_grade(decision, category) for decision in decisions]
            else:
                assessments = list(await analyzer.grade_decisions(finding, decisions))
            for idx, assessment in zip(indices, assessments):
                gold = contract.decision_examples[idx].expected_grade
                pred = assessment.grade
                confusion[gold][pred] += 1
                total += 1
                if pred == gold:
                    correct += 1

    f1_by_label: dict[str, dict[str, Any]] = {}
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in labels if other != label)
        fn = sum(confusion[label][other] for other in labels if other != label)
        f1_by_label[label] = _prf(tp, fp, fn)
    macro_f1 = round(sum(f1_by_label[label]["f1"] for label in labels) / len(labels), 4)
    return {
        "total": total,
        "accuracy": _safe_div(correct, total),
        "macro_f1": macro_f1,
        "by_label": f1_by_label,
        "confusion": confusion,
    }


def _gate_metrics(predictions: list[tuple[bool, bool]]) -> dict[str, Any]:
    tp = sum(1 for gold, pred in predictions if gold and pred)
    fp = sum(1 for gold, pred in predictions if not gold and pred)
    fn = sum(1 for gold, pred in predictions if gold and not pred)
    tn = sum(1 for gold, pred in predictions if not gold and not pred)
    cov_total = tp + fn
    oob_total = tn + fp
    return {
        "covered_tpr": _safe_div(tp, cov_total),
        "oob_tnr": _safe_div(tn, oob_total),
        "accuracy": _safe_div(tp + tn, len(predictions)),
        **_prf(tp, fp, fn),
    }


async def evaluate_chat_retrieval(
    dataset: EvalDataset,
    reports: dict[str, ContractReport],
    embedder: Embedder,
    dense_threshold: float | None = None,
) -> dict[str, Any]:
    built: list[tuple[AnnotatedContract, ChatIndex, list[list[float] | None]]] = []
    for contract in dataset.contracts:
        if not contract.chat_questions:
            continue
        report = reports[contract.contract_id]
        index = await build_index(report, embedder, max_chars=800)
        q_vecs: list[list[float] | None] = []
        for q in contract.chat_questions:
            if index.dense_available:
                try:
                    q_vecs.append(await embedder.embed_query(q.question))
                except Exception:
                    q_vecs.append(None)
            else:
                q_vecs.append(None)
        built.append((contract, index, q_vecs))

    modes: tuple[RetrievalMode, ...] = ("lexical", "dense", "hybrid")
    mode_results: dict[str, Any] = {}
    for mode in modes:
        hit1 = hit3 = hit6 = covered_count = 0
        recall_sum = mrr_sum = 0.0
        gate_pairs: list[tuple[bool, bool]] = []
        for contract, index, _ in built:
            for q in contract.chat_questions:
                raw = await retrieve(
                    index,
                    q.question,
                    embedder,
                    mode=mode,
                    top_k=max(6, len(index.chunks)),
                    min_dense_similarity=dense_threshold,
                    apply_threshold=False,
                )
                gated = await retrieve(
                    index,
                    q.question,
                    embedder,
                    mode=mode,
                    top_k=6,
                    min_dense_similarity=dense_threshold,
                    apply_threshold=True,
                )
                gate_pairs.append((q.covered, bool(gated.chunks)))
                if q.covered and q.relevant_chunk_ids:
                    covered_count += 1
                    relevant = set(q.relevant_chunk_ids)
                    ranked_ids = [item.chunk.id for item in raw.chunks]
                    if any(cid in relevant for cid in ranked_ids[:1]):
                        hit1 += 1
                    if any(cid in relevant for cid in ranked_ids[:3]):
                        hit3 += 1
                    top6 = ranked_ids[:6]
                    hits6 = [cid for cid in top6 if cid in relevant]
                    if hits6:
                        hit6 += 1
                    recall_sum += len(set(hits6)) / len(relevant)
                    for rank, cid in enumerate(ranked_ids, start=1):
                        if cid in relevant:
                            mrr_sum += 1.0 / rank
                            break
        mode_results[mode] = {
            "covered_questions": covered_count,
            "hit_at_1": _safe_div(hit1, covered_count),
            "hit_at_3": _safe_div(hit3, covered_count),
            "hit_at_6": _safe_div(hit6, covered_count),
            "recall_at_6": _safe_div(recall_sum, covered_count),
            "mrr": _safe_div(mrr_sum, covered_count),
            "gate": _gate_metrics(gate_pairs),
        }

    lexical_sweep: list[dict[str, Any]] = []
    for min_score in (0.3, 0.5, 0.75, 1.0, 1.25):
        for min_cov in (0.15, 0.25, 0.35, 0.5):
            pairs: list[tuple[bool, bool]] = []
            for contract, index, _ in built:
                for q in contract.chat_questions:
                    scores, coverage = lexical_scores(index, q.question)
                    matched = any(s >= min_score and c >= min_cov for s, c in zip(scores, coverage))
                    pairs.append((q.covered, matched))
            lexical_sweep.append(
                {
                    "min_score": min_score,
                    "min_coverage": min_cov,
                    **_gate_metrics(pairs),
                }
            )
    lexical_sweep.sort(key=lambda item: (-item["f1"], -item["oob_tnr"], item["min_score"]))

    dense_sweep: list[dict[str, Any]] = []
    for min_sim in (0.15, 0.25, 0.3, 0.4, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8):
        pairs = []
        for contract, index, q_vecs in built:
            for q, vec in zip(contract.chat_questions, q_vecs):
                if vec is None or index.vectors is None:
                    matched = False
                else:
                    matched = any(cosine(vec, v) >= min_sim for v in index.vectors)
                pairs.append((q.covered, matched))
        dense_sweep.append({"min_dense_similarity": min_sim, **_gate_metrics(pairs)})
    dense_sweep.sort(key=lambda item: (-item["f1"], -item["oob_tnr"], item["min_dense_similarity"]))

    return {
        "modes": mode_results,
        "best_lexical_gate": lexical_sweep[0] if lexical_sweep else None,
        "lexical_sweep_top5": lexical_sweep[:5],
        "best_dense_gate": dense_sweep[0] if dense_sweep else None,
        "dense_sweep": dense_sweep,
    }


async def evaluate_score_stability(
    dataset: EvalDataset,
    analyzer: ContractAnalyzer,
    app_settings: Settings,
    runs: int = 3,
    max_contracts: int | None = None,
) -> dict[str, Any]:
    yargi_client = FakeYargiClient()
    selected = dataset.contracts[:max_contracts] if max_contracts else dataset.contracts
    per_contract: list[dict[str, Any]] = []
    for contract in selected:
        scores: list[int] = []
        levels: list[str] = []
        for _ in range(runs):
            report = await analyze_contract(
                file_name=f"{contract.contract_id}.txt",
                file_type="docx",
                raw_text=contract.raw_text,
                contract_type=contract.contract_type,
                party=contract.party,
                analyzer=analyzer,
                yargi_client=yargi_client,
                app_settings=app_settings,
            )
            scores.append(report.risk_score)
            levels.append(report.risk_level)
        mean_score = round(sum(scores) / len(scores), 2)
        std_dev = round(statistics.pstdev(scores), 4) if len(scores) > 1 else 0.0
        mode_level = max(set(levels), key=levels.count)
        level_agreement = _safe_div(sum(1 for lvl in levels if lvl == mode_level), len(levels))
        per_contract.append(
            {
                "contract_id": contract.contract_id,
                "runs": runs,
                "scores": scores,
                "levels": levels,
                "mean_score": mean_score,
                "std_dev": std_dev,
                "max_delta": max(scores) - min(scores),
                "level_agreement": level_agreement,
            }
        )
    return {
        "runs": runs,
        "max_std_dev": max((item["std_dev"] for item in per_contract), default=0.0),
        "per_contract": per_contract,
    }


def evaluate_risk_calibration(
    dataset: EvalDataset,
    reports: dict[str, ContractReport],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    noisy_hits = legacy_hits = total_with_target = 0
    for contract in dataset.contracts:
        report = reports[contract.contract_id]
        kept = applicable(report.findings)
        noisy_score = calculate_risk_score(kept)
        noisy_level = risk_level_for_score(noisy_score)
        legacy_score = calculate_risk_score_legacy(kept)
        legacy_level = risk_level_for_score_legacy(legacy_score)
        if contract.expected_risk_level is not None:
            total_with_target += 1
            if noisy_level == contract.expected_risk_level:
                noisy_hits += 1
            if legacy_level == contract.expected_risk_level:
                legacy_hits += 1
        rows.append(
            {
                "contract_id": contract.contract_id,
                "applicable_findings": len(kept),
                "expected_level": contract.expected_risk_level,
                "noisy_or_score": noisy_score,
                "noisy_or_level": noisy_level,
                "legacy_score": legacy_score,
                "legacy_level": legacy_level,
            }
        )

    synthetic_profiles: list[tuple[str, list[RiskFinding]]] = [
        ("single_low", [RiskFinding(id="1", category="termination", severity="low", explanation="e", recommendation="r")]),
        ("single_high", [RiskFinding(id="1", category="termination", severity="high", explanation="e", recommendation="r")]),
        ("single_critical", [RiskFinding(id="1", category="unlawful_entry", severity="critical", explanation="e", recommendation="r")]),
        (
            "one_crit_two_med",
            [
                RiskFinding(id="1", category="unlawful_entry", severity="critical", explanation="e", recommendation="r"),
                RiskFinding(id="2", category="termination", severity="medium", explanation="e", recommendation="r"),
                RiskFinding(id="3", category="penalty_clause", severity="medium", explanation="e", recommendation="r"),
            ],
        ),
        (
            "two_crit_two_high",
            [
                RiskFinding(id="1", category="unlawful_entry", severity="critical", explanation="e", recommendation="r"),
                RiskFinding(id="2", category="data_protection", severity="critical", explanation="e", recommendation="r"),
                RiskFinding(id="3", category="deposit_forfeiture", severity="high", explanation="e", recommendation="r"),
                RiskFinding(id="4", category="rent_increase", severity="high", explanation="e", recommendation="r"),
            ],
        ),
    ]
    synthetic = [
        {
            "profile": name,
            "noisy_or_score": calculate_risk_score(findings),
            "noisy_or_level": risk_level_for_score(calculate_risk_score(findings)),
            "legacy_score": calculate_risk_score_legacy(findings),
            "legacy_level": risk_level_for_score_legacy(calculate_risk_score_legacy(findings)),
        }
        for name, findings in synthetic_profiles
    ]

    return {
        "noisy_or_level_accuracy": _safe_div(noisy_hits, total_with_target),
        "legacy_level_accuracy": _safe_div(legacy_hits, total_with_target),
        "contracts": rows,
        "synthetic_saturation_comparison": synthetic,
    }


async def run_evaluation(
    dataset_path: Path = DEFAULT_DATASET,
    live: bool = False,
    stability_runs: int = 3,
    tufe_percent: float | None = 45.0,
) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    eval_settings = Settings(
        _env_file=None if not live else ".env",
        crag_use_llm_grader=live,
        crag_max_rewrites=0,
        tufe_12m_average_change_percent=tufe_percent,
    )
    if live:
        if not eval_settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required when --live is enabled.")
        eval_settings = eval_settings.model_copy(
            update={"llm_min_interval_seconds": max(eval_settings.llm_min_interval_seconds, 3.0)}
        )

    baseline_analyzer = FakeContractAnalyzer()
    baseline_reports = await run_contracts(dataset, baseline_analyzer, eval_settings)
    baseline_risk = score_risk_detection(dataset, baseline_reports)
    keyword_crag = await evaluate_crag_grader(dataset, None)
    offline_chat = await evaluate_chat_retrieval(dataset, baseline_reports, FakeEmbedder())
    offline_stability = await evaluate_score_stability(
        dataset, baseline_analyzer, eval_settings, runs=stability_runs
    )
    baseline_calibration = evaluate_risk_calibration(dataset, baseline_reports)

    summary: dict[str, Any] = {
        "dataset": str(dataset_path),
        "contracts": len(dataset.contracts),
        "live": live,
        "risk_detection": {"rule_based_baseline": baseline_risk},
        "crag_grader": {"keyword_only": keyword_crag},
        "chat_retrieval": {"offline_fake_embedder": offline_chat},
        "score_stability": {"rule_based_baseline": offline_stability},
        "risk_score_calibration": {"rule_based_baseline": baseline_calibration},
    }

    if live:
        gate = CallGate.from_settings(eval_settings)
        live_analyzer = GeminiContractAnalyzer(eval_settings, gate)
        live_reports = await run_contracts(dataset, live_analyzer, eval_settings)
        summary["risk_detection"]["llm_analyzer"] = score_risk_detection(dataset, live_reports)
        summary["risk_detection"]["llm_warnings"] = live_analyzer.drain_warnings()
        summary["crag_grader"]["llm_grader"] = await evaluate_crag_grader(dataset, live_analyzer)
        summary["chat_retrieval"]["gemini_embedding_001"] = await evaluate_chat_retrieval(
            dataset, live_reports, GeminiEmbedder(eval_settings, gate)
        )
        summary["score_stability"]["llm_analyzer"] = await evaluate_score_stability(
            dataset, live_analyzer, eval_settings, runs=stability_runs, max_contracts=1
        )
        summary["risk_score_calibration"]["llm_analyzer"] = evaluate_risk_calibration(
            dataset, live_reports
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Law RAG pipeline (Package 4)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--tufe", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = asyncio.run(
        run_evaluation(
            dataset_path=args.dataset,
            live=args.live,
            stability_runs=args.runs,
            tufe_percent=args.tufe,
        )
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

