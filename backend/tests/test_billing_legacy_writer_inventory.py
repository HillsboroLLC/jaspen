"""Phase 13: the enforced inventory of legacy billing writers (D04 refresh).

Traceability D18 row 13 requires "all writer/reader inventory"; ADR-0001
lists the fields that "must not remain authoritative". This test is the
inventory's enforcement: it scans the backend source (``app/``, ``scripts/``
and the top-level scripts; migrations and tests are out of scope) and fails
when a function writes a legacy billing field, or references a legacy credit
mutator, without being listed here. It also fails when a listed entry no
longer exists, so the list cannot drift. The human-readable form is D04 in
``docs/specs/billing/current-state-inventory.md``.

Two code lines exist until they are merged. They fork at ``0cf97e7c``: the
billing line (this tree) and the unified line (F1 ``3d0b71d5`` onward, read at
``d05e9c0f``; the uncommitted P3 tree at that base scans identically). Each
entry is tagged ``both``, ``billing_line`` or ``unified_line``. On this tree
the scan must equal the ``both`` + ``billing_line`` entries. Set
``JASPEN_UNIFIED_LINE_BACKEND`` to a unified-line ``backend/`` directory to
check that the scan there equals ``both`` + ``unified_line``. After the merge
the merged tree must pass with its entries re-tagged; a new or removed writer
is an inventory change to review, never a silent pass.

The unified line binds the legacy credit functions into ``TurnBilling`` in
``ai_agent._conversation_turn`` (reserve, price, settle, release,
persist_balance), replacing six per-route copies on the billing line. Since
P4.0 (``04f60590``) that binding goes through ``_TurnOperationEvidence``,
which claims and closes the turn's ``AIOperation`` around the same calls. Phase 17
replaces that binding with the Phase 12 ledger; until then it is a legacy
credit writer like the rest.
"""

import ast
import os
from pathlib import Path
import re

import pytest


BACKEND = Path(__file__).resolve().parents[1]

# ADR-0001 "Current fields that must not remain authoritative", plus the grant
# and offer revocation columns that end legacy credit value (M2).
LEGACY_FIELDS = frozenset({
    "credits_remaining", "credits_reset_at", "subscription_plan", "subscription_status", "plan_key",
    "max_total_paid_seats", "remaining_amount", "credits_charged", "charged_credits",
})
# Columns that end legacy credit value, counted on grant and entitlement objects only
# (auth sessions also have ``revoked_at``).
OWNED_FIELDS = frozenset({"status", "revoked_at", "revoke_reason", "reversed_at"})
# Creating any of these rows writes legacy billing state (defaults included).
LEGACY_MODELS = frozenset({
    "User", "Organization", "PersistentCreditGrant", "PersistentCreditTransaction", "AccountEntitlement",
    "Payment", "UsageEvent", "AIOperation",
})
LEGACY_TABLES = ("users", "organizations", "persistent_credit_grants", "persistent_credit_transactions",
                 "account_entitlements", "payments", "usage_events", "ai_operations")
# Legacy functions that change balances, plans, or meters (D04 "Mutation
# functions"), including the reader that writes on read (STOP-01).
LEGACY_MUTATORS = frozenset({
    "consume_credits", "release_consumed_credits", "add_credits", "cap_monthly_credits",
    "reset_user_monthly_credits", "apply_plan_to_user", "bootstrap_legacy_credits", "_resolve_user_pool",
    "_resolve_org_pool", "get_usage_meter_state", "sync_org_plan_from_owner", "sync_org_plan_and_commit",
    "grant_limited_time_300k_offer", "grant_persistent_credit_pack", "consume_persistent_credits",
    "refund_persistent_usage", "reverse_limited_time_300k_credits", "reverse_persistent_credit_pack",
    "grant_founder_offer", "_reserve_preflight_credits", "_settle_reserved_credits", "_release_reserved_credits",
    "_persist_credit_deduction",
})
# Modules whose attributes are legacy writers; a dynamic getattr on them is unresolvable.
LEGACY_WRITER_MODULES = frozenset({"billing_config", "founder_entitlements", "orgs", "ai_audit", "ai_runtime"})
METER_KEY = "thinking_power"
STATUS_OWNERS = re.compile(r"grant|entitlement", re.IGNORECASE)
# A function that names one of these models owns its status/revocation writes, whatever the variable is called (M2b).
OWNER_MODELS = frozenset({"PersistentCreditGrant", "AccountEntitlement"})
# Statement builders and bulk writers whose first argument is the written model (M2b).
STATEMENT_WRITERS = frozenset({"update", "insert", "delete"})
BULK_WRITERS = frozenset({"bulk_update_mappings", "bulk_insert_mappings"})
QUERY_WRITERS = frozenset({"update", "delete"})
PAYLOAD_CALLS = frozenset({"update", "values", "execute"}) | BULK_WRITERS
RAW_SQL = re.compile(
    r"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+\"?(" + "|".join(LEGACY_TABLES) + r")\"?\b", re.IGNORECASE,
)
# Writers reached only from outside Python (HTTP routes, CLI entry points,
# constructors, a model property): their call sites are not helper calls.
ENTRYPOINT_NAMES = frozenset({"main", "__init__", "plan"})
ROUTE_DECORATORS = frozenset({"route", "get", "post", "put", "patch", "delete"})


