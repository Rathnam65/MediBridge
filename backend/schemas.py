from pydantic import BaseModel, Field, model_validator
from typing import Literal


class ClinicalMention(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    category: str = Field(pattern="^(diagnosis|symptom|procedure|medication)$")
    assertion: str = Field(pattern="^(affirmed|negated|historical|uncertain|planned)$")
    temporality: str = Field(pattern="^(current|historical|future)$")
    experiencer: str = Field(pattern="^(patient|family_member)$")
    evidence: str = Field(min_length=1, max_length=2_000)
    source_file: str = Field(min_length=1, max_length=500)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    sentence_start: int = Field(ge=0)
    sentence_end: int = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: str = Field(default="rule-based", min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_evidence_span(self):
        if self.end < self.start or self.sentence_start > self.start or self.sentence_end < self.end:
            raise ValueError("Clinical mention offsets must be contained in the evidence sentence.")
        return self


class ClinicalNote(BaseModel):
    mentions: list[ClinicalMention]
    conflicts: list[str] = Field(default_factory=list)
    review_required: bool
    review_reasons: list[str]
    nlp_status: str = "not_configured"
    nlp_error: str | None = None
    model_provenance: str | None = None


class ExpectedMention(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    category: str = Field(pattern="^(diagnosis|symptom|procedure|medication)$")
    assertion: str = Field(pattern="^(affirmed|negated|historical|uncertain|planned)$")
    experiencer: str = Field(pattern="^(patient|family_member)$")


class TextRequest(BaseModel):
    text: str = Field(min_length=10, max_length=200_000)


class SyntheticTextRequest(BaseModel):
    text: str = Field(min_length=10, max_length=200_000)
    synthetic_only: Literal[True]


class DecisionRequest(BaseModel):
    decision: str
    note: str = ''


class SignupRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class SourceEvidence(BaseModel):
    source_id: str = Field(min_length=1, max_length=300)
    catalog_type: str = Field(min_length=1, max_length=40)
    catalog_version: str = Field(min_length=1, max_length=40)
    source_file: str = Field(min_length=1, max_length=500)
    locator: str = Field(min_length=1, max_length=120)
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_span(self):
        if self.end < self.start:
            raise ValueError("Evidence end must not precede its start.")
        return self


class EvaluationCase(BaseModel):
    case_id: str = Field(min_length=1, max_length=120)
    dataset_version: str = Field(min_length=1, max_length=120)
    documented_text: str = Field(min_length=1, max_length=200_000)
    expected_codes: list[str] = Field(default_factory=list)
    expected_mentions: list[ExpectedMention] = Field(default_factory=list)
    adjudication_status: str = Field(pattern="^(pending|adjudicated)$")
    adjudicator_reference: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_adjudicator_for_labels(self):
        if self.adjudication_status == "adjudicated" and not self.adjudicator_reference:
            raise ValueError("Adjudicated cases require an adjudicator reference.")
        if self.adjudication_status == "adjudicated" and not self.expected_codes:
            raise ValueError("Adjudicated cases require at least one accepted code.")
        return self
