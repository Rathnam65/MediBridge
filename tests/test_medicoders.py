import json
from io import BytesIO

import pytest

from backend.config import get_settings
from backend.main import codes
from backend.services.ingestion import extract_document_text
from backend.services.pipeline import analyze_text, load_reference_codes
from scripts.prepare_data import extract_hcpcs_records, extract_icd10cm_records
from scripts.seed_synthea_demo import load_synthea_cases


def test_reference_codes_loader_reads_prepared_catalog(tmp_path):
    catalog = tmp_path / "HCPCS" / "2026_Q4" / "codes.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps([
        {"type": "ICD-10-CM", "code": "A000", "description": "Cholera due to Vibrio cholerae 01"},
        {"type": "HCPCS", "code": "A1001", "description": "Dressing for one wound"},
    ]), encoding="utf-8")

    records = load_reference_codes(tmp_path)
    assert any(item[0] == "ICD-10-CM" and item[1] == "A000" for item in records)
    assert any(item[0] == "HCPCS" and item[1] == "A1001" for item in records)


def test_hcpcs_importer_keeps_only_allowed_level_two_procedure_codes():
    rows = [
        {"HCPC": "A1001", "RECID": "3", "LONG DESCRIPTION": "Covered item"},
        {"HCPC": "99213", "RECID": "3", "LONG DESCRIPTION": "Numeric CPT"},
        {"HCPC": "D0120", "RECID": "3", "LONG DESCRIPTION": "Dental code"},
        {"HCPC": "B1001", "RECID": "7", "LONG DESCRIPTION": "Modifier"},
        {"HCPC": "C1001", "RECID": "4", "LONG DESCRIPTION": "Continuation"},
    ]

    records = extract_hcpcs_records(rows)
    assert list(records) == ["A1001"]


def test_icd10cm_importer_parses_short_and_full_length_codes(tmp_path):
    source = tmp_path / "icd10cm_codes_2027.txt"
    source.write_text(
        "I10     Essential (primary) hypertension\n"
        "Z910122 Unspecified risk factor\n",
        encoding="utf-8",
    )

    records = extract_icd10cm_records(source)

    assert records["I10"]["type"] == "ICD-10-CM"
    assert records["I10"]["description"] == "Essential (primary) hypertension"
    assert records["Z910122"]["terms"] == "Unspecified risk factor"


def test_icd10cm_tabular_and_index_parsers_keep_hierarchy_rules_and_sources(tmp_path):
    from scripts.prepare_data import extract_icd10cm_index, extract_icd10cm_tabular

    tabular = tmp_path / "tabular.xml"
    tabular.write_text(
        "<ICD10CM.tabular><chapter><name>1</name><desc>Diseases</desc>"
        "<section id='I10-I19'><desc>Hypertension</desc>"
        "<diag><name>I10</name><desc>Hypertension</desc>"
        "<useAdditionalCode><note>Code the stage</note></useAdditionalCode>"
        "<diag><name>I10.0</name><desc>Example leaf</desc></diag>"
        "</diag></section></chapter></ICD10CM.tabular>",
        encoding="utf-8",
    )
    index = tmp_path / "index.xml"
    index.write_text(
        "<ICD10CM.index><version>2027</version><letter><mainTerm>"
        "<title>Hypertension</title><code>I10</code><term level='1'>"
        "<title>essential</title><code>I10</code></term>"
        "</mainTerm></letter></ICD10CM.index>",
        encoding="utf-8",
    )

    tabular_catalog = extract_icd10cm_tabular(tabular)
    tabular_records = tabular_catalog["codes"]
    index_records = extract_icd10cm_index(index)

    parent = next(item for item in tabular_records if item["code"] == "I10")
    leaf = next(item for item in tabular_records if item["code"] == "I10.0")
    assert parent["effective_year"] == 2027
    assert parent["billable"] is False
    assert parent["source_location"] == "diag:I10"
    inherited = [
        tabular_catalog["instruction_records"][reference]
        for reference in leaf["instruction_refs"]
    ]
    assert any(item["type"] == "use_additional_code" for item in inherited)
    assert leaf["parent_code"] == "I10"
    assert index_records[0]["codes"] == ["I10"]
    assert index_records[1]["term"] == "Hypertension > essential"


def test_hcpcs_validation_never_asserts_coverage_or_infers_missing_rules():
    from backend.services.coding.hcpcs_validation import validate_hcpcs_recommendation

    supported = validate_hcpcs_recommendation(
        "A1001", "Wound dressing performed.",
        [{"code": "A1001", "description": "Dressing for one wound"}],
    )
    unsupported = validate_hcpcs_recommendation(
        "Z9999", "Procedure performed.",
        [{"code": "A1001", "description": "Dressing for one wound"}],
    )

    assert supported["supported"] is True
    assert supported["review_required"] is True
    assert any("coverage" in flag for flag in supported["flags"])
    assert any("effective dates" in flag for flag in supported["flags"])
    assert unsupported["status"] == "unsupported"
    assert unsupported["review_required"] is True