def _sources(root):
    for sub in ("app", "scripts"):
        yield from sorted((root / sub).rglob("*.py"))
    yield from sorted(root.glob("*.py"))


def _name_of(node):
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def _keys(node):
    """Field names written by a bulk payload: a dict literal, or a list or tuple of them."""
    names = set()
    if isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            names |= _keys(element)
    elif isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.add(key.value)
            elif isinstance(key, ast.Attribute):
                names.add(key.attr)
    return names


def _meter_chain(node):
    """True for ``x["thinking_power"]`` and anything subscripted below it."""
    while isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, ast.Constant) and key.value == METER_KEY:
            return True
        node = node.value
    return False


def _statement_builder(name):
    """``update``/``insert``/``delete``, including dialect builders such as ``postgresql_insert``."""
    return name if name in STATEMENT_WRITERS else "insert" if name and name.endswith("_insert") else None


def _query_model(node, resolve):
    """The legacy model of ``session.query(Model)...`` below a bulk ``.update``/``.delete``, if any."""
    while isinstance(node, (ast.Call, ast.Attribute)):
        if isinstance(node, ast.Call):
            if _name_of(node.func) == "query" and node.args and resolve(_name_of(node.args[0])) in LEGACY_MODELS:
                return resolve(_name_of(node.args[0]))
            node = node.func
        else:
            node = node.value
    return None


def _is_route(function):
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _name_of(target) in ROUTE_DECORATORS:
            return True
    return False


def _scan_file(path, relative, helpers):
    writes, references, writer_functions = set(), set(), set()
    tree = ast.parse(path.read_text(), filename=relative)
    aliases, module_aliases = {}, set()
    for node in ast.walk(tree):  # aliased imports resolve to their canonical names
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                base = alias.name.rsplit(".", 1)[-1]
                bound = alias.asname or base
                if base in LEGACY_MUTATORS | LEGACY_MODELS | helpers:
                    aliases[bound] = base
                if base in LEGACY_WRITER_MODULES:
                    module_aliases.add(bound)
    stack, entry, owners = [], [], []

    def resolve(name):
        return aliases.get(name, name)

    def names_owner_model(node):
        return any(resolve(_name_of(n)) in OWNER_MODELS for n in ast.walk(node)
                   if isinstance(n, (ast.Name, ast.Attribute)))

    class Visitor(ast.NodeVisitor):
        def _scope(self, node, entrypoint=False):
            stack.append(node.name)
            entry.append(entrypoint)
            owners.append(not isinstance(node, ast.ClassDef) and names_owner_model(node))
            self.generic_visit(node)
            stack.pop()
            entry.pop()
            owners.pop()

        def _owned(self, receiver):
            return any(owners) or bool(STATUS_OWNERS.search(_name_of(receiver) or ""))

        def visit_FunctionDef(self, node):
            is_property = any(_name_of(d) in ("property", "setter") for d in node.decorator_list)
            self._scope(node, _is_route(node) or is_property or node.name in ENTRYPOINT_NAMES)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            self._scope(node)

        def _where(self):
            return ".".join(stack) or "<module>"

        def _write(self, symbol, *, helper=True):
            writes.add((relative, self._where(), symbol))
            if helper and stack and not any(entry):
                writer_functions.add(stack[-1])

        def _reference(self, symbol):
            references.add((relative, self._where(), symbol))

        def _targets(self, targets):
            for target in targets:
                if isinstance(target, (ast.Tuple, ast.List)):
                    self._targets(target.elts)
                elif isinstance(target, ast.Attribute):
                    if target.attr in LEGACY_FIELDS:
                        self._write(target.attr)
                    elif target.attr in OWNED_FIELDS and self._owned(target.value):
                        self._write(target.attr)
                elif isinstance(target, ast.Subscript) and _meter_chain(target):
                    self._write(METER_KEY)  # a meter write makes its function a writer helper

        def visit_Assign(self, node):
            self._targets(node.targets)
            self.generic_visit(node)

        def visit_AugAssign(self, node):
            self._targets([node.target])
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            self._targets([node.target])
            self.generic_visit(node)

        def visit_Constant(self, node):
            if node.value == METER_KEY:  # any meter access, read or write, is inventoried
                self._write(METER_KEY, helper=False)
            elif isinstance(node.value, str):
                for table in RAW_SQL.findall(node.value):
                    self._write(f"sql:{table.lower()}")

        def visit_Call(self, node):
            name = resolve(_name_of(node.func))
            if name in LEGACY_MODELS:
                self._write(f"{name}()")
            first = resolve(_name_of(node.args[0])) if node.args else None
            builder = _statement_builder(name)
            if builder and first in LEGACY_MODELS:
                self._write(f"{builder}({first})")  # update(User), insert(User), postgresql_insert(User), ...
            if name in BULK_WRITERS and first in LEGACY_MODELS:
                self._write(f"{name}({first})")
            if name in QUERY_WRITERS and isinstance(node.func, ast.Attribute):
                model = _query_model(node.func.value, resolve)
                if model:
                    self._write(f"query({model}).{name}")  # bulk ORM write, whatever its payload
            if any(k.arg == METER_KEY for k in node.keywords):
                self._write(METER_KEY)  # e.g. settings.update(thinking_power=meter), dict(..., thinking_power=m)
            if name in PAYLOAD_CALLS:
                payload = set().union(*(_keys(arg) for arg in node.args), {k.arg for k in node.keywords if k.arg})
                owned = OWNED_FIELDS if any(owners) else OWNED_FIELDS - {"status"}
                for field in sorted(payload & (LEGACY_FIELDS | owned)):
                    self._write(field)
            if name in ("update", "setdefault", "pop", "clear") and isinstance(node.func, ast.Attribute) \
                    and _meter_chain(node.func.value):
                self._write(METER_KEY)  # in-place meter mutation
            if name in ("setattr", "getattr") and len(node.args) >= 2:
                attribute = node.args[1]
                if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
                    if name == "setattr" and (attribute.value in LEGACY_FIELDS or (
                            attribute.value in OWNED_FIELDS and self._owned(node.args[0]))):
                        self._write(attribute.value)
                    if attribute.value in LEGACY_MUTATORS | helpers:
                        self._reference(attribute.value)
                elif name == "setattr":
                    # Unresolvable: listed for review, never assumed safe.
                    self._write("setattr(dynamic)", helper=False)
                elif _name_of(node.args[0]) in module_aliases:
                    self._reference("getattr(dynamic)")
            self.generic_visit(node)

        def visit_Name(self, node):
            name = aliases.get(node.id, node.id)
            if isinstance(node.ctx, ast.Load) and name in LEGACY_MUTATORS | helpers:
                self._reference(name)

        def visit_Attribute(self, node):
            if node.attr in LEGACY_MUTATORS | helpers:
                self._reference(node.attr)
            self.generic_visit(node)

    Visitor().visit(tree)
    return writes, references, writer_functions


