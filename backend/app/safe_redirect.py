import re
from urllib.parse import unquote


_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_MALFORMED_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _unsafe_path_form(path):
    return (
        not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or _CONTROL_CHARACTER.search(path) is not None
        or any(segment in {".", ".."} for segment in path.split("/"))
    )


def safe_internal_path(candidate, fallback):
    if not isinstance(candidate, str) or not candidate:
        return fallback
    if not candidate.startswith("/") or candidate.startswith("//"):
        return fallback
    if _CONTROL_CHARACTER.search(candidate):
        return fallback

    path = re.split(r"[?#]", candidate, maxsplit=1)[0]
    forms = [path]
    current = path
    stable = False

    for _ in range(3):
        if _MALFORMED_PERCENT_ESCAPE.search(current):
            return fallback
        try:
            decoded = unquote(current, errors="strict")
        except UnicodeDecodeError:
            return fallback
        forms.append(decoded)
        if decoded == current:
            stable = True
            break
        current = decoded

    if not stable or any(_unsafe_path_form(form) for form in forms):
        return fallback
    return candidate
