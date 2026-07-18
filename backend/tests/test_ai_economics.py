from app.billing_config import credits_for_completion, provider_cost_usd


def test_published_provider_costs_cover_claude_and_gemini():
    assert provider_cost_usd("claude-sonnet-4-6", 1_000_000, 100_000) == 4.5
    assert provider_cost_usd("gemini-2.5-flash", 1_000_000, 100_000) == 0.55
    assert provider_cost_usd("gemini-2.5-pro", 1_000_000, 100_000) == 2.25


def test_gemini_usage_debits_thinking_capacity():
    assert credits_for_completion("business", "gemini-2.5-flash", 1_000_000, 100_000) > 0