def scan(root):
    """(path, function, symbol) for every legacy field write and legacy writer reference.

    Two passes: the first finds the functions that write legacy fields; the
    second also records every reference to those writer helpers (not HTTP
    routes, CLI entry points, constructors or properties), so a new call site
    of an inventoried writer is itself an inventory change.
    """
    sources = [(path, str(path.relative_to(root))) for path in _sources(root)]
    helpers = set()
    for path, relative in sources:
        helpers |= _scan_file(path, relative, frozenset())[2]
    helpers = frozenset(helpers)
    writes, references = set(), set()
    for path, relative in sources:
        file_writes, file_references, _functions = _scan_file(path, relative, helpers)
        writes |= file_writes
        references |= file_references
    return writes, references


# (path, function, symbol, line). Refreshed 2026-11-17 on billing 4efabb05
# and unified d05e9c0f with the M2 scanner. Symbols: a legacy field,
# ``Model()`` row creation, ``thinking_power`` meter access (read or write),
# ``status``/revocation columns on grants and entitlements, ``sql:<table>``,
# ``setattr(dynamic)`` (reviewed: the attribute cannot be resolved statically),
# and in references a legacy mutator, a legacy writer helper, or
# ``getattr(dynamic)`` on a legacy writer module.
LEGACY_FIELD_WRITERS = (
    # P4.0 chat operation evidence (unified line 04f60590): the turn's claim,
    # and its close when the claim never became durable. Evidence rows only;
    # neither changes a balance.
    ("app/ai_audit.py", "claim_turn_operation", "AIOperation()", "unified_line"),
    ("app/ai_audit.py", "close_turn_operation_alone", "AIOperation()", "unified_line"),
    ("app/ai_audit.py", "persist_operation", "AIOperation()", "both"),
    ("app/ai_audit.py", "persist_operation", "charged_credits", "both"),
    ("app/ai_runtime.py", "_claim_operation", "AIOperation()", "both"),
    ("app/ai_runtime.py", "finalize_batch_charge_allocation", "charged_credits", "both"),
    ("app/ai_runtime.py", "reverse_customer_operation_charge", "charged_credits", "both"),
    ("app/billing_ai_operations.py", "_finalize", "setattr(dynamic)", "billing_line"),
    ("app/billing_ai_operations.py", "authorize_ai_operation", "setattr(dynamic)", "billing_line"),
    ("app/billing_config.py", "_resolve_org_pool", "thinking_power", "both"),
    ("app/billing_config.py", "_resolve_user_pool", "credits_remaining", "both"),
    ("app/billing_config.py", "_resolve_user_pool", "credits_reset_at", "both"),
    ("app/billing_config.py", "_resolve_user_pool", "thinking_power", "both"),
    ("app/billing_config.py", "add_credits", "credits_remaining", "both"),
    ("app/billing_config.py", "add_credits", "credits_reset_at", "both"),
    ("app/billing_config.py", "add_credits", "thinking_power", "both"),
    ("app/billing_config.py", "apply_plan_to_user", "credits_remaining", "both"),
    ("app/billing_config.py", "apply_plan_to_user", "credits_reset_at", "both"),
    ("app/billing_config.py", "apply_plan_to_user", "subscription_plan", "both"),
    ("app/billing_config.py", "bootstrap_legacy_credits", "credits_remaining", "both"),
    ("app/billing_config.py", "bootstrap_legacy_credits", "credits_reset_at", "both"),
    ("app/billing_config.py", "cap_monthly_credits", "credits_remaining", "both"),
    ("app/billing_config.py", "cap_monthly_credits", "thinking_power", "both"),
    ("app/billing_config.py", "consume_credits", "credits_remaining", "both"),
    ("app/billing_config.py", "consume_credits", "credits_reset_at", "both"),
    ("app/billing_config.py", "consume_credits", "thinking_power", "both"),
    ("app/billing_config.py", "release_consumed_credits", "credits_remaining", "both"),
    ("app/billing_config.py", "release_consumed_credits", "thinking_power", "both"),
    ("app/billing_config.py", "reset_user_monthly_credits", "credits_remaining", "both"),
    ("app/billing_config.py", "reset_user_monthly_credits", "credits_reset_at", "both"),
    ("app/billing_enterprise_contracts.py", "_transition", "setattr(dynamic)", "billing_line"),
    ("app/billing_projections.py", "_meter", "thinking_power", "billing_line"),
    ("app/conversation_turn.py", "ConversationTurn.__init__", "credits_charged", "unified_line"),
    ("app/conversation_turn.py", "ConversationTurn.settle", "credits_charged", "unified_line"),
    ("app/decision_asset_email_service.py", "record_telemetry", "UsageEvent()", "both"),
    ("app/founder_entitlements.py", "consume_persistent_credits", "PersistentCreditTransaction()", "both"),
    ("app/founder_entitlements.py", "consume_persistent_credits", "remaining_amount", "both"),
    ("app/founder_entitlements.py", "grant_limited_time_300k_offer", "AccountEntitlement()", "both"),
    ("app/founder_entitlements.py", "grant_limited_time_300k_offer", "PersistentCreditGrant()", "both"),
    ("app/founder_entitlements.py", "grant_limited_time_300k_offer", "PersistentCreditTransaction()", "both"),
    ("app/founder_entitlements.py", "grant_persistent_credit_pack", "PersistentCreditGrant()", "both"),
    ("app/founder_entitlements.py", "grant_persistent_credit_pack", "PersistentCreditTransaction()", "both"),
    ("app/founder_entitlements.py", "refund_persistent_usage", "PersistentCreditTransaction()", "both"),
    ("app/founder_entitlements.py", "refund_persistent_usage", "remaining_amount", "both"),
    ("app/founder_entitlements.py", "reverse_limited_time_300k_credits", "PersistentCreditTransaction()", "both"),
    ("app/founder_entitlements.py", "reverse_limited_time_300k_credits", "remaining_amount", "both"),
    ("app/founder_entitlements.py", "reverse_limited_time_300k_credits", "reversed_at", "both"),
    ("app/founder_entitlements.py", "reverse_limited_time_300k_credits", "revoked_at", "both"),
    ("app/founder_entitlements.py", "reverse_limited_time_300k_credits", "status", "both"),
    ("app/founder_entitlements.py", "reverse_persistent_credit_pack", "PersistentCreditTransaction()", "both"),
    ("app/founder_entitlements.py", "reverse_persistent_credit_pack", "remaining_amount", "both"),
    ("app/founder_entitlements.py", "reverse_persistent_credit_pack", "reversed_at", "both"),
    ("app/founder_entitlements.py", "reverse_persistent_credit_pack", "status", "both"),
    ("app/models.py", "Organization.plan", "plan_key", "both"),
    ("app/orgs.py", "ensure_default_organization_for_user", "Organization()", "both"),
    ("app/orgs.py", "sync_org_plan_from_owner", "plan_key", "both"),
    ("app/routes/admin.py", "adjust_user_credits", "credits_remaining", "both"),
    ("app/routes/admin.py", "patch_user", "credits_remaining", "both"),
    ("app/routes/admin.py", "patch_user", "subscription_plan", "both"),
    # P4.0: reads the meter's last reset into the claim (read only, no write).
    ("app/routes/ai_agent.py", "_meter_cycle_marker", "thinking_power", "unified_line"),
    ("app/routes/ai_agent.py", "_persist_credit_deduction", "credits_remaining", "both"),
    ("app/routes/ai_agent.py", "_record_usage", "UsageEvent()", "both"),
    ("app/routes/auth.py", "_sso_user_and_membership", "User()", "both"),
    ("app/routes/auth.py", "google_callback", "User()", "both"),
    ("app/routes/auth.py", "signup", "User()", "both"),
    ("app/routes/billing.py", "_record_payment", "Payment()", "both"),
    ("app/routes/billing.py", "add_billed_seat", "max_total_paid_seats", "both"),
    ("app/routes/billing.py", "modify_subscription", "subscription_status", "both"),
    ("app/routes/billing.py", "stripe_webhook", "subscription_status", "both"),
    ("app/routes/billing.py", "sync_embedded_subscription", "subscription_status", "both"),
    ("app/routes/leads.py", "_apply_non_empty_metadata", "setattr(dynamic)", "both"),
    ("app/routes/strategy.py", "_record_claude_operation", "UsageEvent()", "both"),
    ("app/routes/teams.py", "create_team_org", "Organization()", "both"),
    ("create_user.py", "create_user", "User()", "both"),
    ("scripts/init_dev_db.py", "main", "User()", "both"),
)

