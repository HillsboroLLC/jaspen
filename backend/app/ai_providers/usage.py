"""Provider-neutral reading of usage a failed provider call reported.

An error from either adapter may carry the usage the provider counted before
it failed, on the exception or on its HTTP response, as a dict in either
provider's key names or as an SDK usage object.
"""


def reported_error_usage(exc):
    """``(input_tokens, output_tokens)`` the failed call reported; each is
    None when the provider reported nothing for it."""
    usage = getattr(exc, 'usage', None)
    if usage is None:
        usage = getattr(getattr(exc, 'response', None), 'usage', None)
    if isinstance(usage, dict):
        input_tokens = usage.get('input_tokens') or usage.get('prompt_tokens')
        output_tokens = usage.get('output_tokens') or usage.get('completion_tokens')
    else:
        input_tokens = getattr(usage, 'input_tokens', None) if usage is not None else None
        output_tokens = getattr(usage, 'output_tokens', None) if usage is not None else None
    return input_tokens, output_tokens
