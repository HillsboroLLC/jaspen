import time, threading
from typing import Any, Dict, Optional

_DEFAULT_TTL = 2 * 60 * 60  # 2h

class _TTLStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[str, tuple[float, Dict[str, Any]]] = {}

    def set(self, key: str, value: Dict[str, Any], ttl: int = _DEFAULT_TTL):
        exp = time.time() + max(1, int(ttl))
        with self._lock:
            self._data[key] = (exp, value)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            exp, val = item
            if exp < now:
                self._data.pop(key, None)
                return None
            return val

    def clear(self, key: str):
        with self._lock:
            self._data.pop(key, None)

_store = _TTLStore()

def set_context(session_id: str, ctx: Dict[str, Any], ttl: int = _DEFAULT_TTL):
    _store.set(session_id, ctx, ttl)

def get_context(session_id: str) -> Optional[Dict[str, Any]]:
    return _store.get(session_id)

def clear_context(session_id: str):
    _store.clear(session_id)
