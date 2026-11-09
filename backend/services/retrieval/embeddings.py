"""Local embeddings for retrieval; hash features are an explicit test fallback."""
import hashlib
import json
import math
import re
import urllib.error
import urllib.request


class HashEmbeddingAdapter:
    def __init__(self, dimensions=64):
        if dimensions < 16:
            raise ValueError("Embedding dimension must be at least 16.")
        self.dimensions = dimensions
        self.model_id = f"local-token-hash-v1-{dimensions}"

    def embed(self, text):
        tokens = re.findall(r"[a-z0-9]+", text.casefold())
        features = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = sum(value * value for value in vector) ** 0.5
        return [value / norm for value in vector] if norm else vector


class OllamaEmbeddingAdapter:
    def __init__(self, model, base_url="http://127.0.0.1:11434", timeout=12):
        from ..llm.client import LocalModelClient

        self.client = LocalModelClient(base_url=base_url, model=model, timeout=timeout)
        if not self.client.configured:
            raise ValueError("An installed local embedding model name is required.")
        self.model_id = f"ollama-local:{model}"
        self._resolved = False

    def ensure_available(self):
        if self._resolved:
            return
        status = self.client.check_status()
        if not status["connected"]:
            from ..llm.client import ModelUnavailable
            raise ModelUnavailable(status["error"] or "Local embedding service is unavailable.")
        if not status["model_available"]:
            from ..llm.client import ModelUnavailable
            raise ModelUnavailable(status["error"] or "Local embedding model is unavailable.")
        digest = status["model_digest"]
        if not digest:
            from ..llm.client import ModelUnavailable
            raise ModelUnavailable(
                "Local embedding service did not report a model digest; rebuild is unsafe."
            )
        self.model_id = f"ollama-local:{self.client.model}@{digest}"
        self._resolved = True

    def embed(self, text):
        return self.embed_many([text])[0]

    def embed_many(self, texts):
        if not texts:
            return []
        self.ensure_available()
        request = urllib.request.Request(
            self.client.base_url + "/api/embed",
            data=json.dumps({"model": self.client.model, "input": texts}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.client.timeout) as response:
                body = json.loads(response.read(4_000_001).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError,
                UnicodeDecodeError) as error:
            from ..llm.client import ModelUnavailable
            raise ModelUnavailable(f"Local embedding request failed: {error}") from error
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        if (
            not isinstance(vectors, list)
            or len(vectors) != len(texts)
            or any(not isinstance(vector, list) for vector in vectors)
        ):
            from ..llm.client import ModelUnavailable
            raise ModelUnavailable("Local embedding model returned an invalid vector batch.")
        normalized = []
        for raw_vector in vectors:
            try:
                vector = [float(value) for value in raw_vector]
            except (TypeError, ValueError) as error:
                from ..llm.client import ModelUnavailable
                raise ModelUnavailable(
                    "Local embedding model returned a non-numeric vector."
                ) from error
            if not vector or any(not math.isfinite(value) for value in vector):
                from ..llm.client import ModelUnavailable
                raise ModelUnavailable("Local embedding model returned an invalid vector.")
            norm = math.sqrt(sum(value * value for value in vector))
            if norm == 0:
                from ..llm.client import ModelUnavailable
                raise ModelUnavailable("Local embedding model returned a zero vector.")
            normalized.append([value / norm for value in vector])
        dimensions = {len(vector) for vector in normalized}
        if len(dimensions) != 1:
            from ..llm.client import ModelUnavailable
            raise ModelUnavailable("Local embedding model returned inconsistent dimensions.")
        return normalized
