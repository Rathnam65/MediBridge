"""Minimal Ollama-compatible JSON client that refuses non-loopback hosts."""
import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request

from ...config import get_settings


class ModelUnavailable(RuntimeError):
    pass


class LocalModelClient:
    def __init__(self, base_url=None, model=None, timeout=None):
        settings = get_settings()
        self.base_url = (base_url or settings["local_model_url"]).rstrip("/")
        self.model = model if model is not None else settings["local_model_name"]
        self.timeout = float(timeout if timeout is not None else settings["local_model_timeout"])
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Local model URL must be an HTTP(S) loopback URL.")
        try:
            local_host = parsed.hostname.casefold() == "localhost" or ipaddress.ip_address(
                parsed.hostname
            ).is_loopback
        except ValueError:
            local_host = False
        if not local_host or parsed.username or parsed.password:
            raise ValueError("Clinical text may only be sent to a loopback model endpoint.")
        if not 0 < self.timeout <= 120:
            raise ValueError("Local model timeout must be between 0 and 120 seconds.")

    @property
    def configured(self):
        return bool(self.model.strip())

    def generate_json(self, prompt):
        if not self.configured:
            raise ModelUnavailable(
                "Local model is not configured. Set LOCAL_MODEL_NAME after installing a local Ollama model."
            )
        request = urllib.request.Request(
            self.base_url + "/api/generate",
            data=json.dumps({
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read(2_000_001).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError,
                UnicodeDecodeError) as error:
            raise ModelUnavailable(f"Local model request failed: {error}") from error
        if not isinstance(body, dict):
            raise ModelUnavailable("Local model returned an invalid response object.")
        generated = body.get("response")
        if not isinstance(generated, str):
            raise ModelUnavailable("Local model returned no response text.")
        try:
            result = json.loads(generated)
        except json.JSONDecodeError as error:
            raise ModelUnavailable("Local model returned invalid JSON.") from error
        if not isinstance(result, dict):
            raise ModelUnavailable("Local model JSON response must be an object.")
        return result

    def check_status(self):
        configured = self.configured
        request = urllib.request.Request(self.base_url + "/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read(2_000_001).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError,
                UnicodeDecodeError) as error:
            return {
                "configured": configured,
                "connected": False,
                "model_available": False,
                "model": self.model or None,
                "model_digest": None,
                "error": f"Local model service is unavailable: {error}",
            }
        models = body.get("models") if isinstance(body, dict) else None
        if not isinstance(models, list):
            return {
                "configured": configured,
                "connected": True,
                "model_available": False,
                "model": self.model or None,
                "model_digest": None,
                "error": "Local model service returned an invalid model list.",
            }
        if not configured:
            return {
                "configured": False,
                "connected": True,
                "model_available": False,
                "model": None,
                "model_digest": None,
                "error": "No local reasoning model is configured.",
            }

        def normalized(name):
            value = str(name or "").strip()
            return value if ":" in value else value + ":latest"

        configured_name = normalized(self.model)
        installed = next(
            (
                item for item in models
                if isinstance(item, dict)
                and normalized(item.get("name") or item.get("model")) == configured_name
            ),
            None,
        )
        return {
            "configured": True,
            "connected": True,
            "model_available": installed is not None,
            "model": self.model,
            "model_digest": installed.get("digest") if installed else None,
            "error": None if installed else f"Configured model '{self.model}' is not installed.",
        }