LEGACY_MUTATOR_REFERENCES = (
    ("app/ai_runtime.py", "_claim_operation", "_claim_operation", "both"),
    ("app/ai_runtime.py", "execute_customer_operation", "_claim_operation", "both"),
    ("app/ai_runtime.py", "execute_customer_operation", "_release_reserved_credits", "both"),
    ("app/ai_runtime.py", "execute_customer_operation", "_reserve_preflight_credits", "both"),
    ("app/ai_runtime.py", "execute_customer_operation", "_settle_reserved_credits", "both"),
    ("app/ai_runtime.py", "execute_customer_operation", "persist_operation", "both"),
    ("app/ai_runtime.py", "finalize_batch_charge_allocation", "_release_reserved_credits", "both"),
    ("app/ai_runtime.py", "reverse_customer_operation_charge", "_release_reserved_credits", "both"),
    ("app/billing_config.py", "add_credits", "_resolve_org_pool", "both"),
    ("app/billing_config.py", "add_credits", "_resolve_user_pool", "both"),
    ("app/billing_config.py", "apply_plan_to_user", "_resolve_org_pool", "both"),
    ("app/billing_config.py", "apply_plan_to_user", "_resolve_user_pool", "both"),
    ("app/billing_config.py", "bootstrap_legacy_credits", "_resolve_org_pool", "both"),
    ("app/billing_config.py", "bootstrap_legacy_credits", "_resolve_user_pool", "both"),
    ("app/billing_config.py", "cap_monthly_credits", "_resolve_org_pool", "both"),
    ("app/billing_config.py", "cap_monthly_credits", "_resolve_user_pool", "both"),
    ("app/billing_config.py", "consume_credits", "_resolve_org_pool", "both"),
    ("app/billing_config.py", "consume_credits", "_resolve_user_pool", "both"),
    ("app/billing_config.py", "consume_credits", "consume_persistent_credits", "both"),
    ("app/billing_config.py", "get_usage_meter_state", "_resolve_org_pool", "both"),
    ("app/billing_config.py", "get_usage_meter_state", "_resolve_user_pool", "both"),
    ("app/billing_config.py", "release_consumed_credits", "_resolve_org_pool", "both"),
    ("app/billing_config.py", "release_consumed_credits", "refund_persistent_usage", "both"),
    ("app/billing_config.py", "reset_user_monthly_credits", "_resolve_org_pool", "both"),
    ("app/billing_config.py", "reset_user_monthly_credits", "_resolve_user_pool", "both"),
    ("app/conversation_turn.py", "ConversationTurn.settle", "settle", "unified_line"),
    ("app/decision_asset_email_service.py", "process_delivery", "record_telemetry", "both"),
    ("app/founder_entitlements.py", "<module>", "reverse_limited_time_300k_credits", "both"),
    ("app/founder_entitlements.py", "grant_founder_offer", "grant_limited_time_300k_offer", "both"),
    ("app/orgs.py", "ensure_default_organization_for_user", "sync_org_plan_from_owner", "both"),
    ("app/orgs.py", "resolve_active_org_for_user", "ensure_default_organization_for_user", "both"),
    ("app/orgs.py", "sync_org_plan_and_commit", "sync_org_plan_from_owner", "both"),
    ("app/routes/admin.py", "adjust_user_credits", "apply_plan_to_user", "both"),
    ("app/routes/admin.py", "force_plan", "apply_plan_to_user", "both"),
    ("app/routes/admin.py", "run_user_recovery", "apply_plan_to_user", "both"),
    # P4.0 (unified line 04f60590) moved the TurnBilling binding of the legacy
    # credit functions out of ``_conversation_turn`` into the evidence
    # wrapper's methods, with the same arguments and results.
    ("app/routes/ai_agent.py", "_TurnOperationEvidence.close_alone", "close_turn_operation_alone", "unified_line"),
    ("app/routes/ai_agent.py", "_TurnOperationEvidence.persist_balance", "_persist_credit_deduction", "unified_line"),
    ("app/routes/ai_agent.py", "_TurnOperationEvidence.release", "_release_reserved_credits", "unified_line"),
    ("app/routes/ai_agent.py", "_TurnOperationEvidence.reserve", "_reserve_preflight_credits", "unified_line"),
    ("app/routes/ai_agent.py", "_TurnOperationEvidence.reserve", "claim_turn_operation", "unified_line"),
    ("app/routes/ai_agent.py", "_TurnOperationEvidence.settle", "_settle_reserved_credits", "unified_line"),
    ("app/routes/ai_agent.py", "_conversation_turn", "settle", "unified_line"),
    ("app/routes/ai_agent.py", "_execute_mutation_tool", "_record_claude_operation", "both"),
    ("app/routes/ai_agent.py", "_execute_mutation_tool", "reverse_customer_operation_charge", "both"),
    ("app/routes/ai_agent.py", "_execute_mutation_tool._reverse_plan_charge", "reverse_customer_operation_charge", "both"),
    ("app/routes/ai_agent.py", "_finish_conversation_turn", "_record_usage", "unified_line"),
    ("app/routes/ai_agent.py", "_finish_conversation_turn", "settle", "unified_line"),
    ("app/routes/ai_agent.py", "_finish_regenerated_turn", "_record_usage", "unified_line"),
    ("app/routes/ai_agent.py", "_finish_regenerated_turn", "settle", "unified_line"),
    ("app/routes/ai_agent.py", "_insufficient_credits_payload", "get_usage_meter_state", "both"),
    ("app/routes/ai_agent.py", "_record_failed_chat_usage", "_record_usage", "both"),
    ("app/routes/ai_agent.py", "_record_usage", "persist_operation", "both"),
    ("app/routes/ai_agent.py", "_release_reserved_credits", "release_consumed_credits", "both"),
    ("app/routes/ai_agent.py", "_reserve_preflight_credits", "consume_credits", "both"),
    ("app/routes/ai_agent.py", "_rollback_promoted_session", "release_consumed_credits", "both"),
    ("app/routes/ai_agent.py", "_settle_reserved_credits", "consume_credits", "both"),
    ("app/routes/ai_agent.py", "_settle_reserved_credits", "release_consumed_credits", "both"),
    ("app/routes/ai_agent.py", "clarify_batch_idea", "bootstrap_legacy_credits", "both"),
    ("app/routes/ai_agent.py", "conversation_continue", "_persist_credit_deduction", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_continue", "_record_usage", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_continue", "_release_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_continue", "_reserve_preflight_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_continue", "_settle_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_continue", "bootstrap_legacy_credits", "both"),
    ("app/routes/ai_agent.py", "conversation_continue.event_stream", "_persist_credit_deduction", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_continue.event_stream", "_record_usage", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_continue.event_stream", "_release_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_continue.event_stream", "_settle_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_regenerate", "_persist_credit_deduction", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_regenerate", "_record_usage", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_regenerate", "_release_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_regenerate", "_reserve_preflight_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_regenerate", "_settle_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_regenerate", "bootstrap_legacy_credits", "both"),
    ("app/routes/ai_agent.py", "conversation_regenerate.event_stream", "_persist_credit_deduction", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_regenerate.event_stream", "_record_usage", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_regenerate.event_stream", "_release_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_regenerate.event_stream", "_settle_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_start", "_persist_credit_deduction", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_start", "_record_usage", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_start", "_release_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_start", "_reserve_preflight_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_start", "_settle_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_start", "bootstrap_legacy_credits", "both"),
    ("app/routes/ai_agent.py", "conversation_start.event_stream", "_persist_credit_deduction", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_start.event_stream", "_record_usage", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_start.event_stream", "_release_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "conversation_start.event_stream", "_settle_reserved_credits", "billing_line"),
    ("app/routes/ai_agent.py", "promote_all_batch_ideas", "bootstrap_legacy_credits", "both"),
    ("app/routes/ai_agent.py", "promote_batch_idea", "bootstrap_legacy_credits", "both"),
    ("app/routes/ai_agent.py", "rank_batch_ideas", "bootstrap_legacy_credits", "both"),
    ("app/routes/auth.py", "_enforce_admin_account_profile", "apply_plan_to_user", "both"),
    ("app/routes/auth.py", "_ensure_user_org", "ensure_default_organization_for_user", "both"),
    ("app/routes/auth.py", "_sso_user_and_membership", "apply_plan_to_user", "both"),
    ("app/routes/auth.py", "get_current_user", "bootstrap_legacy_credits", "both"),
    ("app/routes/auth.py", "get_current_user_from_cookie", "bootstrap_legacy_credits", "both"),
    ("app/routes/auth.py", "google_callback", "apply_plan_to_user", "both"),
    ("app/routes/auth.py", "google_callback", "bootstrap_legacy_credits", "both"),
    ("app/routes/auth.py", "login", "bootstrap_legacy_credits", "both"),
    ("app/routes/auth.py", "signup", "apply_plan_to_user", "both"),
    ("app/routes/auth.py", "sso_callback", "_sso_user_and_membership", "both"),
    ("app/routes/billing.py", "_fulfill_credit_pack_purchase", "_record_payment", "both"),
    ("app/routes/billing.py", "_fulfill_credit_pack_purchase", "grant_persistent_credit_pack", "both"),
    ("app/routes/billing.py", "_fulfill_limited_time_300k_invoice", "_record_payment", "both"),
    ("app/routes/billing.py", "_fulfill_limited_time_300k_invoice", "get_usage_meter_state", "both"),
    ("app/routes/billing.py", "_fulfill_limited_time_300k_invoice", "grant_limited_time_300k_offer", "both"),
    ("app/routes/billing.py", "_fulfill_limited_time_300k_payment_intent", "_record_payment", "both"),
    ("app/routes/billing.py", "_fulfill_limited_time_300k_payment_intent", "get_usage_meter_state", "both"),
    ("app/routes/billing.py", "_fulfill_limited_time_300k_payment_intent", "grant_limited_time_300k_offer", "both"),
    ("app/routes/billing.py", "create_checkout_session", "apply_plan_to_user", "both"),
    ("app/routes/billing.py", "get_billing_status", "apply_plan_to_user", "both"),
    ("app/routes/billing.py", "get_billing_status", "bootstrap_legacy_credits", "both"),
    ("app/routes/billing.py", "get_billing_status", "get_usage_meter_state", "both"),
    ("app/routes/billing.py", "modify_subscription", "apply_plan_to_user", "both"),
    ("app/routes/billing.py", "stripe_webhook", "_record_payment", "both"),
    ("app/routes/billing.py", "stripe_webhook", "apply_plan_to_user", "both"),
    ("app/routes/billing.py", "stripe_webhook", "cap_monthly_credits", "both"),
    ("app/routes/billing.py", "stripe_webhook", "get_usage_meter_state", "both"),
    ("app/routes/billing.py", "stripe_webhook", "grant_limited_time_300k_offer", "both"),
    ("app/routes/billing.py", "stripe_webhook", "reset_user_monthly_credits", "both"),
    ("app/routes/billing.py", "stripe_webhook", "reverse_limited_time_300k_credits", "both"),
    ("app/routes/billing.py", "stripe_webhook", "reverse_persistent_credit_pack", "both"),
    ("app/routes/billing.py", "sync_embedded_subscription", "apply_plan_to_user", "both"),
    ("app/routes/decision_asset_email.py", "request_email_assets", "record_telemetry", "both"),
    ("app/routes/strategy.py", "_build_execution_plan", "_record_claude_operation", "both"),
    ("app/routes/strategy.py", "_build_execution_plan", "reverse_customer_operation_charge", "both"),
    ("app/routes/strategy.py", "_record_claude_operation", "persist_operation", "both"),
    ("app/routes/strategy.py", "_record_claude_operation_batch", "_record_claude_operation", "both"),
    ("app/routes/strategy.py", "_record_claude_operation_batch", "persist_operation", "both"),
    ("app/routes/strategy.py", "analyze_project", "_record_claude_operation", "both"),
    ("app/routes/strategy.py", "analyze_project", "bootstrap_legacy_credits", "both"),
    ("app/routes/strategy.py", "analyze_project", "reverse_customer_operation_charge", "both"),
    ("app/routes/strategy.py", "chat_with_analysis", "bootstrap_legacy_credits", "both"),
    ("app/routes/strategy.py", "execution_assistant", "reverse_customer_operation_charge", "both"),
    ("app/routes/strategy.py", "portfolio_scores_agent", "bootstrap_legacy_credits", "both"),
    ("app/routes/strategy.py", "score_batch_queued", "finalize_batch_charge_allocation", "both"),
    ("app/routes/strategy.py", "score_batch_queued", "reverse_customer_operation_charge", "both"),
    ("app/routes/team.py", "list_user_organizations", "ensure_default_organization_for_user", "both"),
    ("app/routes/team.py", "remove_member", "ensure_default_organization_for_user", "both"),
    ("app/routes/teams.py", "_require_org_access", "sync_org_plan_and_commit", "both"),
    ("app/routes/teams.py", "accept_team_invitation", "sync_org_plan_and_commit", "both"),
    ("app/routes/teams.py", "create_team_org", "ensure_default_organization_for_user", "both"),
    ("create_user.py", "<module>", "create_user", "both"),
    ("scripts/backfill_payments.py", "main", "_record_payment", "both"),
    ("scripts/reset_monthly_credits.py", "reset_monthly_credits", "reset_user_monthly_credits", "both"),
)

def _expected(inventory, line):
    return {entry[:3] for entry in inventory if entry[3] in ("both", line)}


def _assert_matches(root, line):
    writes, references = scan(root)
    for found, inventory, kind in ((writes, LEGACY_FIELD_WRITERS, "field writer"),
                                   (references, LEGACY_MUTATOR_REFERENCES, "mutator reference")):
        expected = _expected(inventory, line)
        unlisted, missing = sorted(found - expected), sorted(expected - found)
        assert not unlisted, f"legacy {kind} not in the Phase 13 inventory: {unlisted}"
        assert not missing, f"inventory lists a legacy {kind} that no longer exists: {missing}"


def test_inventory_entries_are_unique_and_tagged():
    for inventory in (LEGACY_FIELD_WRITERS, LEGACY_MUTATOR_REFERENCES):
        keys = [entry[:3] for entry in inventory]
        assert len(keys) == len(set(keys))
        assert {entry[3] for entry in inventory} <= {"both", "billing_line", "unified_line"}


def test_every_legacy_billing_writer_on_this_line_is_inventoried():
    _assert_matches(BACKEND, "billing_line")


@pytest.mark.skipif(not os.environ.get("JASPEN_UNIFIED_LINE_BACKEND"),
                    reason="no unified-line backend directory configured")
def test_every_legacy_billing_writer_on_the_unified_line_is_inventoried():
    _assert_matches(Path(os.environ["JASPEN_UNIFIED_LINE_BACKEND"]).resolve(), "unified_line")


# ---------------------------------------------------------------------------
# M2 mutation self-tests: each reviewed pattern is detected; unrelated writes are not
# ---------------------------------------------------------------------------

PROBE = '''
from sqlalchemy import text, update
from app.billing_config import consume_credits as spend
from app.models import User as Member
import app.billing_config as legacy

def bulk_orm(session, User):
    session.query(User).filter_by(id=1).update({"credits_remaining": 0})
    session.query(User).update({User.plan_key: "team"})

def core_update(session, User):
    session.execute(update(User).values(subscription_plan="team"))

def raw_sql(session):
    session.execute(text("UPDATE users SET credits_remaining = 0 WHERE id = :id"))

def dynamic_setattr(user, field):
    setattr(user, field, 1)

def aliased(user):
    spend(user, 1)
    return Member(email="x")

def dynamic_getattr(user, name):
    getattr(legacy, name)(user)
    return getattr(legacy, "add_credits")

def meter_mutation(prefs):
    prefs["thinking_power"]["remaining"] = 1
    prefs["thinking_power"].update(remaining=2)

def revocation(grant, entitlement, now):
    grant.status = "reversed"
    entitlement.revoked_at = now

def writer_helper(user):
    user.credits_remaining = 7

def new_call_site(user):
    writer_helper(user)
'''

CONTROL = '''
from sqlalchemy import text

def unrelated(user, project, auth_session, session, data, obj, now, Project):
    user.name = "x"
    project.status = "done"
    auth_session.revoked_at = now
    data["other"]["remaining"] = 1
    data["other"].update(remaining=2)
    session.query(Project).update({"title": "t"})
    session.execute(text("UPDATE projects SET title = 't'"))
    setattr(obj, "title", 1)
    return getattr(obj, "name")
'''


def _probe(tmp_path, source):
    (tmp_path / "app").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "app" / "probe.py").write_text(source)
    return scan(tmp_path)


