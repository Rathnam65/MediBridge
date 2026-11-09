"""Rule-based, evidence-spanned clinical mention extraction for the demo."""
from functools import lru_cache
import math
import re
from pathlib import Path

from ...schemas import ClinicalMention, ClinicalNote
from ...config import get_settings


TERMS = {
    "diagnosis": (
        "hypertension", "high blood pressure", "type 2 diabetes", "diabetes",
        "hyperlipidemia", "gerd", "reflux", "asthma", "pneumonia",
        "heart failure", "chronic kidney disease",
    ),
    "symptom": ("fatigue", "headache", "cough", "fever", "nausea", "chest pain"),
    "procedure": ("blood pressure measurement", "venipuncture", "blood collection", "a1c", "metabolic panel"),
    "medication": ("metformin", "lisinopril", "atorvastatin", "insulin"),
}
NEGATION = re.compile(r"\b(?:no|not|without|denies|denied|negative for|absence of)\b", re.I)
HISTORY = re.compile(r"\b(?:history of|historical|previously had|resolved|remote)\b", re.I)
UNCERTAINTY = re.compile(r"\b(?:possible|possibly|suspected|rule out|cannot exclude|may have|question of)\b", re.I)
FAMILY = re.compile(r"\b(?:mother|father|sister|brother|family history|maternal|paternal)\b", re.I)
FUTURE = re.compile(r"\b(?:plan to|will start|schedule for|recommend(?:ed)?|consider(?:ing)?)\b", re.I)
SENTENCES = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")


class ClinicalNLPUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=2)
def _load_disease_ner(model_id: str):
    try:
        from transformers import (
            AutoModelForTokenClassification,
            AutoTokenizer,
            pipeline,
        )
    except ImportError as error:
        raise ClinicalNLPUnavailable(
            "Optional clinical NLP dependencies are missing; install requirements-clinical-nlp.txt."
        ) from error
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model_id, local_files_only=True
        )
        model = AutoModelForTokenClassification.from_pretrained(
            model_id, local_files_only=True
        )
        return pipeline(
            "token-classification",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy="simple",
        )
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise ClinicalNLPUnavailable(
            f"Configured local clinical NLP model '{model_id}' could not be loaded: {error}"
        ) from error


def _sentence_for_span(text: str, start: int, end: int) -> tuple[int, int, str]:
    for match in SENTENCES.finditer(text):
        if match.start() <= start < match.end():
            return match.start(), match.end(), match.group().strip()
    return 0, len(text), text


def _evidence_for_span(
    text: str, sentence_start: int, sentence_end: int, start: int
) -> str:
    sentence = text[sentence_start:sentence_end]
    if len(sentence) <= 2_000:
        return sentence.strip()
    excerpt_start = max(0, start - sentence_start - 1_000)
    excerpt_end = min(len(sentence), excerpt_start + 2_000)
    if excerpt_end - excerpt_start < 2_000:
        excerpt_start = max(0, excerpt_end - 2_000)
    return sentence[excerpt_start:excerpt_end].strip()


def _assertion_for_span(text: str, start: int, end: int):
    sentence_start, sentence_end, sentence = _sentence_for_span(text, start, end)
    prefix = sentence[:max(0, start - sentence_start)].lower()
    if FAMILY.search(sentence):
        return sentence_start, sentence_end, sentence, "negated", "historical", "family_member"
    if NEGATION.search(prefix[-60:]):
        return sentence_start, sentence_end, sentence, "negated", "current", "patient"
    if UNCERTAINTY.search(prefix[-80:]):
        return sentence_start, sentence_end, sentence, "uncertain", "current", "patient"
    if FUTURE.search(prefix[-80:]):
        return sentence_start, sentence_end, sentence, "planned", "future", "patient"
    if HISTORY.search(prefix[-80:]):
        return sentence_start, sentence_end, sentence, "historical", "historical", "patient"
    return sentence_start, sentence_end, sentence, "affirmed", "current", "patient"


