"""LocalAIModel.generate_json accepts json_schema/schema_name but cannot
enforce strict mode (no Ollama equivalent). Logs once per (model,
endpoint) so operators know they're on the prompt-only path, then
proceeds normally.

These tests verify ONLY the kwarg absorption + log behavior. The full
generate_json path requires a real Ollama server, so we don't exercise it
here — that's covered by the integration tier."""

from autonomous.ai.models import local_model
from autonomous.ai.models.local_model import LocalAIModel


def _local():
    """Bare LocalAIModel without DB persistence."""
    inst = LocalAIModel.__new__(LocalAIModel)
    # Initialize required DB fields to prevent descriptor errors
    object.__setattr__(inst, "_data", {"instructions": "You are a helpful AI.", "name": "test"})
    object.__setattr__(inst, "_dynamic_fields", {})
    object.__setattr__(inst, "_changed_fields", [])
    object.__setattr__(inst, "_initialised", True)
    object.__setattr__(inst, "_created", False)
    return inst


class TestJSONSchemaAbsorption:
    def setup_method(self):
        # Each test gets a fresh log-once cache
        local_model._STRUCTURED_OUTPUTS_LOGGED.clear()

    def test_signature_accepts_json_schema(self):
        # Inspect the signature directly — no network call needed.
        import inspect
        sig = inspect.signature(LocalAIModel.generate_json)
        assert "json_schema" in sig.parameters
        assert "schema_name" in sig.parameters
        assert sig.parameters["json_schema"].default is None
        assert sig.parameters["schema_name"].default == "response"

    def test_log_fires_once_per_model_endpoint(self, monkeypatch):
        local = _local()
        object.__setattr__(local, "_text_model", "test-model")
        object.__setattr__(local, "_ollama_url", "http://test-host:11434")

        captured_logs = []
        monkeypatch.setattr(
            local_model, "log",
            lambda msg, *a, **kw: captured_logs.append(str(msg)),
        )

        # Short-circuit the rest of generate_json by raising AFTER the
        # log block (we only care about the log behavior here).
        monkeypatch.setattr(
            local_model._SESSION, "post",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("stop"))
        )

        # First call: should log the unavailable marker.
        try:
            LocalAIModel.generate_json(
                local, "prompt", json_schema={"type": "object"}
            )
        except RuntimeError:
            pass

        unavailable_logs = [
            m for m in captured_logs if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m
        ]
        assert len(unavailable_logs) == 1, (
            f"Expected 1 unavailable marker, got: {unavailable_logs}"
        )

        # Second call: should NOT log again (same model+endpoint).
        try:
            LocalAIModel.generate_json(
                local, "prompt2", json_schema={"type": "string"}
            )
        except RuntimeError:
            pass

        unavailable_logs = [
            m for m in captured_logs if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m
        ]
        assert len(unavailable_logs) == 1

    def test_log_fires_for_different_model_endpoint_combos(self, monkeypatch):
        local = _local()
        object.__setattr__(local, "_text_model", "model-a")
        object.__setattr__(local, "_ollama_url", "http://host-a:11434")

        captured_logs = []
        monkeypatch.setattr(
            local_model, "log",
            lambda msg, *a, **kw: captured_logs.append(str(msg)),
        )
        monkeypatch.setattr(
            local_model._SESSION, "post",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("stop"))
        )

        try:
            LocalAIModel.generate_json(local, "p", json_schema={"type": "object"})
        except RuntimeError:
            pass

        # Change model+endpoint — new combo should re-log.
        object.__setattr__(local, "_text_model", "model-b")
        try:
            LocalAIModel.generate_json(local, "p", json_schema={"type": "object"})
        except RuntimeError:
            pass

        unavailable_logs = [
            m for m in captured_logs if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m
        ]
        assert len(unavailable_logs) == 2

    def test_no_log_when_json_schema_is_none(self, monkeypatch):
        local = _local()
        object.__setattr__(local, "_text_model", "test-model")
        object.__setattr__(local, "_ollama_url", "http://test-host:11434")

        captured_logs = []
        monkeypatch.setattr(
            local_model, "log",
            lambda msg, *a, **kw: captured_logs.append(str(msg)),
        )
        monkeypatch.setattr(
            local_model._SESSION, "post",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("stop"))
        )

        try:
            LocalAIModel.generate_json(local, "prompt")  # no json_schema
        except RuntimeError:
            pass

        unavailable_logs = [
            m for m in captured_logs if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m
        ]
        assert len(unavailable_logs) == 0
