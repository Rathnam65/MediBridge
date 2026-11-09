"""Hybrid local code/reference retrieval with explicit lexical fallback."""
from functools import lru_cache
import re
from pathlib import Path
import sqlite3

from .vector_store import IndexVersionMismatch, LocalVectorStore
from .embeddings import OllamaEmbeddingAdapter
from ...config import get_settings
from ..llm.client import ModelUnavailable

BASE = Path(__file__).resolve().parents[3]
DEFAULT_INDEX = BASE / "data" / "retrieval" / "medibridge.sqlite"
DEFAULT_CODING_DIR = BASE / "data" / "coding"
CATALOG_VERSION = "ICD-10-CM-2027|HCPCS-2026_Q4"
_LEXICAL_INDEX = None
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
    "has", "have", "he", "her", "his", "i", "in", "is", "it", "its", "of",
    "on", "or", "patient", "she", "that", "the", "their", "there", "they",
    "this", "to", "was", "we", "were", "with", "you",
}


@lru_cache(maxsize=1)
def _tabular_records():
    path = DEFAULT_CODING_DIR / "ICD10CM" / "2027" / "tabular.json"
    if not path.is_file():
        return {}
    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {item["code"]: item for item in payload}
    instructions = payload.get("instruction_records", {})
    records = {}
    for item in payload.get("codes", []):
        item["instructions"] = [
            instructions[reference] for reference in item.get("instruction_refs", [])
            if reference in instructions
        ]
        records[_normalized_icd_code(item["code"])] = item
    return records


@lru_cache(maxsize=1)
def _index_terms():
    path = DEFAULT_CODING_DIR / "ICD10CM" / "2027" / "index.json"
    if not path.is_file():
        return {}
    import json
    records = json.loads(path.read_text(encoding="utf-8"))
    terms = {}
    for item in records:
        for code in item.get("codes", []):
            terms.setdefault(_normalized_icd_code(code), []).append(item)
    return terms


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _normalized_icd_code(code):
    return code.replace(".", "").upper()


def _lexical_candidates(codes, query_tokens, semantic_ids):
    global _LEXICAL_INDEX
    if _LEXICAL_INDEX is None or _LEXICAL_INDEX[0] is not codes:
        postings = {}
        by_key = {}
        aliases = _index_terms()
        for index, (code_type, code, description, terms) in enumerate(codes):
            by_key[f"{codes[index][0]}:{code}"] = index
            alias_key = _normalized_icd_code(code) if code_type == "ICD-10-CM" else code
            index_text = " ".join(
                item.get("term", "") for item in aliases.get(alias_key, [])
            )
            for token in _tokens(f"{code} {description} {terms} {index_text}") - STOPWORDS:
                postings.setdefault(token, []).append(index)
        _LEXICAL_INDEX = (codes, postings, by_key, aliases)
    postings = _LEXICAL_INDEX[1]
    candidates = {
        index for token in query_tokens for index in postings.get(token, ())
    }
    if semantic_ids:
        by_key = _LEXICAL_INDEX[2]
        candidates.update(by_key[item] for item in semantic_ids if item in by_key)
    return candidates


