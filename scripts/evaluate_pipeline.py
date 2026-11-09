"""Run a repeatable, synthetic-only extraction/retrieval demo evaluation."""
import argparse
import json
from pathlib import Path
import sys
import time
import tracemalloc

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from backend.schemas import EvaluationCase
from backend.services.clinical_nlp.extraction import extract_clinical_context
from backend.services.evaluation.coding_accuracy import evaluate_coding_accuracy
from backend.services.pipeline import CODES
from backend.services.retrieval.rag import retrieve
from backend.services.workflow.graph import run_analysis_workflow

DEFAULT_FIXTURE = BASE / "tests" / "fixtures" / "evaluation_cases.json"


def _span_metrics(expected, actual):
    expected_set = {
        (item["text"].casefold(), item["category"], item["assertion"], item["experiencer"])
        for item in expected
    }
    actual_set = {
        (item["text"].casefold(), item["category"], item["assertion"], item["experiencer"])
        for item in actual
    }
    true_positive = len(expected_set & actual_set)
    precision = true_positive / len(actual_set) if actual_set else 0.0
    recall = true_positive / len(expected_set) if expected_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return true_positive, len(actual_set) - true_positive, len(expected_set) - true_positive, precision, recall, f1


def evaluate(fixture_path=DEFAULT_FIXTURE):
    source = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    cases = [EvaluationCase.model_validate(item) for item in source["cases"]]
    expected_tp = expected_fp = expected_fn = 0
    precision_sum = recall_sum = f1_sum = latency_sum = 0.0
    retrieval_hits = retrieval_total = workflow_completed = workflow_errors = abstentions = 0
    tracemalloc.start()
    for case in cases:
        started = time.perf_counter()
        context = extract_clinical_context(case.documented_text)
        elapsed = time.perf_counter() - started
        latency_sum += elapsed
        actual = [item.model_dump() for item in context.mentions]
        tp, fp, fn, precision, recall, f1 = _span_metrics(
            [item.model_dump() for item in case.expected_mentions], actual
        )
        expected_tp += tp
        expected_fp += fp
        expected_fn += fn
        precision_sum += precision
        recall_sum += recall
        f1_sum += f1
        retrieval = retrieve(case.documented_text, CODES, limit=10)
        if case.adjudication_status == "adjudicated":
            retrieval_total += len(case.expected_codes)
            retrieval_hits += len(
                set(case.expected_codes) & {item["code"] for item in retrieval["results"]}
            )
        try:
            workflow = run_analysis_workflow(
                case.documented_text,
                {"recommendations": []},
            )
            workflow_completed += 1
            abstentions += workflow.get("model_status") in {"unconfigured", "unavailable"}
        except Exception:
            workflow_errors += 1
            raise
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    micro_precision = expected_tp / (expected_tp + expected_fp) if expected_tp + expected_fp else 0.0
    micro_recall = expected_tp / (expected_tp + expected_fn) if expected_tp + expected_fn else 0.0
    micro_f1 = 2 * micro_precision * micro_recall / (micro_precision + micro_recall) if micro_precision + micro_recall else 0.0
    return {
        "dataset_version": source["dataset_version"],
        "evaluation_type": "synthetic_demo_unadjudicated",
        "case_count": len(cases),
        "clinical_span_metrics": {
            "micro_precision": micro_precision,
            "micro_recall": micro_recall,
            "micro_f1": micro_f1,
            "illustrative_case_macro_precision": precision_sum / len(cases),
            "illustrative_case_macro_recall": recall_sum / len(cases),
            "illustrative_case_macro_f1": f1_sum / len(cases),
        },
        "retrieval_recall_at_10": retrieval_hits / retrieval_total if retrieval_total else None,
        "retrieval_labeled_codes": retrieval_total,
        "workflow": {
            "completed": workflow_completed,
            "errors": workflow_errors,
            "model_unavailable_or_unconfigured": abstentions,
        },
        "runtime": {
            "mean_context_extraction_seconds": latency_sum / len(cases),
            "peak_traced_memory_bytes": peak_memory,
        },
        "coding_accuracy": None,
        "warning": "Illustrative synthetic extraction metrics are not clinical accuracy or coder-adjudicated results.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.fixture)
    serialized = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