def test_local_vector_index_persists_rebuilds_checks_versions_and_integrity(tmp_path):
    import pytest
    from backend.services.retrieval.embeddings import HashEmbeddingAdapter
    from backend.services.retrieval.vector_store import (
        IndexVersionMismatch, LocalVectorStore,
    )

    path = tmp_path / "index.sqlite"
    store = LocalVectorStore(path, embedder=HashEmbeddingAdapter())
    documents = [
        {"id": "ICD-10-CM:I10", "text": "hypertension high blood pressure",
         "metadata": {"source": "icd10cm-2027"}},
        {"id": "ICD-10-CM:J18.9", "text": "pneumonia infection",
         "metadata": {"source": "icd10cm-2027"}},
    ]
    assert store.build(documents, "2027") == 2
    assert store.check_integrity() == {"ok": True, "documents": 2, "error": None}
    results = store.search("hypertension", "2027")
    assert results[0]["id"] == "ICD-10-CM:I10"
    assert results[0]["metadata"]["source"] == "icd10cm-2027"
    with pytest.raises(IndexVersionMismatch):
        store.search("hypertension", "2028")
    assert store.build(documents[:1], "2028") == 1
    assert store.check_integrity()["documents"] == 1


def test_postgres_connection_adapter_supports_existing_qmark_queries(monkeypatch):
    from sqlalchemy import create_engine
    from backend import database

    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(database, "DATABASE_URL", "postgresql://placeholder")
    monkeypatch.setattr(database, "_get_engine", lambda: engine)
    connection = database.conn()
    try:
        connection.execute(
            "CREATE TABLE adapter_check(id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO adapter_check(id,label) VALUES (?,?)",
            (7, "synthetic-only"),
        )
        connection.commit()

        row = connection.execute(
            "SELECT id,label FROM adapter_check WHERE id=?", (7,)
        ).fetchone()

        assert row["id"] == 7
        assert row["label"] == "synthetic-only"
    finally:
        connection.close()
        engine.dispose()


def test_postgres_database_initialization_runs_alembic_without_touching_sqlite(
    monkeypatch,
):
    from alembic import command
    from backend import database

    calls = []
    monkeypatch.setattr(database, "DATABASE_URL", "postgresql://placeholder")
    monkeypatch.setattr(
        command, "upgrade",
        lambda config, revision: calls.append((config, revision)),
    )

    database.init_db()

    assert len(calls) == 1
    assert calls[0][1] == "head"
    assert calls[0][0].get_main_option("script_location") == "backend/migrations"


def test_postgres_required_setting_prevents_ephemeral_sqlite_fallback(
    tmp_path, monkeypatch
):
    from backend import database

    sqlite_path = tmp_path / "must-not-be-created.sqlite"
    monkeypatch.setattr(database, "DB", sqlite_path)
    monkeypatch.setattr(database, "DATABASE_URL", None)
    monkeypatch.setattr(database, "REQUIRE_POSTGRES", True)

    with pytest.raises(RuntimeError, match="DATABASE_URL is not configured"):
        database.init_db()

    assert not sqlite_path.exists()


def test_postgres_url_normalizes_neon_connection_string(monkeypatch):
    from backend import database

    monkeypatch.setattr(
        database,
        "DATABASE_URL",
        "postgres://demo:secret@ep-example.neon.tech/app?sslmode=require",
    )
    assert database._postgres_url() == (
        "postgresql+psycopg://demo:secret@ep-example.neon.tech/app?sslmode=require"
    )


def test_ollama_status_reports_connection_and_exact_model_availability(monkeypatch):
    import json
    import urllib.error
    from backend.services.llm.client import LocalModelClient

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return json.dumps(self.body).encode("utf-8")

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: Response({
            "models": [{
                "name": "qwen2.5:3b",
                "digest": "sha256:version-1",
            }],
        }),
    )
    client = LocalModelClient(
        base_url="http://127.0.0.1:11434", model="qwen2.5:3b"
    )
    available = client.check_status()
    assert available["connected"] is True
    assert available["model_available"] is True
    assert available["model_digest"] == "sha256:version-1"

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            urllib.error.URLError("offline")
        ),
    )
    unavailable = client.check_status()
    assert unavailable["connected"] is False
    assert unavailable["model_available"] is False
    assert "offline" in unavailable["error"]


