"""A context-local observer for every provider request (I4, ai_reservation family).

The two provider adapters (``anthropic.message_create``, ``gemini.chat_completion``)
are the only places Jaspen sends a provider request. When an observer is
installed on the current context (the I4 delivery executor installs one for a
modern organization's turn), each request is announced before it is sent and
reported after it ends, whatever the outcome: success, error, timeout, a
fallback to the next candidate model, or a stream that ends or is abandoned.
That is how Phase 12 checks every call before it happens and records every
call's usage after it (gate criteria 2 and 6).

With no observer installed, which covers every legacy turn and every other
caller, the adapters behave exactly as before.

An observer implements:

* ``before_call(provider, model, request) -> handle``. ``request`` holds
  ``max_output_tokens`` and ``input_characters`` (for the caller's
  deterministic input bound). Raising refuses the request before it is sent.
* ``after_call(handle, outcome, *, input_tokens, output_tokens, error=None,
  status_code=None, request_id=None)``. ``outcome`` is ``"succeeded"``,
  ``"failed"`` or ``"abandoned"``. Token counts are ``None`` when the provider
  reported none.
"""

from contextlib import contextmanager
import contextvars
import json


_current = contextvars.ContextVar("jaspen_provider_call_observer", default=None)


def current():
    return _current.get()


@contextmanager
def observing(observer):
    token = _current.set(observer)
    try:
        yield observer
    finally:
        _current.reset(token)


def input_characters(*parts):
    """Characters of a request's prompt material, for the observer's input bound."""
    total = 0
    for part in parts:
        if part is None:
            continue
        total += len(part if isinstance(part, str) else json.dumps(part, default=str))
    return total


class ObservedCall:
    """One announced request; reports exactly once."""

    def __init__(self, observer, handle):
        self._observer = observer
        self._handle = handle
        self._reported = False

    def report(self, outcome, *, input_tokens=None, output_tokens=None, error=None, status_code=None,
               request_id=None):
        if self._reported:
            return
        self._reported = True
        self._observer.after_call(self._handle, outcome, input_tokens=input_tokens, output_tokens=output_tokens,
                                  error=error, status_code=status_code, request_id=request_id)


def announce(provider, model, *, max_output_tokens, input_chars):
    """Announce a request to the installed observer; ``None`` when there is none."""
    observer = _current.get()
    if observer is None:
        return None
    handle = observer.before_call(provider, model, {"max_output_tokens": int(max_output_tokens or 0),
                                                     "input_characters": int(input_chars or 0)})
    return ObservedCall(observer, handle)