def test_m2_every_reviewed_write_pattern_is_detected(tmp_path):
    writes, references = _probe(tmp_path, PROBE)
    path = "app/probe.py"
    expected_writes = {
        (path, "bulk_orm", "credits_remaining"), (path, "bulk_orm", "plan_key"),
        (path, "core_update", "subscription_plan"),
        (path, "raw_sql", "sql:users"),
        (path, "dynamic_setattr", "setattr(dynamic)"),
        (path, "aliased", "User()"),
        (path, "meter_mutation", "thinking_power"),
        (path, "revocation", "status"), (path, "revocation", "revoked_at"),
        (path, "writer_helper", "credits_remaining"),
    }
    expected_references = {
        (path, "aliased", "consume_credits"),
        (path, "dynamic_getattr", "getattr(dynamic)"), (path, "dynamic_getattr", "add_credits"),
        (path, "new_call_site", "writer_helper"),
    }
    assert expected_writes <= writes, sorted(expected_writes - writes)
    assert expected_references <= references, sorted(expected_references - references)


def test_m2_negative_control_unrelated_writes_are_not_flagged(tmp_path):
    assert _probe(tmp_path, CONTROL) == (set(), set())


# ---------------------------------------------------------------------------
# M2b (re-acceptance 2026-11-17): the probes the M2 scanner missed
# ---------------------------------------------------------------------------

