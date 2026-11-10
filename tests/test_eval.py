import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from evaluate import (
    DEFAULT_DATASET,
    evaluate_crag_grader,
    evaluate_risk_calibration,
    load_dataset,
    run_contracts,
    run_evaluation,
)
from law_rag.chat_index import build_chunks
from law_rag.config import Settings
from law_rag.fake_analyzer import FakeContractAnalyzer
from law_rag.segmentation import segment_clauses


def test_sample_dataset_clause_ids_match_segmentation() -> None:
    dataset = load_dataset(DEFAULT_DATASET)

    assert len(dataset.contracts) >= 3
    for contract in dataset.contracts:
        clause_ids = {clause.id for clause in segment_clauses(contract.raw_text)}
        for expected in contract.expected_findings:
            assert expected.clause_id in clause_ids


@pytest.mark.asyncio
async def test_offline_evaluation_runs_all_sections() -> None:
    result = await run_evaluation(
        dataset_path=DEFAULT_DATASET,
        live=False,
        stability_runs=2,
        tufe_percent=45.0,
    )

    baseline = result["risk_detection"]["rule_based_baseline"]["strict_pair"]
    assert 0.0 <= baseline["precision"] <= 1.0
    assert 0.0 <= baseline["recall"] <= 1.0
    assert 0.0 <= baseline["f1"] <= 1.0

    crag = result["crag_grader"]["keyword_only"]
    assert crag["total"] == 6
    assert set(crag["by_label"]) == {"relevant", "ambiguous", "irrelevant"}

    chat = result["chat_retrieval"]["offline_fake_embedder"]
    assert set(chat["modes"]) == {"lexical", "dense", "hybrid"}
    assert len(chat["lexical_sweep_top5"]) == 5
    assert len(chat["dense_sweep"]) == 10

    stability = result["score_stability"]["rule_based_baseline"]
    assert stability["max_std_dev"] == 0.0

    calibration = result["risk_score_calibration"]["rule_based_baseline"]
    assert len(calibration["synthetic_saturation_comparison"]) == 5


@pytest.mark.asyncio
async def test_sample_dataset_chat_chunk_ids_and_keyword_crag() -> None:
    dataset = load_dataset(DEFAULT_DATASET)
    app_settings = Settings(_env_file=None, crag_use_llm_grader=False, tufe_12m_average_change_percent=45.0)
    analyzer = FakeContractAnalyzer()
    reports = await run_contracts(dataset, analyzer, app_settings)

    for contract in dataset.contracts:
        chunk_ids = {chunk.id for chunk in build_chunks(reports[contract.contract_id])}
        for question in contract.chat_questions:
            assert set(question.relevant_chunk_ids).issubset(chunk_ids)

    crag = await evaluate_crag_grader(dataset, None)
    assert crag["total"] > 0

    calibration = evaluate_risk_calibration(dataset, reports)
    scores = [row["noisy_or_score"] for row in calibration["synthetic_saturation_comparison"]]
    assert scores == sorted(scores)