def test_model_status_api_reports_local_providers_without_note_text(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main

    class Model:
        def check_status(self):
            return {
                "configured": True,
                "connected": True,
                "model_available": True,
                "model": "local-model",
                "model_digest": "sha256:local",
                "error": None,
            }

    class EmbeddingAdapter:
        def __init__(self, *args, **kwargs):
            self.client = Model()

    monkeypatch.setattr(main, "LocalModelClient", Model)
    monkeypatch.setattr(main, "OllamaEmbeddingAdapter", EmbeddingAdapter)
    monkeypatch.setattr(main, "settings", {
        **main.settings,
        "local_embedding_model_name": "local-embed",
        "local_model_url": "http://127.0.0.1:11434",
        "local_model_timeout": 12,
        "clinical_nlp_model": "local-nlp",
    })

    with TestClient(main.app) as client:
        response = client.get("/api/model-status")

    assert response.status_code == 200
    assert response.json()["reasoner"]["model_available"] is True
    assert response.json()["embeddings"]["model_digest"] == "sha256:local"
    assert response.json()["clinical_nlp"]["external_data_transfer"] is False
    assert response.json()["external_data_transfer"] is False


def test_ollama_embeddings_use_digest_pinned_batch_for_semantic_search(
    tmp_path, monkeypatch
):
    import json
    import pytest
    from backend.services.retrieval.embeddings import OllamaEmbeddingAdapter
    from backend.services.retrieval.vector_store import (
        IndexVersionMismatch, LocalVectorStore,
    )

    calls = []
    model_digest = ["sha256:embedding-v1"]

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return json.dumps(self.body).encode("utf-8")

    vectors = {
        "synthetic hypertension note": [1.0, 0.0],
        "synthetic lung disease reference": [0.0, 1.0],
        "vascular condition paraphrase": [0.8, 0.2],
    }

    def fake_urlopen(request, timeout):
        calls.append(request)
        assert timeout == 12
        assert request.full_url.startswith("http://127.0.0.1:11434/")
        if request.full_url.endswith("/api/tags"):
            return Response({
                "models": [{
                    "name": "nomic-embed-text:latest",
                    "digest": model_digest[0],
                }],
            })
        payload = json.loads(request.data)
        assert payload["model"] == "nomic-embed-text"
        inputs = payload["input"]
        if isinstance(inputs, str):
            inputs = [inputs]
        return Response({"embeddings": [vectors[text] for text in inputs]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    adapter = OllamaEmbeddingAdapter("nomic-embed-text")
    store = LocalVectorStore(tmp_path / "semantic.sqlite", embedder=adapter)
    store.build([
        {
            "id": "ICD-10-CM:I10",
            "text": "synthetic hypertension note",
            "metadata": {"code": "I10", "source": "official-catalog"},
        },
        {
            "id": "ICD-10-CM:J18.9",
            "text": "synthetic lung disease reference",
            "metadata": {"code": "J18.9", "source": "official-catalog"},
        },
    ], "catalog-v1")

    results = store.search("vascular condition paraphrase", "catalog-v1")

    assert adapter.model_id == "ollama-local:nomic-embed-text@sha256:embedding-v1"
    assert results[0]["id"] == "ICD-10-CM:I10"
    assert results[0]["metadata"]["source"] == "official-catalog"
    assert len(calls) == 3

    model_digest[0] = "sha256:embedding-v2"
    changed_adapter = OllamaEmbeddingAdapter("nomic-embed-text")
    with pytest.raises(IndexVersionMismatch, match="embedding model"):
        LocalVectorStore(
            tmp_path / "semantic.sqlite", embedder=changed_adapter
        ).search("vascular condition paraphrase", "catalog-v1")


def test_hybrid_retrieval_keeps_semantic_only_catalog_matches(monkeypatch, tmp_path):
    from backend.services.retrieval import rag

    class SemanticStore:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, query, catalog_version, limit):
            return [{
                "id": "ICD-10-CM:J18.9",
                "metadata": {"code": "J18.9"},
                "score": 0.8,
            }]

    monkeypatch.setattr(rag, "_tabular_records", lambda: {})
    monkeypatch.setattr(rag, "_index_terms", lambda: {})
    monkeypatch.setattr(rag, "get_settings", lambda: {
        "local_embedding_model_name": "local-test",
        "local_model_url": "http://127.0.0.1:11434",
        "local_model_timeout": 12,
    })
    monkeypatch.setattr(rag, "OllamaEmbeddingAdapter", lambda *args, **kwargs: object())
    monkeypatch.setattr(rag, "LocalVectorStore", SemanticStore)
    index_path = tmp_path / "present.sqlite"
    index_path.touch()

    result = rag.retrieve(
        "lung infection",
        [("ICD-10-CM", "J18.9", "Pulmonary disease", "")],
        index_path=index_path,
    )

    assert result["strategy"] == "hybrid-local"
    assert result["results"][0]["code"] == "J18.9"
    assert result["results"][0]["lexical_score"] == 0
    assert result["results"][0]["semantic_score"] == 0.9


def test_unavailable_embedding_model_uses_visible_lexical_fallback(monkeypatch, tmp_path):
    from backend.services.llm.client import ModelUnavailable
    from backend.services.retrieval import rag
    from backend.services.retrieval.embeddings import HashEmbeddingAdapter
    from backend.services.retrieval.vector_store import LocalVectorStore

    class UnavailableEmbedder:
        model_id = "ollama-local:missing"

        def ensure_available(self):
            raise ModelUnavailable("Ollama is offline.")

        def embed(self, text):
            raise AssertionError("Embedding should not run when Ollama is offline.")

    monkeypatch.setattr(rag, "_tabular_records", lambda: {})
    monkeypatch.setattr(rag, "_index_terms", lambda: {})
    monkeypatch.setattr(rag, "get_settings", lambda: {
        "local_embedding_model_name": "missing",
        "local_model_url": "http://127.0.0.1:11434",
        "local_model_timeout": 12,
    })
    monkeypatch.setattr(
        rag, "OllamaEmbeddingAdapter", lambda *args, **kwargs: UnavailableEmbedder()
    )
    index = tmp_path / "existing.sqlite"
    LocalVectorStore(index, embedder=HashEmbeddingAdapter()).build([
        {"id": "ICD-10-CM:I10", "text": "Essential hypertension"},
    ], rag.CATALOG_VERSION)

    result = rag.retrieve(
        "hypertension",
        [("ICD-10-CM", "I10", "Essential hypertension", "")],
        index_path=index,
    )

    assert result["strategy"] == "lexical"
    assert "Ollama is offline" in result["warning"]
    assert result["results"][0]["code"] == "I10"


def test_hybrid_retrieval_returns_provenance_and_explicit_version_fallback(tmp_path, monkeypatch):
    from backend.services.retrieval import rag
    from backend.services.retrieval.rag import CATALOG_VERSION, retrieve
    from backend.services.retrieval.embeddings import HashEmbeddingAdapter
    from backend.services.retrieval.vector_store import LocalVectorStore

    monkeypatch.setattr(rag, "_tabular_records", lambda: {})
    monkeypatch.setattr(rag, "_index_terms", lambda: {})
    monkeypatch.setattr(rag, "get_settings", lambda: {
        "local_embedding_model_name": "test-semantic",
        "local_model_url": "http://127.0.0.1:11434",
        "local_model_timeout": 12,
    })
    monkeypatch.setattr(
        rag, "OllamaEmbeddingAdapter",
        lambda *args, **kwargs: HashEmbeddingAdapter(),
    )
    codes = [
        ("ICD-10-CM", "I10", "Essential hypertension", "hypertension"),
        ("ICD-10-CM", "J18.9", "Pneumonia, unspecified organism", "pneumonia"),
    ]
    index = tmp_path / "local.sqlite"
    LocalVectorStore(index, embedder=HashEmbeddingAdapter()).build([
        {"id": "ICD-10-CM:I10", "text": "I10 Essential hypertension"},
        {"id": "ICD-10-CM:J18.9", "text": "J18.9 Pneumonia"},
    ], CATALOG_VERSION)

    hybrid = retrieve("hypertension", codes, index_path=index)
    assert hybrid["strategy"] == "hybrid-local"
    assert hybrid["results"][0]["code"] == "I10"
    assert hybrid["results"][0]["source_location"] == "code:I10"
    LocalVectorStore(index, embedder=HashEmbeddingAdapter()).build([], "stale")
    fallback = retrieve("hypertension", codes, index_path=index)
    assert fallback["strategy"] == "lexical"
    assert "lexical fallback" in fallback["warning"]


def test_icd_index_term_ranks_the_exact_diagnosis_before_broader_matches(monkeypatch, tmp_path):
    from backend.services.retrieval import rag

    monkeypatch.setattr(rag, "_tabular_records", lambda: {})
    monkeypatch.setattr(rag, "_index_terms", lambda: {
        "I10": [{"term": "Hypertension, hypertensive"}],
        "I1A0": [{"term": "Hypertension, hypertensive > resistant"}],
    })
    results = rag.retrieve(
        "hypertension",
        [
            ("ICD-10-CM", "I10", "Essential (primary) hypertension", ""),
            ("ICD-10-CM", "I1A0", "Resistant hypertension", ""),
        ],
        index_path=tmp_path / "missing.sqlite",
        allowed_types={"ICD-10-CM"},
    )

    assert results["results"][0]["code"] == "I10"


def test_dotted_icd_codes_keep_index_terms_and_tabular_provenance(monkeypatch, tmp_path):
    from backend.services.retrieval import rag

    monkeypatch.setattr(rag, "_tabular_records", lambda: {
        "J189": {
            "source_file": "tabular.xml",
            "source_location": "diag:J18.9",
            "catalog_version": "2027",
            "instructions": [{"type": "code_first", "text": "Code first example"}],
        },
    })
    monkeypatch.setattr(rag, "_index_terms", lambda: {
        "J189": [{
            "term": "Pulmonary infection",
            "source_file": "index.xml",
            "source_location": "term:pulmonary-infection",
        }],
    })

    result = rag.retrieve(
        "pulmonary infection",
        [("ICD-10-CM", "J18.9", "Pneumonia, unspecified", "")],
        index_path=tmp_path / "missing.sqlite",
        allowed_types={"ICD-10-CM"},
    )

    recommendation = result["results"][0]
    assert recommendation["code"] == "J18.9"
    assert recommendation["matched_index_terms"] == ["Pulmonary infection"]
    assert recommendation["source_file"] == "tabular.xml"
    assert recommendation["source_location"] == "diag:J18.9"
    assert recommendation["instructions"][0]["type"] == "code_first"


def test_workflow_excludes_negated_historical_and_wrong_category_candidates(monkeypatch, tmp_path):
    from backend.services.retrieval import rag
    from backend.services.workflow import graph as workflow

    monkeypatch.setattr(rag, "_tabular_records", lambda: {})
    monkeypatch.setattr(rag, "_index_terms", lambda: {})
    monkeypatch.setattr(workflow, "CODES", [
        ("ICD-10-CM", "I10", "Essential hypertension", "hypertension"),
        ("ICD-10-CM", "R05.9", "Cough, unspecified", "cough"),
        ("ICD-10-CM", "R50.9", "Fever, unspecified", "fever"),
        ("ICD-10-CM", "J18.9", "Pneumonia, unspecified organism", "pneumonia"),
        ("HCPCS", "G8768", "Hypertension quality measure", "hypertension"),
    ])

    class UnconfiguredModel:
        configured = False
        model = ""

    result = workflow.run_analysis_workflow(
        "Patient has hypertension and cough. No fever. History of pneumonia.",
        {"recommendations": []},
        model_client=UnconfiguredModel(),
        index_path=tmp_path / "missing.sqlite",
    )

    assert {item["code"] for item in result["recommendations"]} == {"I10", "R05.9"}
    assert [item["node"] for item in result["pipeline_trace"]] == [
        "parse", "retrieve", "reason", "validate",
    ]
    assert result["review_required"] is True
    assert result["pipeline_trace"][-1]["outputs"]["human_review_required"] is True


def test_langgraph_uses_available_local_model_only_for_retrieved_codes(monkeypatch, tmp_path):
    from backend.services.retrieval import rag
    from backend.services.workflow import graph as workflow
    from backend.services.clinical_nlp import extraction

    monkeypatch.setattr(extraction, "get_settings", lambda: {
        "clinical_nlp_model": "",
    })
    monkeypatch.setattr(rag, "get_settings", lambda: {
        "local_embedding_model_name": "",
        "local_model_url": "http://127.0.0.1:11434",
        "local_model_timeout": 12,
    })
    monkeypatch.setattr(rag, "_index_terms", lambda: {})
    monkeypatch.setattr(workflow, "CODES", [
        ("ICD-10-CM", "I10", "Essential hypertension", "hypertension"),
    ])

    class AvailableModel:
        configured = True
        model = "local-reasoner"

        def check_status(self):
            return {
                "connected": True,
                "model_available": True,
                "error": None,
            }

        def generate_json(self, prompt):
            assert '"code": "I10"' in prompt
            return {"selected_codes": ["I10"], "rationale": "Candidate supported."}

    result = workflow.run_analysis_workflow(
        "Patient has hypertension.",
        {"recommendations": []},
        model_client=AvailableModel(),
        index_path=tmp_path / "missing.sqlite",
    )

    assert result["model_status"] == "available"
    assert result["model_selected_codes"] == ["I10"]
    assert [item["node"] for item in result["pipeline_trace"]] == [
        "parse", "retrieve", "reason", "validate",
    ]
    assert result["pipeline_trace"][2]["status"] == "complete"
    assert result["recommendations"][0]["review_required"] is True


def test_langgraph_skips_model_call_when_ollama_is_unavailable(monkeypatch, tmp_path):
    from backend.services.clinical_nlp import extraction
    from backend.services.retrieval import rag
    from backend.services.workflow import graph as workflow

    monkeypatch.setattr(extraction, "get_settings", lambda: {
        "clinical_nlp_model": "",
    })
    monkeypatch.setattr(rag, "get_settings", lambda: {
        "local_embedding_model_name": "",
        "local_model_url": "http://127.0.0.1:11434",
        "local_model_timeout": 12,
    })
    monkeypatch.setattr(rag, "_index_terms", lambda: {})
    monkeypatch.setattr(workflow, "CODES", [
        ("ICD-10-CM", "I10", "Essential hypertension", "hypertension"),
    ])

    class OfflineModel:
        configured = True
        model = "local-model"

        def check_status(self):
            return {
                "connected": False,
                "model_available": False,
                "error": "Ollama is offline.",
            }

        def generate_json(self, prompt):
            raise AssertionError("No note should be sent to an unavailable model.")

    result = workflow.run_analysis_workflow(
        "Patient has hypertension.",
        {"recommendations": []},
        model_client=OfflineModel(),
        index_path=tmp_path / "missing.sqlite",
    )

    assert result["model_status"] == "unavailable"
    assert "Ollama is offline" in result["model_error"]
    assert result["recommendations"][0]["code"] == "I10"
    assert result["pipeline_trace"][2]["status"] == "warning"


def test_invalid_remote_ollama_configuration_keeps_deterministic_workflow(monkeypatch, tmp_path):
    from backend.services.clinical_nlp import extraction
    from backend.services.retrieval import rag
    from backend.services.workflow import graph as workflow

    monkeypatch.setattr(extraction, "get_settings", lambda: {
        "clinical_nlp_model": "",
    })
    monkeypatch.setattr(rag, "get_settings", lambda: {
        "local_embedding_model_name": "",
        "local_model_url": "https://example.invalid",
        "local_model_timeout": 12,
    })
    monkeypatch.setattr(rag, "_index_terms", lambda: {})
    monkeypatch.setattr(workflow, "CODES", [
        ("ICD-10-CM", "I10", "Essential hypertension", "hypertension"),
    ])

    def reject_remote_endpoint():
        raise ValueError("Clinical text may only be sent to a loopback model endpoint.")

    monkeypatch.setattr(workflow, "LocalModelClient", reject_remote_endpoint)
    result = workflow.run_analysis_workflow(
        "Patient has hypertension.",
        {"recommendations": []},
        index_path=tmp_path / "missing.sqlite",
    )

    assert result["model_status"] == "unavailable"
    assert "loopback model endpoint" in result["model_error"]
    assert result["recommendations"][0]["code"] == "I10"


def test_optional_huggingface_entities_keep_rule_assertion_context(monkeypatch):
    from backend.services.clinical_nlp import extraction

    text = "No hypertension. Possible asthma. History of renal fibrosis."
    start = text.index("renal fibrosis")
    monkeypatch.setattr(extraction, "get_settings", lambda: {
        "clinical_nlp_model": "local-disease-model",
    })
    monkeypatch.setattr(
        extraction, "_load_disease_ner",
        lambda model_id: lambda note: [{
            "entity_group": "Disease",
            "start": start,
            "end": start + len("renal fibrosis"),
            "score": 0.94,
        }],
    )

    result = extraction.extract_clinical_context(text, "synthetic.txt")
    mentions = {item.text.casefold(): item for item in result.mentions}

    assert mentions["hypertension"].assertion == "negated"
    assert mentions["asthma"].assertion == "uncertain"
    assert mentions["renal fibrosis"].assertion == "historical"
    assert mentions["renal fibrosis"].temporality == "historical"
    assert mentions["renal fibrosis"].experiencer == "patient"
    assert mentions["renal fibrosis"].confidence == 0.94
    assert mentions["renal fibrosis"].provenance == "huggingface:local-disease-model"


def test_optional_huggingface_failure_falls_back_to_rules_with_visible_error(monkeypatch):
    from backend.services.clinical_nlp import extraction

    monkeypatch.setattr(extraction, "get_settings", lambda: {
        "clinical_nlp_model": "missing-local-model",
    })

    def unavailable(model_id):
        raise extraction.ClinicalNLPUnavailable("model files are not cached")

    monkeypatch.setattr(extraction, "_load_disease_ner", unavailable)
    result = extraction.extract_clinical_context("Patient has hypertension.")

    assert result.nlp_status == "unavailable"
    assert "model files are not cached" in result.nlp_error
    assert result.mentions[0].text == "hypertension"
    assert result.review_required is True
    assert result.review_reasons[-1] == result.nlp_error


def test_context_extraction_caps_long_sentence_evidence_without_losing_span(monkeypatch):
    from backend.services.clinical_nlp import extraction

    monkeypatch.setattr(extraction, "get_settings", lambda: {
        "clinical_nlp_model": "",
    })
    text = ("unrelated " * 400) + "hypertension"
    mention = extraction.extract_clinical_context(text).mentions[0]

    assert len(mention.evidence) <= 2_000
    assert text[mention.start:mention.end].casefold() == "hypertension"
    assert "hypertension" in mention.evidence.casefold()


def test_langgraph_workflow_reports_unconfigured_and_invalid_local_models(monkeypatch, tmp_path):
    import pytest
    from backend.services.llm.client import LocalModelClient
    from backend.services.workflow import graph as workflow

    monkeypatch.setattr(workflow, "CODES", [
        ("ICD-10-CM", "I10", "Essential hypertension", "hypertension"),
    ])
    baseline = {
        "recommendations": [{
            "type": "ICD-10-CM", "code": "I10",
            "description": "Caller-supplied description", "confidence": 0.9,
            "evidence": "Patient has hypertension.",
        }],
    }

    class UnconfiguredModel:
        configured = False
        model = ""

    result = workflow.run_analysis_workflow(
        "Patient has hypertension.", baseline,
        model_client=UnconfiguredModel(), index_path=tmp_path / "missing.sqlite",
    )
    assert result["model_status"] == "unconfigured"
    assert result["review_required"] is True
    assert result["recommendations"][0]["source"]["source_location"] == "diag:I10"
    assert result["recommendations"][0]["description"] == "Essential hypertension"

    class InvalidModel:
        configured = True
        model = "local-demo"

        def generate_json(self, prompt):
            return {"selected_codes": ["NOT-A-CANDIDATE"]}

    invalid = workflow.run_analysis_workflow(
        "Patient has hypertension.", baseline,
        model_client=InvalidModel(), index_path=tmp_path / "missing.sqlite",
    )
    assert invalid["model_status"] == "invalid_response"
    assert invalid["recommendations"][0]["model_selected"] is False
    with pytest.raises(ValueError, match="loopback"):
        LocalModelClient(base_url="https://example.com", model="remote")


def test_workflow_drops_baseline_codes_not_present_in_official_catalog(monkeypatch, tmp_path):
    from backend.services.workflow import graph as workflow

    monkeypatch.setattr(workflow, "CODES", [])

    class Model:
        configured = True
        model = "local-model"

        def check_status(self):
            return {"connected": True, "model_available": True, "error": None}

        def generate_json(self, prompt):
            raise AssertionError("The model must not receive unverified baseline codes.")

    result = workflow.run_analysis_workflow(
        "Patient has hypertension.",
        {"recommendations": [{
            "type": "ICD-10-CM",
            "code": "FAKE",
            "description": "Invented code",
        }]},
        model_client=Model(),
        index_path=tmp_path / "missing.sqlite",
    )

    assert result["candidates"] == []
    assert result["recommendations"] == []
    assert result["model_status"] == "skipped"


def test_installed_icd10cm_catalog_contains_2027_codes():
    records = load_reference_codes()
    icd10_codes = {
        code for code_type, code, _, _ in records if code_type == "ICD-10-CM"
    }

    assert len(icd10_codes) == 74879
    assert "I10" in icd10_codes


def test_synthea_case_import_omits_patient_identifiers(tmp_path):
    (tmp_path / "conditions.csv").write_text(
        "START,STOP,PATIENT,ENCOUNTER,CODE,DESCRIPTION\n"
        "2020-01-02,,patient-secret,encounter-secret,123,Hypertension\n"
        "2020-01-02,,patient-secret,encounter-secret,456,Diabetes\n"
        "2020-01-03,,another-secret,another-encounter,789,Asthma\n",
        encoding="utf-8",
    )

    records = load_synthea_cases(tmp_path, limit=2)

    assert records == [
        {"date": "2020-01-02", "conditions": ["Hypertension", "Diabetes"]},
        {"date": "2020-01-03", "conditions": ["Asthma"]},
    ]
    assert "patient-secret" not in repr(records)
    assert "encounter-secret" not in repr(records)


def test_synthea_full_corpus_import_isolated_minimized_and_repeatable(tmp_path):
    import sqlite3
    from scripts.import_synthea import import_corpus

    source = tmp_path / "synthea"
    source.mkdir()
    (source / "patients.csv").write_text(
        "Id,FIRST,LAST,SSN\npatient-a,Name,Secret,123\n", encoding="utf-8"
    )
    (source / "encounters.csv").write_text(
        "Id,START,PATIENT,ENCOUNTERCLASS,CODE,DESCRIPTION\n"
        "encounter-a,2020-01-02T10:00:00Z,patient-a,ambulatory,185349003,Checkup\n",
        encoding="utf-8",
    )
    (source / "conditions.csv").write_text(
        "START,STOP,PATIENT,ENCOUNTER,CODE,DESCRIPTION\n"
        "2020-01-02,,patient-a,encounter-a,38341003,Hypertension\n",
        encoding="utf-8",
    )
    target = tmp_path / "synthetic.sqlite"

    result = import_corpus(source, target, batch_size=1)
    repeat = import_corpus(source, target, batch_size=1)

    assert result["synthetic"] is True
    assert result["patient_count"] == 1
    assert result["encounter_count"] == 1
    assert result["condition_count"] == 1
    assert repeat["condition_count"] == 1
    connection = sqlite3.connect(target)
    assert connection.execute("SELECT COUNT(*) FROM synthetic_conditions").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM synthetic_encounters").fetchone()[0] == 1
    metadata = dict(connection.execute("SELECT key,value FROM metadata"))
    columns = {row[1] for row in connection.execute("PRAGMA table_info(synthetic_patients)")}
    connection.close()
    assert metadata["dataset_version"] == "synthea_sample_data_csv_nov2021"
    assert metadata["synthetic"] == "true"
    assert columns == {"id"}
    assert "Name" not in repr(result)


def test_pdf_and_docx_ingestion_preserve_source_locations():
    from docx import Document
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
    })
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 12 Tf 72 720 Td (Patient has hypertension.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    pdf = BytesIO()
    writer.write(pdf)

    pdf_text, pdf_locations = extract_document_text("note.pdf", pdf.getvalue())

    document = Document()
    document.add_paragraph("Patient has hypertension.")
    document.add_paragraph("History reviewed with the patient.")
    docx = BytesIO()
    document.save(docx)
    docx_text, docx_locations = extract_document_text("note.docx", docx.getvalue())

    assert "hypertension" in pdf_text
    assert pdf_locations == [{"page": 1, "start": 0, "end": len(pdf_text)}]
    assert "History reviewed" in docx_text
    assert [item["paragraph"] for item in docx_locations] == [1, 2]
    for location in docx_locations:
        assert docx_text[location["start"]:location["end"]]


def test_document_ingestion_rejects_malformed_and_empty_files():
    import pytest
    from pypdf import PdfWriter

    with pytest.raises(ValueError, match="Unable to read PDF"):
        extract_document_text("bad.pdf", b"not a pdf document")
    with pytest.raises(ValueError, match="valid DOCX"):
        extract_document_text("bad.docx", b"not a zip archive")
    with pytest.raises(ValueError, match="at least 10 characters"):
        extract_document_text("empty.txt", b"short")
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("document-password")
    encrypted_pdf = BytesIO()
    writer.write(encrypted_pdf)
    with pytest.raises(ValueError, match="Password-protected"):
        extract_document_text("locked.pdf", encrypted_pdf.getvalue())


def test_docx_expansion_limit_is_checked_before_archive_validation(monkeypatch):
    import zipfile
    import pytest
    from backend.services import ingestion

    monkeypatch.setattr(ingestion, "MAX_DOCX_UNCOMPRESSED_BYTES", 10)
    document = BytesIO()
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", b"<document/>")
        archive.writestr("word/media/image.bin", b"12345678901")

    with pytest.raises(ValueError, match="Expanded DOCX"):
        extract_document_text("large.docx", document.getvalue())


def test_code_search_requires_a_query_and_caps_result_pages():
    assert codes() == []
    assert len(codes(q="a", limit=10_000)) <= 100


def test_app_settings_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("APP_NAME", "MediBridge Coders")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://demo:secret@ep-example.neon.tech/app"
    )
    monkeypatch.setenv("REQUIRE_POSTGRES", "true")
    monkeypatch.delenv("CLINICAL_DATA_APPROVED", raising=False)
    settings = get_settings()

    assert settings["app_name"] == "MediBridge Coders"
    assert settings["app_env"] == "production"
    assert settings["host"] == "127.0.0.1"
    assert settings["port"] == 8000
    assert settings["clinical_data_approved"] is False
    assert settings["analysis_gate_reasons"]
    assert settings["database_url"].startswith("postgresql://")
    assert settings["require_postgres"] is True


