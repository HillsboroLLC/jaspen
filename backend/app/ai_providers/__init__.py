"""Model provider adapters: the only package that talks to a model provider.

Each module holds one provider's client, the conversion of Jaspen's messages,
tools and attachments into that provider's request format, the conversion of
its responses and stream events back, and nothing else. Which provider and
model to use, what the prompt says, what a tool does, who may run it and what
is charged are decided by the caller (``routes/ai_agent.py`` today, the
conversation turn and ``ai_runtime`` over time) and passed in.

Rules (Unified Architecture section 6, guard in tests/test_ai_providers.py):

- A provider SDK is imported only here, and lazily, so importing Jaspen never
  loads one (the public intake no-AI guarantee depends on this).
- A provider endpoint is addressed only here.
- Nothing here imports a route module, so there is no import cycle.

P5a moved this code out of ``routes/ai_agent.py`` unchanged; the request bytes
each provider receives were compared before and after and are identical.
"""
