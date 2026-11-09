"""Atomic, versioned SQLite vector index using local semantic embeddings."""
from itertools import islice
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

class IndexVersionMismatch(ValueError):
    pass


class LocalVectorStore:
    def __init__(self, path, embedder=None):
        self.path = Path(path)
        if embedder is None:
            raise ValueError("An explicit local embedding adapter is required.")
        self.embedder = embedder

    def build(self, documents, catalog_version):
        ensure_available = getattr(self.embedder, "ensure_available", None)
        if ensure_available:
            ensure_available()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=self.path.stem + "-", suffix=".sqlite.tmp", dir=self.path.parent
        )
        os.close(descriptor)
        try:
            connection = sqlite3.connect(temporary)
            try:
                connection.executescript("""
                    CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE documents(
                        id TEXT PRIMARY KEY, text TEXT NOT NULL,
                        metadata_json TEXT NOT NULL, vector_json TEXT NOT NULL
                    );
                    CREATE VIRTUAL TABLE documents_fts USING fts5(id UNINDEXED, text);
                """)
                count = 0
                with connection:
                    connection.executemany(
                        "INSERT INTO metadata(key,value) VALUES (?,?)",
                        [
                            ("catalog_version", catalog_version),
                            ("embedding_model", self.embedder.model_id),
                        ],
                    )
                    document_iterator = iter(documents)
                    while batch := list(islice(document_iterator, 32)):
                        prepared = [
                            (str(document["id"]), str(document["text"]).strip(), document)
                            for document in batch
                        ]
                        if any(not doc_id or not text for doc_id, text, _ in prepared):
                            raise ValueError("Indexed documents need a non-empty id and text.")
                        texts = [text for _, text, _ in prepared]
                        embed_many = getattr(self.embedder, "embed_many", None)
                        vectors = (
                            embed_many(texts)
                            if embed_many else [self.embedder.embed(text) for text in texts]
                        )
                        if len(vectors) != len(prepared):
                            raise ValueError("Embedding adapter returned a mismatched batch.")
                        for (doc_id, text, document), vector in zip(prepared, vectors):
                            cursor = connection.execute(
                                "INSERT INTO documents VALUES (?,?,?,?)",
                                (doc_id, text, json.dumps(document.get("metadata", {})),
                                 json.dumps(vector, separators=(",", ":"))),
                            )
                            connection.execute(
                                "INSERT INTO documents_fts(rowid,id,text) VALUES (?,?,?)",
                                (cursor.lastrowid, doc_id, text),
                            )
                            count += 1
                    connection.execute(
                        "INSERT INTO metadata(key,value) VALUES ('document_count',?)",
                        (str(count),),
                    )
            finally:
                connection.close()
            os.replace(temporary, self.path)
        except Exception:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise
        return count

    def search(self, query, catalog_version, limit=10):
        if not self.path.is_file():
            return []
        ensure_available = getattr(self.embedder, "ensure_available", None)
        if ensure_available:
            ensure_available()
        connection = sqlite3.connect(self.path)
        try:
            metadata = dict(connection.execute("SELECT key,value FROM metadata"))
            if metadata.get("catalog_version") != catalog_version:
                raise IndexVersionMismatch(
                    f"Index catalog version {metadata.get('catalog_version')} does not match {catalog_version}."
                )
            if metadata.get("embedding_model") != self.embedder.model_id:
                raise IndexVersionMismatch("Index embedding model does not match the active adapter.")
            query_vector = self.embedder.embed(query)
            results = []
            rows = connection.execute(
                "SELECT id,text,metadata_json,vector_json FROM documents"
            )
            for doc_id, text, metadata_json, vector_json in rows:
                vector = json.loads(vector_json)
                if len(vector) != len(query_vector) or any(
                    not math.isfinite(float(value)) for value in vector
                ):
                    raise ValueError(f"Corrupt vector found for document {doc_id}.")
                score = sum(float(left) * float(right)
                            for left, right in zip(query_vector, vector))
                results.append({
                    "id": doc_id,
                    "text": text,
                    "metadata": json.loads(metadata_json),
                    "score": score,
                })
            results.sort(key=lambda item: (-item["score"], item["id"]))
            return results[:max(1, min(int(limit), 100))]
        finally:
            connection.close()

    def check_integrity(self):
        if not self.path.is_file():
            return {"ok": False, "documents": 0, "error": "Index does not exist."}
        connection = sqlite3.connect(self.path)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            return {"ok": result == "ok", "documents": count, "error": None if result == "ok" else result}
        finally:
            connection.close()