def _clinical_text_chunks(text: str, max_chars: int = 1800, overlap: int = 200):
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        yield start, end
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def extract_clinical_context(text: str, source_name: str = "clinical note") -> ClinicalNote:
    mentions = []
    for category, terms in TERMS.items():
        for term in terms:
            for match in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I):
                (sentence_start, sentence_end, sentence, assertion,
                 temporality, experiencer) = _assertion_for_span(text, *match.span())
                mentions.append(ClinicalMention(
                    text=match.group(),
                    category=category,
                    assertion=assertion,
                    temporality=temporality,
                    experiencer=experiencer,
                    evidence=_evidence_for_span(
                        text, sentence_start, sentence_end, match.start()
                    ),
                    source_file=Path(source_name).name,
                    start=match.start(),
                    end=match.end(),
                    sentence_start=sentence_start,
                    sentence_end=sentence_end,
                    provenance="rule-based",
                ))

    model_id = get_settings()["clinical_nlp_model"]
    nlp_status = "not_configured"
    nlp_error = None
    model_provenance = None
    if model_id:
        try:
            ner_model = _load_disease_ner(model_id)
            entities = []
            for chunk_start, chunk_end in _clinical_text_chunks(text[:200_000]):
                chunk_entities = ner_model(text[chunk_start:chunk_end])
                if not isinstance(chunk_entities, list):
                    raise ClinicalNLPUnavailable(
                        "Local clinical NLP model returned an invalid entity list."
                    )
                for entity in chunk_entities:
                    if not isinstance(entity, dict):
                        raise ClinicalNLPUnavailable(
                            "Local clinical NLP model returned an invalid entity."
                        )
                    adjusted = dict(entity)
                    if isinstance(adjusted.get("start"), int) and isinstance(
                        adjusted.get("end"), int
                    ):
                        adjusted["start"] += chunk_start
                        adjusted["end"] += chunk_start
                    entities.append(adjusted)
            model_config = getattr(getattr(ner_model, "model", None), "config", None)
            revision = getattr(model_config, "_commit_hash", None)
            model_provenance = f"huggingface:{model_id}" + (
                f"@{revision}" if revision else ""
            )
            for entity in entities:
                label = str(entity.get("entity_group", entity.get("entity", ""))).casefold()
                if "disease" not in label:
                    continue
                start, end = entity.get("start"), entity.get("end")
                confidence = entity.get("score")
                if (
                    not isinstance(start, int) or not isinstance(end, int)
                    or start < 0 or end <= start or end > len(text)
                    or not isinstance(confidence, (int, float))
                    or not math.isfinite(confidence) or not 0 <= confidence <= 1
                ):
                    raise ClinicalNLPUnavailable("Local clinical NLP model returned invalid entity offsets or confidence.")
                overlap = next(
                    (
                        item for item in mentions
                        if start < item.end and end > item.start
                    ),
                    None,
                )
                if overlap:
                    if start == overlap.start and end == overlap.end:
                        overlap.confidence = float(confidence)
                        overlap.provenance = model_provenance
                    continue
                sentence_start, sentence_end, sentence, assertion, temporality, experiencer = (
                    _assertion_for_span(text, start, end)
                )
                mentions.append(ClinicalMention(
                    text=text[start:end],
                    category="diagnosis",
                    assertion=assertion,
                    temporality=temporality,
                    experiencer=experiencer,
                    evidence=_evidence_for_span(
                        text, sentence_start, sentence_end, start
                    ),
                    source_file=Path(source_name).name,
                    start=start,
                    end=end,
                    sentence_start=sentence_start,
                    sentence_end=sentence_end,
                    confidence=float(confidence),
                    provenance=model_provenance,
                ))
            nlp_status = "available"
        except ClinicalNLPUnavailable as error:
            nlp_status = "unavailable"
            nlp_error = str(error)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            nlp_status = "unavailable"
            nlp_error = f"Local clinical NLP inference failed: {error}"

    mentions.sort(key=lambda item: (item.start, item.end, item.category))
    by_term = {}
    for mention in mentions:
        by_term.setdefault(mention.text.casefold(), set()).add(mention.assertion)
    conflicts = sorted(term for term, assertions in by_term.items() if len(assertions) > 1)
    review_reasons = []
    if any(item.assertion in {"uncertain", "planned"} for item in mentions):
        review_reasons.append("Uncertain or planned statements require coder review.")
    if conflicts:
        review_reasons.append("Conflicting assertions were found for: " + ", ".join(conflicts))
    if not mentions:
        review_reasons.append("No supported clinical terms were found; review the note manually.")
    if nlp_error:
        review_reasons.append(nlp_error)
    return ClinicalNote(
        mentions=mentions,
        conflicts=conflicts,
        review_required=bool(review_reasons),
        review_reasons=review_reasons,
        nlp_status=nlp_status,
        nlp_error=nlp_error,
        model_provenance=model_provenance,
    )