def test_render_blueprint_uses_free_web_service_and_secret_postgres_url():
    import yaml
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    blueprint = yaml.safe_load((root / "render.yaml").read_text(encoding="utf-8"))
    service = blueprint["services"][0]
    variables = {item["key"]: item for item in service["envVars"]}

    assert service["plan"] == "free"
    assert "disk" not in service
    assert variables["DATABASE_URL"]["sync"] is False
    assert variables["REQUIRE_POSTGRES"]["value"] == "true"
    assert variables["CLINICAL_DATA_APPROVED"]["value"] == "false"
    assert variables["SYNTHETIC_DEMO_ENABLED"]["value"] == "true"


def test_release_gate_requires_every_referenced_approval_and_opt_in(tmp_path, monkeypatch):
    from backend.config import REQUIRED_RELEASE_APPROVALS

    approval_file = tmp_path / "approvals.json"
    evidence = {
        key: {"approved": True, "reference": f"review-{index}"}
        for index, key in enumerate(REQUIRED_RELEASE_APPROVALS)
    }
    approval_file.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setenv("RELEASE_APPROVALS_PATH", str(approval_file))
    monkeypatch.setenv("CLINICAL_DATA_APPROVED", "false")
    assert get_settings()["clinical_data_approved"] is False
    monkeypatch.setenv("CLINICAL_DATA_APPROVED", "true")
    settings = get_settings()
    assert settings["clinical_data_approved"] is False
    assert any(
        "Organization-scoped clinical approval is not implemented." in reason
        for reason in settings["analysis_gate_reasons"]
    )
    evidence["clinician_signoff"]["reference"] = ""
    approval_file.write_text(json.dumps(evidence), encoding="utf-8")
    assert get_settings()["clinical_data_approved"] is False


