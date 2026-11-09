"""Keep pytest away from repository-resident application and retrieval data."""

import os
import tempfile
from pathlib import Path


_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="medibridge-pytest-"))

# backend.main initializes its database at import time, before ordinary test
# fixtures run. Set isolated paths here so collection and startup cannot touch
# the user's database or retrieval index.
os.environ["DATABASE_PATH"] = str(_TEST_DATA_DIR / "application.sqlite")
os.environ["VECTOR_INDEX_PATH"] = str(_TEST_DATA_DIR / "retrieval.sqlite")
os.environ.pop("DATABASE_URL", None)
os.environ["CLINICAL_DATA_APPROVED"] = "false"
os.environ["SYNTHETIC_DEMO_ENABLED"] = "false"
os.environ["RELEASE_APPROVALS_PATH"] = str(
    _TEST_DATA_DIR / "release-approvals-not-configured.json"
)
