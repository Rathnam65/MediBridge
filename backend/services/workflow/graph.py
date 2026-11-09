"""Small LangGraph demo: extraction, local retrieval, optional local reasoning, review."""
import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..coding.hcpcs_validation import validate_hcpcs_recommendation
from ..clinical_nlp.extraction import extract_clinical_context
from ..llm.client import LocalModelClient, ModelUnavailable
from ..pipeline import CODES
from ..retrieval.rag import retrieve
from ...config import get_settings


class AnalysisState(TypedDict, total=False):
    text: str
    baseline: dict[str, Any]
    context: dict[str, Any]
    candidates: list[dict[str, Any]]
    retrieval_method: str
    retrieval_warning: str | None
    model_status: str
    model_error: str | None
    model_provenance: dict[str, str] | None
    model_rationale: str
    model_selected_codes: list[str]
    recommendations: list[dict[str, Any]]
    review_required: bool
    review_reasons: list[str]
    pipeline_trace: list[dict[str, Any]]


class UnavailableLocalModelClient:
    configured = True
    model = ""

    def __init__(self, error):
        self.error = str(error)

    def check_status(self):
        return {
            "connected": False,
            "model_available": False,
            "error": self.error,
        }

    def generate_json(self, prompt):
        raise ModelUnavailable(self.error)


