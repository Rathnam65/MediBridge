"""Create one-time demo coder accounts and privacy-minimized Synthea cases."""
import csv
from datetime import datetime
import json
from pathlib import Path
import secrets
import sys
import uuid

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from backend.database import conn
from backend.main import case_review_status, case_schedule, hash_password
from backend.services.pipeline import analyze_text

CODER_COUNT = 10
CASE_COUNT = 15
EMAIL_DOMAIN = "demo.medibridge.test"


def load_synthea_cases(source, limit=CASE_COUNT):
    """Read encounter conditions without importing patient identifiers."""
    path = Path(source) / "conditions.csv"
    cases = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            encounter = row.get("ENCOUNTER", "").strip()
            description = row.get("DESCRIPTION", "").strip()
            start = row.get("START", "").strip()
            if not encounter or not description or not start:
                continue
            item = cases.setdefault(encounter, {"date": start[:10], "conditions": []})
            if description not in item["conditions"]:
                item["conditions"].append(description)
    if len(cases) < limit:
        raise ValueError(f"Expected at least {limit} encounters with conditions in {path}")
    return list(cases.values())[:limit]


def main():
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/seed_synthea_demo.py "
            "<path-to-synthea-csv-folder>",
            file=sys.stderr,
        )
        return 2

    sample_cases = load_synthea_cases(sys.argv[1])
    credentials = [
        {
            "name": f"Demo Coder {index:02}",
            "email": f"coder{index:02}@{EMAIL_DOMAIN}",
            "password": secrets.token_urlsafe(18),
            "id": uuid.uuid4().hex,
        }
        for index in range(1, CODER_COUNT + 1)
    ]
    now = datetime.now().astimezone()
    assigned_at, deadline_at = case_schedule(now)
    connection = conn()
    try:
        existing = connection.execute(
            "SELECT email FROM users WHERE email IN ({})".format(
                ",".join("?" for _ in credentials)
            ),
            [coder["email"] for coder in credentials],
        ).fetchall()
        if existing:
            emails = ", ".join(row["email"] for row in existing)
            raise RuntimeError(
                f"Demo account(s) already exist ({emails}); refusing to reset passwords."
            )

        with connection:
            for coder in credentials:
                connection.execute(
                    "INSERT INTO users(id,email,full_name,password_hash,created_at) "
                    "VALUES (?,?,?,?,?)",
                    (
                        coder["id"],
                        coder["email"],
                        coder["name"],
                        hash_password(coder["password"]),
                        assigned_at,
                    ),
                )

            for index, sample in enumerate(sample_cases):
                note = (
                    f"Synthetic Synthea encounter date: {sample['date']}. "
                    f"Documented conditions: {'; '.join(sample['conditions'][:8])}."
                )
                result = analyze_text(note)
                coder = credentials[index % CODER_COUNT]
                case_id = f"SYN-{uuid.uuid4().hex[:10].upper()}"
                status = case_review_status(result, {
                    "review_threshold": 85,
                    "flag_low_confidence": True,
                })
                connection.execute(
                    "INSERT INTO cases("
                    "id,user_id,created_at,assigned_at,deadline_at,document_name,"
                    "source,text,status,overall_confidence,extracted_json,"
                    "recommendations_json,gaps_json"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        case_id,
                        coder["id"],
                        assigned_at,
                        assigned_at,
                        deadline_at,
                        f"Synthea sample encounter {index + 1:02}",
                        "synthea_demo",
                        note,
                        status,
                        result["overall_confidence"],
                        json.dumps(result["extracted"]),
                        json.dumps(result["recommendations"]),
                        json.dumps(result["gaps"]),
                    ),
                )
                connection.execute(
                    "INSERT INTO activity(user_id,created_at,kind,title,detail) "
                    "VALUES (?,?,?,?,?)",
                    (
                        coder["id"],
                        assigned_at,
                        "assignment",
                        f"Case {case_id} assigned",
                        "Synthetic Synthea encounter added for demo workflow testing.",
                    ),
                )
    finally:
        connection.close()

    print(f"Created {CODER_COUNT} demo coder accounts and {CASE_COUNT} cases.")
    print(f"All cases are assigned today and due {deadline_at}.")
    print("Credentials are shown once; save this output securely:")
    for coder in credentials:
        print(f"{coder['name']}\t{coder['email']}\t{coder['password']}")
    print("Synthea patient identifiers and demographics were not imported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
