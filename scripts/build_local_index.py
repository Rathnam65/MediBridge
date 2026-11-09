"""Build a versioned offline vector index from installed code catalogs."""
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from backend.services.pipeline import CODING_DATA_DIR
from backend.services.retrieval.rag import CATALOG_VERSION, DEFAULT_INDEX
from backend.services.retrieval.embeddings import OllamaEmbeddingAdapter
from backend.services.retrieval.vector_store import LocalVectorStore
from backend.config import get_settings


def build_index(coding_dir=CODING_DATA_DIR, index_path=DEFAULT_INDEX):
    coding_dir = Path(coding_dir)
    documents = []
    for catalog in sorted(coding_dir.rglob("codes.json")):
        records = json.loads(catalog.read_text(encoding="utf-8"))
        index_terms = {}
        index_path_for_catalog = catalog.parent / "index.json"
        if index_path_for_catalog.is_file():
            index_records = json.loads(
                index_path_for_catalog.read_text(encoding="utf-8")
            )
            for record in index_records:
                term = record.get("term", "")
                for code in record.get("codes", []):
                    normalized = code.replace(".", "").upper()
                    index_terms.setdefault(normalized, []).append(term)
        for item in records:
            doc_id = f"{item.get('type', '')}:{item.get('code', '')}"
            code = item.get("code", "")
            terms = index_terms.get(code.replace(".", "").upper(), [])
            text = " ".join(
                part for part in (
                    code, item.get("description", ""), item.get("terms", ""),
                    " ".join(terms),
                ) if part
            )
            if doc_id.strip(":") and text.strip():
                documents.append({
                    "id": doc_id,
                    "text": text,
                    "metadata": {
                        "catalog_type": item.get("type"),
                        "catalog_version": (
                            "2027" if item.get("type") == "ICD-10-CM" else "2026_Q4"
                        ),
                        "source_file": str(catalog.relative_to(coding_dir)),
                        "source_location": f"code:{item.get('code', '')}",
                        "code": code,
                        "index_terms": terms,
                    },
                })
    settings = get_settings()
    if not settings["local_embedding_model_name"]:
        raise ValueError(
            "Set OLLAMA_EMBEDDING_MODEL to an installed local Ollama embedding model before building the index."
        )
    embedder = OllamaEmbeddingAdapter(
        settings["local_embedding_model_name"],
        base_url=settings["local_model_url"],
        timeout=settings["local_model_timeout"],
    )
    count = LocalVectorStore(index_path, embedder=embedder).build(
        documents, CATALOG_VERSION
    )
    return {"documents": count, "catalog_version": CATALOG_VERSION,
            "embedding_model": embedder.model_id,
            "index_path": str(Path(index_path).resolve())}


if __name__ == "__main__":
    print(json.dumps(build_index(), indent=2))