def test_evaluation_runner_keeps_coding_accuracy_unavailable_without_adjudication():
    from scripts.evaluate_pipeline import evaluate

    report = evaluate()

    assert report["evaluation_type"] == "synthetic_demo_unadjudicated"
    assert report["case_count"] == 3
    assert report["coding_accuracy"] is None
    assert report["runtime"]["mean_context_extraction_seconds"] >= 0
    assert "not clinical accuracy" in report["warning"]


def test_coding_accuracy_requires_adjudicated_cases_and_reports_metrics():
    import pytest
    from backend.services.evaluation.coding_accuracy import evaluate_coding_accuracy

    pending = [{
        "case_id": "pending", "dataset_version": "demo-v1",
        "documented_text": "synthetic note", "expected_codes": [],
        "adjudication_status": "pending",
    }]
    with pytest.raises(ValueError, match="coder-adjudicated"):
        evaluate_coding_accuracy(pending, {})

    adjudicated = [{
        "case_id": "reviewed", "dataset_version": "reviewed-v1",
        "documented_text": "synthetic note", "expected_codes": ["I10", "E11.9"],
        "adjudication_status": "adjudicated",
        "adjudicator_reference": "review-board-1",
    }]
    metrics = evaluate_coding_accuracy(adjudicated, {
        "reviewed": {"predicted_codes": ["I10", "J18.9"], "coder_codes": ["I10", "E11.9"]},
    })
    assert metrics["exact_match_rate"] == 0
    assert metrics["partial_case_agreement_rate"] == 1
    assert metrics["code_precision"] == 0.5
    assert metrics["code_recall"] == 0.5
    assert metrics["reviewer_override_rate"] == 1


