"""Benchmark deterministic and optional Ollama embeddings using synthetic text only."""
import argparse
import json
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from backend.config import get_settings
from backend.services.llm.client import ModelUnavailable
from backend.services.retrieval.embeddings import HashEmbeddingAdapter, OllamaEmbeddingAdapter

SAMPLES = (
    "Synthetic note: patient has hypertension and high blood pressure.",
    "Synthetic note: cough and fever are denied; no active respiratory symptoms.",
    "Synthetic reference: type 2 diabetes mellitus without complications.",
)


def benchmark(models=(), base_url=None):
    settings = get_settings()
    base_url = base_url or settings["local_model_url"]
    results = []
    for dimensions in (64, 128):
        adapter = HashEmbeddingAdapter(dimensions)
        started = time.perf_counter()
        vectors = [adapter.embed(text) for text in SAMPLES]
        results.append({
            "model": adapter.model_id,
            "status": "ok",
            "sample_count": len(vectors),
            "dimensions": len(vectors[0]),
            "mean_latency_seconds": (time.perf_counter() - started) / len(vectors),
            "quality_claim": "deterministic lexical feature baseline only",
        })
    failed = False
    for model in models:
        started = time.perf_counter()
        try:
            adapter = OllamaEmbeddingAdapter(model, base_url=base_url)
            vectors = [adapter.embed(text) for text in SAMPLES]
            results.append({
                "model": adapter.model_id,
                "status": "ok",
                "sample_count": len(vectors),
                "dimensions": len(vectors[0]),
                "mean_latency_seconds": (time.perf_counter() - started) / len(vectors),
                "quality_claim": "latency and dimensions only; evaluate retrieval relevance separately",
            })
        except (ModelUnavailable, ValueError) as error:
            failed = True
            results.append({"model": model, "status": "unavailable", "error": str(error)})
    return {
        "endpoint": base_url,
        "clinical_data_sent": False,
        "candidates": results,
        "warning": "Use only synthetic samples. This benchmark does not establish clinical quality.",
        "failed": failed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--base-url", default=None)
    args = parser.parse_args()
    report = benchmark(args.models, args.base_url)
    print(json.dumps(report, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
