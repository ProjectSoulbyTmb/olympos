"""Thread-local request context helpers for server -> backend propagation."""

import threading
from contextlib import contextmanager
from dataclasses import dataclass


_STATE = threading.local()


@dataclass
class RequestContext:
    request_id: str
    route: str = ""
    conversation_id: str = ""


def get_request_context():
    return getattr(_STATE, "value", None)


def get_request_id():
    context = get_request_context()
    return context.request_id if context else ""


@contextmanager
def bind_request_context(request_id, route="", conversation_id=""):
    previous = get_request_context()
    _STATE.value = RequestContext(
        request_id=request_id, route=route, conversation_id=conversation_id)
    try:
        yield _STATE.value
    finally:
        if previous is None:
            if hasattr(_STATE, "value"):
                delattr(_STATE, "value")
        else:
            _STATE.value = previous
