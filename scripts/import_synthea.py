"""Import a privacy-minimized Synthea corpus into a separate synthetic SQLite store."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

BASE = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BASE / "data" / "synthea-demo.sqlite"
DATASET_VERSION = "synthea_sample_data_csv_nov2021"


def _key(value: str) -> str:
    return hashlib.sha256((DATASET_VERSION + ":" + value).encode("utf-8")).hexdigest()


def import_corpus(source, database=DEFAULT_DATABASE, batch_size=2000):
    source = Path(source)
    patients_file = source / "patients.csv"
    encounters_file = source / "encounters.csv"
    conditions_file = source / "conditions.csv"
    for path in (patients_file, encounters_file, conditions_file):
        if not path.is_file():
            raise FileNotFoundError(f"Required Synthea file is missing: {path}")
    if batch_size < 1:
        raise ValueError("Batch size must be a positive integer.")

    patients = set()
    with patients_file.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            patient_id = row.get("Id", "").strip()
            if patient_id:
                patients.add(patient_id)

    encounters = []
    encounter_keys = set()
    with encounters_file.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            source_id = row.get("Id", "").strip()
            patient_id = row.get("PATIENT", "").strip()
            if not source_id or not patient_id:
                continue
            encounter_keys.add(source_id)
            encounters.append((
                _key(source_id), _key(patient_id), row.get("START", "")[:10],
                row.get("ENCOUNTERCLASS", ""), row.get("CODE", ""),
                row.get("DESCRIPTION", ""),
            ))

    conditions = []
    with conditions_file.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            encounter_id = row.get("ENCOUNTER", "").strip()
            patient_id = row.get("PATIENT", "").strip()
            if not encounter_id or not patient_id or encounter_id not in encounter_keys:
                continue
            conditions.append((
                _key(encounter_id), _key(patient_id), row.get("START", "")[:10],
                row.get("STOP", "")[:10] or None, row.get("CODE", ""),
                row.get("DESCRIPTION", ""),
            ))

    database = Path(database).expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=database.stem + "-", suffix=".sqlite.tmp", dir=database.parent
    )
    os.close(handle)
    try:
        connection = sqlite3.connect(temporary_name)
        try:
            connection.executescript("""
                PRAGMA journal_mode=DELETE;
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE synthetic_patients(id TEXT PRIMARY KEY);
                CREATE TABLE synthetic_encounters(
                    id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES synthetic_patients(id),
                    date TEXT NOT NULL, encounter_class TEXT, code TEXT, description TEXT
                );
                CREATE TABLE synthetic_conditions(
                    id INTEGER PRIMARY KEY, encounter_id TEXT NOT NULL REFERENCES synthetic_encounters(id),
                    patient_id TEXT NOT NULL REFERENCES synthetic_patients(id),
                    start_date TEXT NOT NULL, stop_date TEXT, code TEXT, description TEXT
                );
                CREATE INDEX idx_synthea_conditions_encounter ON synthetic_conditions(encounter_id);
            """)
            patient_keys = sorted({_key(value) for value in patients} |
                                  {row[1] for row in encounters})
            with connection:
                connection.executemany(
                    "INSERT INTO synthetic_patients(id) VALUES (?)",
                    ((item,) for item in patient_keys),
                )
                for start in range(0, len(encounters), batch_size):
                    connection.executemany(
                        "INSERT INTO synthetic_encounters "
                        "(id,patient_id,date,encounter_class,code,description) "
                        "VALUES (?,?,?,?,?,?)",
                        encounters[start:start + batch_size],
                    )
                for start in range(0, len(conditions), batch_size):
                    connection.executemany(
                        "INSERT INTO synthetic_conditions "
                        "(encounter_id,patient_id,start_date,stop_date,code,description) "
                        "VALUES (?,?,?,?,?,?)",
                        conditions[start:start + batch_size],
                    )
                manifest = {
                    "dataset_version": DATASET_VERSION,
                    "synthetic": "true",
                    "patient_count": str(len(patient_keys)),
                    "encounter_count": str(len(encounters)),
                    "condition_count": str(len(conditions)),
                    "source_name": source.name,
                }
                connection.executemany(
                    "INSERT INTO metadata(key,value) VALUES (?,?)", manifest.items()
                )
        finally:
            connection.close()
        os.replace(temporary_name, database)
    except BaseException:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise
    return {
        "dataset_version": DATASET_VERSION,
        "synthetic": True,
        "patient_count": len(patient_keys),
        "encounter_count": len(encounters),
        "condition_count": len(conditions),
        "database": str(database),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Folder containing Synthea patients/encounters/conditions CSV files")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--batch-size", type=int, default=2000)
    args = parser.parse_args()
    result = import_corpus(args.source, args.database, args.batch_size)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