def retrieve(
    query, codes, index_path=DEFAULT_INDEX, catalog_version=CATALOG_VERSION,
    limit=8, allowed_types=None,
):
    query_tokens = _tokens(query) - STOPWORDS
    if not query_tokens:
        return {"results": [], "strategy": "lexical", "warning": None}

    semantic = {}
    strategy = "lexical"
    warning = None
    semantic_sources = {}
    settings = get_settings()
    embedding_model = settings["local_embedding_model_name"]
    if not embedding_model:
        warning = (
            "Semantic retrieval is not configured. Set OLLAMA_EMBEDDING_MODEL "
            "to an installed local Ollama embedding model; using lexical fallback."
        )
    elif not Path(index_path).is_file():
        warning = "Semantic index is missing; build it with scripts/build_local_index.py. Using lexical fallback."
    else:
        store = LocalVectorStore(
            index_path,
            OllamaEmbeddingAdapter(
                embedding_model,
                base_url=settings["local_model_url"],
                timeout=settings["local_model_timeout"],
            ),
        )
        try:
            semantic_query = " ".join(sorted(query_tokens))
            semantic_results = store.search(
                semantic_query, catalog_version, limit=100
            )
            semantic = {
                item["metadata"].get("code", item["id"].split(":")[1]): item["score"]
                for item in semantic_results
            }
            semantic_sources = {
                item["metadata"].get("code", item["id"].split(":")[1]): item["metadata"]
                for item in semantic_results
            }
            semantic_document_ids = {item["id"] for item in semantic_results}
            strategy = "hybrid-local"
        except (IndexVersionMismatch, ModelUnavailable, ValueError, sqlite3.Error) as error:
            warning = str(error) + " Using explicit lexical fallback."

    tabular = _tabular_records()
    aliases = _LEXICAL_INDEX[3] if _LEXICAL_INDEX and _LEXICAL_INDEX[0] is codes else _index_terms()
    scored = []
    semantic_ids = semantic_document_ids if semantic else set()
    for index in _lexical_candidates(codes, query_tokens, semantic_ids):
        code_type, code, description, terms = codes[index]
        if allowed_types is not None and code_type not in allowed_types:
            continue
        text = f"{code} {description} {terms}"
        alias_key = _normalized_icd_code(code) if code_type == "ICD-10-CM" else code
        index_records = aliases.get(alias_key, [])
        index_text = " ".join(item.get("term", "") for item in index_records)
        tokens = (_tokens(f"{text} {index_text}") - STOPWORDS)
        overlap = len(query_tokens & tokens) / max(1, len(query_tokens))
        exact = 1.0 if code.casefold() in query.casefold() else 0.0
        vector_score = semantic.get(code, 0.0)
        matching_index = max(
            index_records,
            key=lambda item: len(query_tokens & (_tokens(item.get("term", "")) - STOPWORDS)),
            default=None,
        )
        index_overlap = (
            len(query_tokens & (_tokens(matching_index.get("term", "")) - STOPWORDS))
            if matching_index else 0
        )
        index_overlap_ratio = index_overlap / max(1, len(query_tokens))
        exact_index_match = any(
            query_tokens & (_tokens(item.get("term", "")) - STOPWORDS)
            and ">" not in item.get("term", "")
            for item in index_records
        )
        semantic_score = (
            max(0.0, min(1.0, (vector_score + 1.0) / 2.0))
            if code in semantic else 0.0
        )
        score = (
            0.45 * overlap + 0.18 * index_overlap_ratio
            + 0.12 * exact_index_match + 0.05 * exact + 0.20 * semantic_score
        )
        if score <= 0:
            continue
        reference = (
            tabular.get(_normalized_icd_code(code), {})
            if code_type == "ICD-10-CM" else {}
        )
        semantic_source = semantic_sources.get(code, {})
        scored.append({
            "type": code_type,
            "code": code,
            "description": description,
            "catalog_version": (
                reference.get("catalog_version", "2027")
                if code_type == "ICD-10-CM" else "2026_Q4"
            ),
            "source_file": reference.get("source_file") or (
                matching_index.get("source_file") if index_overlap
                else semantic_source.get("source_file", "codes.json")
            ),
            "source_location": reference.get("source_location") or (
                matching_index.get("source_location") if index_overlap
                else semantic_source.get("source_location", f"code:{code}")
            ),
            "instructions": reference.get("instructions", []),
            "billable": reference.get("billable"),
            "retrieval_score": round(score, 6),
            "semantic_score": round(semantic_score, 6),
            "lexical_score": round(overlap, 6),
            "index_score": round(index_overlap_ratio, 6),
            "retrieval_method": strategy,
            "evidence": query[:500],
            "matched_index_terms": [
                item.get("term", "") for item in index_records
                if query_tokens & (_tokens(item.get("term", "")) - STOPWORDS)
            ],
        })
    scored.sort(key=lambda item: (-item["retrieval_score"], item["type"], item["code"]))
    return {"results": scored[:max(1, min(int(limit), 50))],
            "strategy": strategy, "warning": warning}