def test_evaluation_schemas_require_traceable_adjudication():
    import pytest
    from pydantic import ValidationError

    from backend.schemas import EvaluationCase, SourceEvidence

    with pytest.raises(ValidationError):
        EvaluationCase(
            case_id="case-1",
            dataset_version="synthea-2021",
            documented_text="Synthetic note content",
            expected_codes=["I10"],
            adjudication_status="adjudicated",
        )

    evidence = SourceEvidence(
        source_id="icd-10-cm-2027",
        catalog_type="ICD-10-CM",
        catalog_version="2027",
        source_file="tabular.xml",
        locator="I10",
        start=0,
        end=4,
    )
    assert evidence.end == 4
    with pytest.raises(ValidationError):
        SourceEvidence(
            source_id="icd-10-cm-2027",
            catalog_type="ICD-10-CM",
            catalog_version="2027",
            source_file="tabular.xml",
            locator="I10",
            start=4,
            end=0,
        )


def test_context_extraction_marks_negation_history_family_and_uncertainty():
    from backend.services.clinical_nlp.extraction import extract_clinical_context

    text = (
        "No hypertension today. History of asthma. "
        "Possible diabetes. Mother has asthma."
    )
    result = extract_clinical_context(text, "fixture.txt")
    states = [(item.text.lower(), item.assertion, item.experiencer) for item in result.mentions]

    assert ("hypertension", "negated", "patient") in states
    assert ("asthma", "historical", "patient") in states
    assert ("diabetes", "uncertain", "patient") in states
    assert ("asthma", "negated", "family_member") in states
    assert all(text[item.start:item.end].lower() == item.text.lower() for item in result.mentions)
    assert result.review_required