def build_analysis_graph(model_client=None, index_path=None):
    if model_client is not None:
        client = model_client
    else:
        try:
            client = LocalModelClient()
        except ValueError as error:
            client = UnavailableLocalModelClient(error)

    def parse_node(state: AnalysisState):
        context = extract_clinical_context(state["text"])
        context_data = {
            "mentions": [item.model_dump() for item in context.mentions],
            "conflicts": context.conflicts,
            "review_required": context.review_required,
            "review_reasons": context.review_reasons,
            "nlp_status": context.nlp_status,
            "nlp_error": context.nlp_error,
            "model_provenance": context.model_provenance,
        }
        return {"context": {
            **context_data,
        }, "pipeline_trace": [{
            "node": "parse",
            "inputs": ["text"],
            "outputs": {
                "mention_count": len(context.mentions),
                "conflict_count": len(context.conflicts),
                "nlp_status": context.nlp_status,
            },
            "status": "warning" if context.nlp_error else "complete",
            "error": context.nlp_error,
        }]}

    def retrieve_node(state: AnalysisState):
        mentions = state.get("context", {}).get("mentions", [])
        eligible_mentions = [
            item for item in mentions
            if item["assertion"] not in {"negated", "historical"}
            and item["experiencer"] == "patient"
        ]
        query = " ".join(dict.fromkeys(item["text"] for item in eligible_mentions))
        allowed_types = {
            "HCPCS" if item["category"] == "procedure" else "ICD-10-CM"
            for item in eligible_mentions
            if item["category"] in {"diagnosis", "symptom", "procedure"}
        }
        search = retrieve(
            query, CODES,
            index_path=index_path or get_settings()["vector_index_path"],
            allowed_types=allowed_types,
        )
        best_by_mention = {}
        for candidate in search["results"]:
            expected_categories = (
                {"procedure"} if candidate["type"] == "HCPCS"
                else {"diagnosis", "symptom"}
            )
            description = candidate.get("description", "").casefold()
            index_terms = candidate.get("matched_index_terms", [])
            matching_mentions = []
            for mention in mentions:
                term = mention["text"].casefold()
                exact_index_matches = any(
                    term in index_term.casefold()
                    and ">" not in index_term
                    for index_term in index_terms
                )
                if (
                    mention["category"] in expected_categories
                    and (
                        term in description
                        or exact_index_matches
                        or candidate.get("semantic_score", 0) >= 0.65
                    )
                ):
                    matching_mentions.append(mention)
            if not matching_mentions:
                continue
            if any(
                item["assertion"] in {"negated", "historical"}
                or item["experiencer"] != "patient"
                for item in matching_mentions
            ):
                continue
            candidate["context_uncertain"] = any(
                item["assertion"] in {"uncertain", "planned"}
                for item in matching_mentions
            )
            for mention in matching_mentions:
                key = (mention["text"].casefold(), mention["category"])
                current = best_by_mention.get(key)
                if current is None or candidate["retrieval_score"] > current["retrieval_score"]:
                    best_by_mention[key] = candidate
        candidates = list({
            item["code"]: item for item in best_by_mention.values()
        }.values())
        by_code = {item["code"]: item for item in candidates}
        catalog_by_code = {
            code: (code_type, code, description, terms)
            for code_type, code, description, terms in CODES
        }
        for item in state.get("baseline", {}).get("recommendations", []):
            official = catalog_by_code.get(item.get("code"))
            if not official or item.get("type") != official[0]:
                continue
            code_type, code, description, terms = official
            candidate = by_code.get(code)
            if candidate:
                for field in ("confidence", "evidence", "evidence_span"):
                    if field in item:
                        candidate[field] = item[field]
            else:
                by_code[code] = {
                    "type": code_type,
                    "code": code,
                    "description": description,
                    "terms": terms,
                    "confidence": item.get("confidence", 0),
                    "evidence": item.get("evidence", ""),
                    "evidence_span": item.get("evidence_span"),
                    "catalog_version": "2027" if code_type == "ICD-10-CM" else "2026_Q4",
                    "source_file": "codes.json",
                    "source_location": f"code:{code}",
                    "instructions": [],
                    "retrieval_method": "deterministic-baseline",
                }
        return {
            "candidates": list(by_code.values()),
            "retrieval_method": search["strategy"],
            "retrieval_warning": search["warning"],
            "pipeline_trace": state.get("pipeline_trace", []) + [{
                "node": "retrieve",
                "inputs": ["context.mentions", "baseline.recommendations"],
                "outputs": {
                    "candidate_count": len(by_code),
                    "retrieval_method": search["strategy"],
                },
                "status": "warning" if search["warning"] else "complete",
                "error": search["warning"],
            }],
        }

    def reasoning_node(state: AnalysisState):
        if not client.configured:
            return {
                "model_status": "unconfigured",
                "model_error": "No local model configured; showing deterministic suggestions only.",
                "pipeline_trace": state.get("pipeline_trace", []) + [{
                    "node": "reason",
                    "inputs": ["text", "candidates"],
                    "outputs": {"selected_count": 0},
                    "status": "skipped",
                    "error": "No local model configured.",
                }],
            }
        status_check = getattr(client, "check_status", None)
        if status_check:
            status = status_check()
            if not status.get("model_available"):
                error = status.get("error") or "Configured local model is unavailable."
                return {
                    "model_status": "unavailable",
                    "model_error": error,
                    "pipeline_trace": state.get("pipeline_trace", []) + [{
                        "node": "reason",
                        "inputs": ["text", "candidates"],
                        "outputs": {"selected_count": 0},
                        "status": "warning",
                        "error": error,
                    }],
                }
        if not state.get("candidates"):
            error = "No catalog candidates are available for model reasoning."
            return {
                "model_status": "skipped",
                "model_error": error,
                "pipeline_trace": state.get("pipeline_trace", []) + [{
                    "node": "reason",
                    "inputs": ["text", "candidates"],
                    "outputs": {"selected_count": 0},
                    "status": "skipped",
                    "error": error,
                }],
            }
        prompt = (
            "Review the clinical note and candidate codes. Do not invent codes. "
            "Return JSON with selected_codes (array of candidate code strings) and "
            "rationale (short string). This is only a coder-assistance suggestion; "
            "do not approve any code.\nNOTE:\n" + state["text"][:6000] +
            "\nCANDIDATES:\n" + json.dumps([
                {"code": item["code"], "description": item["description"]}
                for item in state.get("candidates", [])[:30]
            ])
        )
        try:
            response = client.generate_json(prompt)
        except ModelUnavailable as error:
            return {
                "model_status": "unavailable",
                "model_error": str(error),
                "pipeline_trace": state.get("pipeline_trace", []) + [{
                    "node": "reason",
                    "inputs": ["text", "candidates"],
                    "outputs": {"selected_count": 0},
                    "status": "warning",
                    "error": str(error),
                }],
            }
        selected = response.get("selected_codes", [])
        valid = {item["code"] for item in state.get("candidates", [])}
        if not isinstance(selected, list) or any(
            not isinstance(code, str) or code not in valid for code in selected
        ):
            return {
                "model_status": "invalid_response",
                "model_error": "Local model selected a code outside the retrieved candidates.",
                "pipeline_trace": state.get("pipeline_trace", []) + [{
                    "node": "reason",
                    "inputs": ["text", "candidates"],
                    "outputs": {"selected_count": 0},
                    "status": "warning",
                    "error": "Local model selected a code outside the retrieved candidates.",
                }],
            }
        provenance = {"provider": "Ollama-compatible local endpoint",
                      "model": client.model}
        return {
            "model_status": "available",
            "model_error": None,
            "model_provenance": provenance,
            "model_selected_codes": selected,
            "model_rationale": str(response.get("rationale", ""))[:1000],
            "pipeline_trace": state.get("pipeline_trace", []) + [{
                "node": "reason",
                "inputs": ["text", "candidates"],
                "outputs": {
                    "selected_count": len(selected),
                    "model": client.model,
                },
                "status": "complete",
                "error": None,
            }],
        }

    def validation_node(state: AnalysisState):
        recommendations = []
        review_reasons = list(state.get("context", {}).get("review_reasons", []))
        if state.get("retrieval_warning"):
            review_reasons.append(state["retrieval_warning"])
        if state.get("model_error"):
            review_reasons.append(state["model_error"])
        for candidate in state.get("candidates", []):
            item = dict(candidate)
            item["source"] = {
                "catalog_type": item.get("type"),
                "catalog_version": item.get("catalog_version"),
                "source_file": item.get("source_file"),
                "source_location": item.get("source_location"),
            }
            item["model_selected"] = item["code"] in state.get("model_selected_codes", [])
            item["review_required"] = True
            if item.get("type") == "HCPCS":
                item["validation"] = validate_hcpcs_recommendation(
                    item["code"], state["text"],
                    [{"code": code, "description": description}
                     for kind, code, description, _ in CODES if kind == "HCPCS"],
                )
                review_reasons.extend(item["validation"]["flags"])
            recommendations.append(item)
        return {
            "recommendations": recommendations,
            "review_required": True,
            "review_reasons": list(dict.fromkeys(review_reasons)),
            "pipeline_trace": state.get("pipeline_trace", []) + [{
                "node": "validate",
                "inputs": ["candidates", "model_selected_codes", "context.review_reasons"],
                "outputs": {
                    "recommendation_count": len(recommendations),
                    "human_review_required": True,
                    "review_reason_count": len(set(review_reasons)),
                },
                "status": "complete",
                "error": None,
            }],
        }

    workflow = StateGraph(AnalysisState)
    workflow.add_node("parse", parse_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("reason", reasoning_node)
    workflow.add_node("validate", validation_node)
    workflow.add_edge(START, "parse")
    workflow.add_edge("parse", "retrieve")
    workflow.add_edge("retrieve", "reason")
    workflow.add_edge("reason", "validate")
    workflow.add_edge("validate", END)
    return workflow.compile()


def run_analysis_workflow(text, baseline, model_client=None, index_path=None):
    graph = build_analysis_graph(model_client=model_client, index_path=index_path)
    return graph.invoke(
        {"text": text, "baseline": baseline},
        {"recursion_limit": 8},
    )
