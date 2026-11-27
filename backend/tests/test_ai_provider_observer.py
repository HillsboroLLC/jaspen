"""I4: every provider request is announced and reported to an installed observer."""

from types import SimpleNamespace

import pytest

from app.ai_providers import anthropic as anthropic_provider
from app.ai_providers import gemini as gemini_provider
from app.ai_providers import observer


class Recorder:
    def __init__(self, refuse=False):
        self.calls, self.refuse = [], refuse

    def before_call(self, provider, model, request):
        if self.refuse:
            raise RuntimeError("refused before sending")
        self.calls.append({"provider": provider, "model": model, **request})
        return len(self.calls) - 1

    def after_call(self, handle, outcome, *, input_tokens, output_tokens, error=None, status_code=None,
                   request_id=None):
        self.calls[handle].update(outcome=outcome, input_tokens=input_tokens, output_tokens=output_tokens,
                                  error=type(error).__name__ if error else None)


def _message(input_tokens=11, output_tokens=7):
    return SimpleNamespace(id="msg_1", usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
                           content=[], stop_reason="end_turn")


class FakeStream:
    def __init__(self, events):
        self._events = events

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return _message(20, 30)


class FakeManager:
    def __init__(self, stream):
        self.stream, self.exited = stream, None

    def __enter__(self):
        return self.stream

    def __exit__(self, exc_type, exc, tb):
        self.exited = exc_type
        return False


class FakeClient:
    def __init__(self, failures=()):
        self.failures, self.sent = set(failures), []
        self.messages = self

    def create(self, *, model, **kwargs):
        self.sent.append(model)
        if model in self.failures:
            raise RuntimeError(f"{model} down")
        return _message()

    def stream(self, *, model, **kwargs):
        self.sent.append(model)
        return FakeManager(FakeStream([]))


KW = dict(max_tokens=500, system="sys", messages=[{"role": "user", "content": "hi"}])


def test_without_an_observer_nothing_changes():
    client = FakeClient()
    response, model = anthropic_provider.message_create(client, candidates=["m1"], **KW)
    assert model == "m1" and response.id == "msg_1" and observer.current() is None


def test_each_candidate_request_is_announced_and_reported():
    client, recorder = FakeClient(failures={"m1"}), Recorder()
    with observer.observing(recorder):
        _response, model = anthropic_provider.message_create(client, candidates=["m1", "m2"], **KW)
    assert model == "m2"
    assert [(c["model"], c["outcome"], c["input_tokens"]) for c in recorder.calls] == [
        ("m1", "failed", None), ("m2", "succeeded", 11)]
    assert recorder.calls[0]["max_output_tokens"] == 500 and recorder.calls[0]["input_characters"] > 0


def test_a_refusal_before_sending_sends_nothing():
    client = FakeClient()
    with observer.observing(Recorder(refuse=True)), pytest.raises(RuntimeError, match="refused before sending"):
        anthropic_provider.message_create(client, candidates=["m1"], **KW)
    assert client.sent == []


def test_a_stream_reports_its_final_usage_or_its_abandonment():
    recorder = Recorder()
    with observer.observing(recorder):
        manager, _model = anthropic_provider.message_create(FakeClient(), candidates=["m1"], stream=True, **KW)
        with manager:
            pass
        manager, _model = anthropic_provider.message_create(FakeClient(), candidates=["m1"], stream=True, **KW)
        with pytest.raises(ValueError):
            with manager:
                raise ValueError("stopped mid-stream")
    assert [(c["outcome"], c["output_tokens"]) for c in recorder.calls] == [("succeeded", 30), ("failed", None)]


def test_observed_anthropic_request_does_not_retry_inside_the_sdk():
    import httpx

    requests = []

    def fail(request):
        requests.append(request)
        return httpx.Response(503, json={"type": "error", "error": {"type": "overloaded_error"}})

    sdk = anthropic_provider.load_sdk()
    recorder = Recorder()
    with sdk.Anthropic(api_key="fake", http_client=httpx.Client(transport=httpx.MockTransport(fail))) as client:
        with observer.observing(recorder), pytest.raises(sdk.APIStatusError):
            anthropic_provider.message_create(client, candidates=["m1"], **KW)
    assert len(requests) == 1
    assert [call["outcome"] for call in recorder.calls] == ["failed"]


def test_a_stream_opening_error_is_reported_once():
    class UnavailableStream:
        def __enter__(self):
            raise RuntimeError("stream unavailable")

    client = FakeClient()
    client.stream = lambda **kwargs: UnavailableStream()
    recorder = Recorder()
    with observer.observing(recorder):
        manager, _model = anthropic_provider.message_create(client, candidates=["m1"], stream=True, **KW)
        with pytest.raises(RuntimeError, match="stream unavailable"):
            with manager:
                pass
    assert [call["outcome"] for call in recorder.calls] == ["failed"]


class FakeResponse:
    def __init__(self, lines=(), body=None, status_code=200):
        self._lines, self._body, self.status_code = list(lines), body or {}, status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._body

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


GEMINI = dict(model_name="gemini-x", system_prompt="sys", messages=[], tools=None, max_tokens=100, temperature=0,
              api_key="k")


def test_gemini_requests_are_reported_with_reported_usage(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(gemini_provider.requests, "post", lambda *a, **k: FakeResponse(
        body={"usage": {"prompt_tokens": 5, "completion_tokens": 3}}))
    with observer.observing(recorder):
        gemini_provider.chat_completion(**GEMINI)
    lines = ['data: {"choices": [{"delta": {"content": "a"}}]}',
             'data: {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 2}}', "data: [DONE]"]
    monkeypatch.setattr(gemini_provider.requests, "post", lambda *a, **k: FakeResponse(lines=lines))
    with observer.observing(recorder):
        response = gemini_provider.chat_completion(stream=True, **GEMINI)
        assert len(list(gemini_provider.iter_stream_payloads(response))) == 2
    assert [(c["outcome"], c["input_tokens"], c["output_tokens"]) for c in recorder.calls] == [
        ("succeeded", 5, 3), ("succeeded", 8, 2)]


def test_an_abandoned_gemini_stream_is_reported(monkeypatch):
    recorder = Recorder()
    lines = ['data: {"choices": [{"delta": {"content": "a"}}]}', 'data: {"choices": [{"delta": {"content": "b"}}]}']
    monkeypatch.setattr(gemini_provider.requests, "post", lambda *a, **k: FakeResponse(lines=lines))
    with observer.observing(recorder):
        payloads = gemini_provider.iter_stream_payloads(gemini_provider.chat_completion(stream=True, **GEMINI))
        next(payloads)
        payloads.close()
    assert recorder.calls[0]["outcome"] == "abandoned"
