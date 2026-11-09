import os
import json
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


REQUIRED_RELEASE_APPROVALS = (
    "clinical_governance",
    "privacy_security_review",
    "clinician_signoff",
    "local_model_verified",
    "evaluation_passed",
    "retention_backup_review",
)


def load_release_approvals(path):
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, ["Release approval record is missing."]
    except (OSError, json.JSONDecodeError) as error:
        return False, [f"Release approval record could not be read: {error}"]
    if not isinstance(payload, dict):
        return False, ["Release approval record must be a JSON object."]
    blockers = [
        f"Missing approved evidence: {key}"
        for key in REQUIRED_RELEASE_APPROVALS
        if not isinstance(payload.get(key), dict)
        or payload[key].get("approved") is not True
        or not str(payload[key].get("reference", "")).strip()
    ]
    return not blockers, blockers
load_dotenv(BASE_DIR / '.env')


def get_settings() -> dict:
    """Load app settings from environment variables with sane defaults."""
    app_env = os.getenv("APP_ENV", "development").lower()
    synthetic_demo_value = os.getenv("SYNTHETIC_DEMO_ENABLED")
    synthetic_demo_requested = (synthetic_demo_value or "").lower() in {
        "1", "true", "yes", "on"
    }
    synthetic_demo_enabled = (
        synthetic_demo_requested
        if synthetic_demo_value is not None
        else app_env != "production"
    )
    database_path = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "database" / "medibridge.db"))).expanduser()
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path
    approvals_path = Path(os.getenv(
        "RELEASE_APPROVALS_PATH", str(BASE_DIR / "release-approvals.example.json")
    )).expanduser()
    if not approvals_path.is_absolute():
        approvals_path = BASE_DIR / approvals_path
    approvals_complete, approval_blockers = load_release_approvals(approvals_path)
    requested_approval = os.getenv("CLINICAL_DATA_APPROVED", "false").lower() in {
        "1", "true", "yes", "on"
    }
    release_blockers = list(approval_blockers)
    if not requested_approval:
        release_blockers.insert(0, "CLINICAL_DATA_APPROVED is false.")
    if synthetic_demo_requested:
        release_blockers.insert(0, "Synthetic-only demo mode disables clinical document analysis.")
    release_evidence_passes = (
        requested_approval
        and approvals_complete
        and not synthetic_demo_requested
    )
    # There is not yet an organization membership/approval policy to authorize
    # clinical processing. Keep the route gate closed until that control exists.
    organization_approval_passes = False
    if not organization_approval_passes:
        release_blockers.append(
            "Organization-scoped clinical approval is not implemented."
        )
    return {
        "app_name": os.getenv("APP_NAME", "MediBridge"),
        "app_env": app_env,
        "synthetic_demo_enabled": synthetic_demo_enabled,
        "host": os.getenv("HOST", "127.0.0.1"),
        "port": int(os.getenv("PORT", "8000")),
        "debug": os.getenv("DEBUG", "false").lower() in {"1", "true", "yes", "on"},
        "clinical_data_approved": (
            release_evidence_passes and organization_approval_passes
        ),
        "release_approvals_path": approvals_path,
        "analysis_gate_reasons": release_blockers,
        "local_model_url": os.getenv("LOCAL_MODEL_URL", "http://127.0.0.1:11434"),
        "local_model_name": os.getenv("LOCAL_MODEL_NAME", ""),
        "local_embedding_model_name": os.getenv("OLLAMA_EMBEDDING_MODEL", ""),
        "local_model_timeout": float(os.getenv("LOCAL_MODEL_TIMEOUT", "12")),
        "clinical_nlp_model": os.getenv("CLINICAL_NLP_MODEL", ""),
        "vector_index_path": Path(os.getenv(
            "VECTOR_INDEX_PATH", str(BASE_DIR / "data" / "retrieval" / "medibridge.sqlite")
        )).expanduser(),
        "allowed_origins": [
            origin.strip()
            for origin in os.getenv(
                "ALLOWED_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:8000,http://127.0.0.1:3000",
            ).split(",")
            if origin.strip()
        ],
        "uploads_dir": BASE_DIR / "uploads",
        "database_path": database_path,
        "database_url": os.getenv("DATABASE_URL", "").strip() or None,
        "require_postgres": os.getenv("REQUIRE_POSTGRES", "false").lower() in {
            "1", "true", "yes", "on"
        },
    }