PROBE_M2B = '''
from sqlalchemy import insert, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from app.models import AccountEntitlement, PersistentCreditGrant, User as Member

def meter_keyword(o, m):
    dict(o.settings).update(thinking_power=m)

def meter_keyword_constructor(o, m):
    o.settings = dict(o.settings, thinking_power=m)

def grant_status_any_name(session, gid, now):
    row = session.get(PersistentCreditGrant, gid)
    row.status = "reversed"
    row.reversed_at = now

def entitlement_revocation_any_name(session, eid, now):
    x = session.query(AccountEntitlement).get(eid)
    x.revoked_at = now
    setattr(x, "status", "revoked")

def grant_status_bulk_payload(session, gid):
    session.query(PersistentCreditGrant).filter_by(id=gid).update({"status": "reversed"})

def core_update_dynamic(session, payload):
    session.execute(update(Member).values(**payload))

def core_insert(session, rows):
    session.execute(insert(PersistentCreditGrant), rows)

def dialect_insert(session, values):
    session.execute(postgresql_insert(AccountEntitlement).values(**values))

def execute_mappings(session):
    session.execute(update(Member), [{"id": 1, "credits_remaining": 0}])

def bulk_mappings(session):
    session.bulk_update_mappings(Member, [{"id": 1, "credits_remaining": 0}])
    session.bulk_insert_mappings(PersistentCreditGrant, [{"remaining_amount": 5}])

def query_bulk_dynamic(session, payload):
    session.query(Member).filter(Member.id == 1).update(payload, synchronize_session=False)
    session.query(PersistentCreditGrant).delete()
'''

