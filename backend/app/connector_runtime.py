import random
import time
from time import perf_counter

import requests


RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def _safe_json(response):
    try:
        return response.json() if response.text else {}
    except Exception:
        return {"raw": response.text}


def request_json_with_backoff(
    method,
    url,
    *,
    json_payload=None,
    data_payload=None,
    params=None,
    headers=None,
    auth=None,
    timeout=20,
    max_attempts=4,
    base_delay_seconds=0.5,
    max_delay_seconds=8.0,
    retryable_status_codes=None,
):
    retryable_codes = set(retryable_status_codes or RETRYABLE_STATUS_CODES)
    started = perf_counter()
    attempt_count = 0
    last_error = None

    for attempt in range(1, max_attempts + 1):
        attempt_count = attempt
        try:
            response = requests.request(
                method=method,
                url=url,
                json=json_payload,
                data=data_payload,
                params=params,
                headers=headers,
                auth=auth,
                timeout=timeout,
            )
            data = _safe_json(response)

            if response.status_code >= 400:
                message = f"HTTP {response.status_code}: {data}"
                retryable = response.status_code in retryable_codes and attempt < max_attempts
                if retryable:
                    retry_after = response.headers.get("Retry-After")
                    delay = None
                    if retry_after:
                        try:
                            delay = float(str(retry_after).strip())
                        except Exception:
                            delay = None
                    if delay is None:
                        delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
                    delay = delay + random.uniform(0, delay * 0.15)
                    time.sleep(delay)
                    last_error = RuntimeError(message)
                    continue
                raise RuntimeError(message)

            return {
                "data": data,
                "attempt_count": attempt,
                "duration_ms": int((perf_counter() - started) * 1000),
                "url": url,
            }
        except requests.RequestException as exc:
            last_error = exc
            if attempt < max_attempts:
                delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
                delay = delay + random.uniform(0, delay * 0.15)
                time.sleep(delay)
                continue
            break

    raise RuntimeError(
        f"Request failed after {attempt_count} attempts to {url}: {last_error}"
    )
