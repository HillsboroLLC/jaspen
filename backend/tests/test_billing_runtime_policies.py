"""I4 prerequisite: staging-only test pricing and capacity policies (D2, D3)."""

import copy
import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from app import billing_runtime_policies as bp
from app.billing_ai_operations import CapacityPolicyRequiredError, capacity_rules
from app.models import CapacityPolicyVersion, PricingPolicyVersion, ProviderRateEntry
from app.models_billing_phase12 import CONVERSION_KEY


BACKEND = Path(__file__).resolve().parents[1]
WINDOW = [{"key": "five_hour", "window_seconds": 18000, "max_operations": 10}]
RULES = {
    "pricing": {"rates": [{"provider": "anthropic", "model": "claude-test", "input_rate": "3", "output_rate": "15"}],
                "source_reference": "fixture"},
    "capacity": {
        "schema": "jaspen.capacity.v1",
        "tiers": {"plan.free": {"priority": 1, "member": {"max_concurrent": 1, "windows": WINDOW}}},
        "runaway": {"max_provider_attempts": 3, "max_tool_iterations": 8, "max_operation_seconds": 600,
                    "reservation_lease_seconds": 120, "max_reserved_credits": 3600000,
                    "max_call_input_tokens": 150000, "max_call_output_tokens": 16000,
                    "max_operation_tokens": 400000},
    },
}


def _effective(session, model):
    return session.execute(sa.select(model).where(model.state == "effective")).scalars().all()


def test_install_writes_one_labeled_effective_version_of_each_and_is_idempotent(db):
    session = db.session
    result = bp.install_test_policies(session, rules=RULES, approval_reference="lydia:2026-11-26:D2-D3")
    session.commit()
    assert result["pricing"][1] == result["capacity"][1] == "installed"
    [pricing] = _effective(session, PricingPolicyVersion)
    [capacity] = _effective(session, CapacityPolicyVersion)
    assert pricing.version.startswith("staging-test-pricing-") and capacity.version.startswith("staging-test-capacity-")
    assert pricing.credit_conversion_version.startswith("staging-test:")
    assert pricing.conversion_json[CONVERSION_KEY] == bp.internal_units_per_provider_usd() == "3600000"
    assert "never valid in production" in pricing.conversion_json["label"]
    assert capacity.approval_evidence_reference == "staging-test:lydia:2026-11-26:D2-D3"
    [rate] = session.query(ProviderRateEntry).filter_by(pricing_policy_version_id=pricing.id).all()
    assert (rate.provider, rate.model, str(rate.input_rate).rstrip("0").rstrip("."), rate.source_reference) == (
        "anthropic", "claude-test", "3", "staging-test:fixture")
    capacity_rules(capacity)  # Phase 12 accepts it

    again = bp.install_test_policies(session, rules=RULES, approval_reference="lydia:2026-11-26:D2-D3")
    assert again["pricing"][1] == again["capacity"][1] == "unchanged"
    session.rollback()


def test_a_changed_rules_file_supersedes_the_effective_versions(db):
    session = db.session
    bp.install_test_policies(session, rules=RULES, approval_reference="ref")
    session.commit()
    changed = copy.deepcopy(RULES)
    changed["capacity"]["runaway"]["max_reserved_credits"] = 1800000
    result = bp.install_test_policies(session, rules=changed, approval_reference="ref")
    session.commit()
    assert result["capacity"][1] == "installed" and result["pricing"][1] == "unchanged"
    assert len(_effective(session, CapacityPolicyVersion)) == 1
    assert session.query(CapacityPolicyVersion).filter_by(state="superseded").count() == 1


def test_pricing_rates_default_to_the_repository_tables(db):
    session = db.session
    rules = copy.deepcopy(RULES)
    del rules["pricing"]["rates"]
    bp.install_test_policies(session, rules=rules, approval_reference="ref")
    [pricing] = _effective(session, PricingPolicyVersion)
    count = session.query(ProviderRateEntry).filter_by(pricing_policy_version_id=pricing.id).count()
    assert count == len(bp.repository_rates()) > 0
    session.rollback()


@pytest.mark.parametrize("mutate,error", [
    (lambda r: r.pop("capacity"), bp.PolicyInstallError),
    (lambda r: r["capacity"]["runaway"].pop("max_reserved_credits"), CapacityPolicyRequiredError),
    (lambda r: r["pricing"]["rates"][0].update(input_rate="-1"), bp.PolicyInstallError),
    (lambda r: r["pricing"]["rates"].append(dict(r["pricing"]["rates"][0])), bp.PolicyInstallError),
])
def test_incomplete_or_invalid_rules_write_nothing(db, mutate, error):
    session = db.session
    rules = copy.deepcopy(RULES)
    mutate(rules)
    with pytest.raises(error):
        bp.install_test_policies(session, rules=rules, approval_reference="ref")
    session.rollback()
    assert session.query(PricingPolicyVersion).count() == 0 and session.query(CapacityPolicyVersion).count() == 0


@pytest.mark.parametrize("variable,value", [("APP_ENV", "production"), ("STRIPE_SECRET_KEY", "sk_live_example")])
def test_test_policies_are_refused_in_a_production_runtime(db, monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(bp.PolicyInstallError, match="production runtime"):
        bp.install_test_policies(db.session, rules=RULES, approval_reference="ref")


def _cli(app, argv, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("billing_policies", BACKEND / "scripts" / "billing_policies.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.run(argv, app=app)
    return code, json.loads(capsys.readouterr().out or "null")


def test_the_command_line_needs_confirmation_and_installs(db, app, capsys, tmp_path):
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps(RULES))
    argv = ["install", "--rules-file", str(rules_file), "--approval-reference", "ref"]
    code, out = _cli(app, argv, capsys)
    assert code == 2 and "--confirm-write" in out["error"]
    code, out = _cli(app, argv + ["--confirm-write"], capsys)
    assert code == 0 and out["pricing"]["state"] == "installed" and out["capacity"]["state"] == "installed"