CONTROL_M2B = '''
from sqlalchemy import insert, update
from app.models import Project, IdempotencyRegistry

def unrelated(session, settings, project, rows, payload, now, feed):
    settings.update(theme="dark")
    dict(settings, other=1)
    project.status = "done"
    project.revoked_at = now
    session.execute(update(Project).values(**payload))
    session.execute(insert(IdempotencyRegistry), rows)
    session.bulk_update_mappings(Project, [{"id": 1, "status": "x"}])
    session.query(Project).update(payload)
    feed.insert(0, {"status": "x"})
'''


def test_m2b_every_missed_probe_is_detected(tmp_path):
    writes, _references = _probe(tmp_path, PROBE_M2B)
    path = "app/probe.py"
    expected = {
        (path, "meter_keyword", "thinking_power"),
        (path, "meter_keyword_constructor", "thinking_power"),
        (path, "grant_status_any_name", "status"), (path, "grant_status_any_name", "reversed_at"),
        (path, "entitlement_revocation_any_name", "revoked_at"), (path, "entitlement_revocation_any_name", "status"),
        (path, "grant_status_bulk_payload", "status"),
        (path, "grant_status_bulk_payload", "query(PersistentCreditGrant).update"),
        (path, "core_update_dynamic", "update(User)"),
        (path, "core_insert", "insert(PersistentCreditGrant)"),
        (path, "dialect_insert", "insert(AccountEntitlement)"),
        (path, "execute_mappings", "update(User)"), (path, "execute_mappings", "credits_remaining"),
        (path, "bulk_mappings", "bulk_update_mappings(User)"), (path, "bulk_mappings", "credits_remaining"),
        (path, "bulk_mappings", "bulk_insert_mappings(PersistentCreditGrant)"),
        (path, "bulk_mappings", "remaining_amount"),
        (path, "query_bulk_dynamic", "query(User).update"),
        (path, "query_bulk_dynamic", "query(PersistentCreditGrant).delete"),
    }
    assert expected <= writes, sorted(expected - writes)


def test_m2b_negative_control_unrelated_bulk_and_status_writes_are_not_flagged(tmp_path):
    assert _probe(tmp_path, CONTROL_M2B) == (set(), set())
