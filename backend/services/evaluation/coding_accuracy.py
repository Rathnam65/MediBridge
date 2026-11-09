"""Metrics for explicitly adjudicated coding sets only."""
from collections import Counter

from ...schemas import EvaluationCase


def evaluate_coding_accuracy(cases, predictions):
    cases = [EvaluationCase.model_validate(item) for item in cases]
    if not cases:
        raise ValueError("No evaluation cases were supplied.")
    if any(item.adjudication_status != "adjudicated" for item in cases):
        raise ValueError("Coding accuracy requires coder-adjudicated cases.")
    if len({item.case_id for item in cases}) != len(cases):
        raise ValueError("Evaluation case IDs must be unique.")

    exact = partial = predicted_total = expected_total = unsupported = overrides = 0
    for case in cases:
        expected = set(case.expected_codes)
        predicted = set(predictions.get(case.case_id, {}).get("predicted_codes", []))
        accepted = expected & predicted
        exact += expected == predicted
        partial += bool(accepted)
        predicted_total += len(predicted)
        expected_total += len(expected)
        unsupported += len(predicted - expected)
        coder_codes = predictions.get(case.case_id, {}).get("coder_codes")
        if coder_codes is not None:
            overrides += set(coder_codes) != predicted

    true_positive = expected_total - sum(
        len(set(case.expected_codes) -
            set(predictions.get(case.case_id, {}).get("predicted_codes", [])))
        for case in cases
    )
    false_positive = unsupported
    false_negative = expected_total - true_positive
    precision = true_positive / predicted_total if predicted_total else 0.0
    recall = true_positive / expected_total if expected_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "case_count": len(cases),
        "exact_match_rate": exact / len(cases),
        "partial_case_agreement_rate": partial / len(cases),
        "code_precision": precision,
        "code_recall": recall,
        "code_f1": f1,
        "unsupported_code_rate": false_positive / predicted_total if predicted_total else 0.0,
        "reviewer_override_rate": overrides / len(cases),
        "true_positive_codes": true_positive,
        "false_positive_codes": false_positive,
        "false_negative_codes": false_negative,
    }