def test_context_extraction_flags_conflicts_and_pipeline_abstains_historical_codes(monkeypatch):
    from backend.services import pipeline

    monkeypatch.setattr(pipeline, 'CODES', [
        ('ICD-10-CM', 'I10', 'Essential hypertension', 'hypertension'),
    ])
    result = pipeline.analyze_text(
        "History of hypertension. Patient has hypertension today."
    )
    assert result['clinical_context']['conflicts'] == ['hypertension']
    assert result['review_required'] is True
    assert result['recommendations']
    historical_only = pipeline.analyze_text("History of hypertension.")
    assert historical_only['recommendations'] == []


def test_analyze_text_only_returns_matches_from_loaded_reference_data(monkeypatch):
    from backend.services import pipeline

    monkeypatch.setattr(pipeline, 'CODES', [
        ('ICD-10-CM', 'I10', 'Essential (primary) hypertension', 'hypertension'),
        ('ICD-10-CM', 'E11.9', 'Type 2 diabetes mellitus without complications', 'type 2 diabetes'),
    ])
    result = analyze_text(
        "Patient has hypertension and type 2 diabetes."
    )

    assert {item["code"] for item in result["recommendations"]} == {"I10", "E11.9"}
    assert all(item["code"] != "REVIEW" for item in result["recommendations"])


def test_analyze_text_does_not_invent_codes_when_reference_catalog_has_no_match(monkeypatch):
    from backend.services import pipeline

    monkeypatch.setattr(pipeline, 'CODES', [])
    result = analyze_text("Patient has hypertension and type 2 diabetes.")

    assert result["recommendations"] == []
    assert result["overall_confidence"] == 0
    assert any("active knowledge base" in gap for gap in result["gaps"])
