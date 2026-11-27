"""I4 prerequisite: staging-only test pricing and capacity policy versions (founder decisions D2, D3).

Phase 12 fails closed without exactly one effective pricing version and one
effective capacity version. Founder decisions of 2026-11-26:

* D2: staging-only test pricing, explicitly labeled as test;
* D3: staging-only test capacity thresholds with bounded spending and safeguards.

``install_test_policies`` writes both through the normal lifecycle (draft,
approved, effective; superseding the current effective version). Every version
it writes is labeled ``staging-test``, and the installer refuses a production
runtime, so a test version can never become production pricing. The numbers come
from an operator rules file, never from code. Pricing rates default to the
repository's current provider rate tables, and the credit conversion is the
governance policy's internal-unit rate. The capacity rules are validated by
Phase 12's own ``capacity_rules`` before anything is written.

The operator entry point is ``scripts/billing_policies.py``. No route, job or
startup path imports this module.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from types import SimpleNamespace

from sqlalchemy import select

from .billing_ai_operations import capacity_rules
from .billing_cutover import _database_now
from .models import CapacityPolicyVersion, PricingPolicyVersion, ProviderRateEntry
from .models_billing_phase12 import CONVERSION_KEY


TEST_LABEL = "staging-test"
LABEL_NOTE = "staging-test policy (founder decisions D2/D3, 2026-11-26); never valid in production"


class PolicyInstallError(RuntimeError):
    """The rules are invalid or the runtime may not install test policies."""


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
                          .encode("utf-8")).hexdigest()


def _decimal(name, value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PolicyInstallError(f"{name} must be a decimal") from exc
    if not number.is_finite() or number < 0:
        raise PolicyInstallError(f"{name} must be a non-negative decimal")
    return str(number)


def repository_rates():
    """The repository's current provider rate tables (USD per 1M tokens), as ``{(provider, model): (in, out)}``."""
    from .billing_config import ANTHROPIC_PRICES_USD_PER_M, GEMINI_PRICES_USD_PER_M

    rates = {}
    for provider, table in (("anthropic", ANTHROPIC_PRICES_USD_PER_M), ("google", GEMINI_PRICES_USD_PER_M)):
        for model, entry in table.items():
            rates[(provider, model)] = (str(entry["input"]), str(entry["output"]))
    return rates


def internal_units_per_provider_usd():
    from .ai_governance import credits_for_provider_cost

    return str(Decimal(str(credits_for_provider_cost(1, internal=True))))


def _pricing_spec(rules):
    pricing = rules.get("pricing") or {}
    if not isinstance(pricing, dict):
        raise PolicyInstallError("pricing must be an object")
    source = str(pricing.get("source_reference") or "repository:billing_config rate tables").strip()
    entries = pricing.get("rates")
    if entries is None:
        rates = repository_rates()
    else:
        if not isinstance(entries, list) or not entries:
            raise PolicyInstallError("pricing.rates must be a non-empty list when given")
        rates = {}
        for entry in entries:
            key = (str(entry.get("provider") or "").strip(), str(entry.get("model") or "").strip())
            if not all(key) or key in rates:
                raise PolicyInstallError("each rate names a unique provider and model")
            rates[key] = (_decimal("input_rate", entry.get("input_rate")),
                          _decimal("output_rate", entry.get("output_rate")))
    return {"rates": {f"{p}:{m}": list(v) for (p, m), v in sorted(rates.items())}, "source_reference": source,
            "conversion": internal_units_per_provider_usd()}


def _capacity_spec(rules):
    capacity = rules.get("capacity")
    if not isinstance(capacity, dict):
        raise PolicyInstallError("capacity rules are required (no number has a default)")
    capacity_rules(SimpleNamespace(rules_json=capacity))  # Phase 12's own validation; raises when incomplete
    return capacity


def install_test_policies(session, *, rules, approval_reference):
    """Install the staging test pricing and capacity versions; returns ``{"pricing": ..., "capacity": ...}``.

    Each entry is ``(version_name, "installed" | "unchanged")``. The caller commits.
    """
    from .rate_limits import is_production_runtime

    if is_production_runtime():
        raise PolicyInstallError("staging test policies are refused in a production runtime")
    approval_reference = str(approval_reference or "").strip()
    if not approval_reference:
        raise PolicyInstallError("an approval reference is required")
    if not isinstance(rules, dict):
        raise PolicyInstallError("rules must be an object")
    pricing, capacity = _pricing_spec(rules), _capacity_spec(rules)
    now = _database_now(session)
    return {
        "pricing": _install_pricing(session, pricing, now),
        "capacity": _install_capacity(session, capacity, approval_reference, now),
    }


def _effective(session, model):
    return session.execute(select(model).where(model.state == "effective")).scalars().all()


def _install_pricing(session, spec, now):
    name = f"{TEST_LABEL}-pricing-{_fingerprint(spec)[:16]}"
    current = _effective(session, PricingPolicyVersion)
    if [v.version for v in current] == [name]:
        return name, "unchanged"
    for old in current:
        old.state, old.superseded_at = "superseded", now
    session.flush()
    version = PricingPolicyVersion(
        version=name, state="draft", effective_at=now - timedelta(seconds=1),
        credit_conversion_version=f"{TEST_LABEL}:provider-cost-3600-v1", rounding_rule="ceil_whole_credit",
        conversion_json={CONVERSION_KEY: spec["conversion"], "label": LABEL_NOTE},
        customer_credit_impact=False, notice_required=False,
    )
    session.add(version)
    session.flush()
    for key, (input_rate, output_rate) in spec["rates"].items():
        provider, model = key.split(":", 1)
        session.add(ProviderRateEntry(
            pricing_policy_version_id=version.id, provider=provider, model=model, currency="usd",
            unit_basis="per_1m_tokens", input_rate=input_rate, output_rate=output_rate,
            source_reference=f"{TEST_LABEL}:{spec['source_reference']}"[:255], source_observed_at=now,
        ))
    session.flush()
    version.state, version.approved_at = "approved", now - timedelta(seconds=2)
    session.flush()
    version.state = "effective"
    session.flush()
    return name, "installed"


def _install_capacity(session, rules_json, approval_reference, now):
    rules_json = {**rules_json, "label": LABEL_NOTE}
    name = f"{TEST_LABEL}-capacity-{_fingerprint(rules_json)[:16]}"
    current = _effective(session, CapacityPolicyVersion)
    if [v.version for v in current] == [name]:
        return name, "unchanged"
    for old in current:
        old.state, old.superseded_at = "superseded", now
    session.flush()
    version = CapacityPolicyVersion(version=name, state="draft", effective_at=now - timedelta(seconds=1),
                                    rules_json=rules_json)
    session.add(version)
    session.flush()
    version.state, version.approved_at = "approved", now - timedelta(seconds=2)
    version.approval_evidence_reference = f"{TEST_LABEL}:{approval_reference}"[:255]
    session.flush()
    version.state = "effective"
    session.flush()
    return name, "installed"
