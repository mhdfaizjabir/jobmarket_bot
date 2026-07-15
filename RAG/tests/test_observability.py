"""Regression test for the Langfuse SDK v4 API mismatch found during Sprint 10
activation: observability.py called `lf.start_span(name=..., metadata=...)`,
a method that no longer exists on the installed `langfuse` package (renamed
to `start_observation`). The old call was silently swallowed by
trace_llm_call's own try/except, so Langfuse looked "ACTIVE" in the startup
log but never actually sent a single trace. This test locks in the correct
method name and call shape using a fake client — no real Langfuse credentials
needed, since _langfuse_client() is mocked out entirely."""

from unittest.mock import MagicMock

import observability


def test_trace_llm_call_uses_start_observation_not_start_span(monkeypatch):
    fake_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_observation.return_value = fake_span
    monkeypatch.setattr(observability, "_langfuse_client", lambda: fake_client)

    with observability.trace_llm_call("chat_completion", model="fanar/Fanar-C-2-27B"):
        pass

    fake_client.start_observation.assert_called_once()
    _, kwargs = fake_client.start_observation.call_args
    assert kwargs["name"] == "chat_completion"
    assert kwargs["as_type"] == "generation"
    assert kwargs["metadata"] == {"model": "fanar/Fanar-C-2-27B"}
    # start_span (the old, now-nonexistent method) must never be called.
    assert not fake_client.start_span.called
    fake_span.end.assert_called_once()


def test_trace_llm_call_ends_span_even_if_body_raises(monkeypatch):
    fake_span = MagicMock()
    fake_client = MagicMock()
    fake_client.start_observation.return_value = fake_span
    monkeypatch.setattr(observability, "_langfuse_client", lambda: fake_client)

    try:
        with observability.trace_llm_call("chat_completion"):
            raise ValueError("boom")
    except ValueError:
        pass

    fake_span.end.assert_called_once()


def test_trace_llm_call_works_with_no_langfuse_client(monkeypatch):
    # Mirrors the default (unconfigured) posture — must not raise.
    monkeypatch.setattr(observability, "_langfuse_client", lambda: None)
    with observability.trace_llm_call("chat_completion"):
        pass


def test_trace_llm_call_degrades_if_start_observation_raises(monkeypatch):
    fake_client = MagicMock()
    fake_client.start_observation.side_effect = RuntimeError("network down")
    monkeypatch.setattr(observability, "_langfuse_client", lambda: fake_client)

    # Must not propagate the Langfuse-side error into the caller's LLM call.
    with observability.trace_llm_call("chat_completion"):
        pass
