"""I1: row-17 family switches, the billing model boundary and the identity family."""

from datetime import timezone
import os
import uuid

import pytest
import sqlalchemy as sa
from werkzeug.security import generate_password_hash

from app import billing_cutover as bc
from app import billing_migration as bm
from app.models import (
    AIOperation,
    BillingAccount,
    BillingRoleGrant,
    Organization,
    OrganizationMember,
    Payment,
    PersistentCreditGrant,
    User,
)
from app.models_billing_identity import BillingModelAssignment


REVISION = "a1f3c5e7b9d0"
TABLE = "billing_model_assignments"
ON = bc.CutoverConfig(frozenset({"identity"}), ())
PG = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="local disposable PostgreSQL is not configured")


def _user(session, label=None):
    label = label or uuid.uuid4().hex[:10]
    user = User(email=f"{label}@example.invalid", name=label,
                password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
                subscription_plan="free", credits_remaining=0, seat_limit=1, max_seats=1)
    session.add(user)
    session.flush()
    return user


def _org(session, owner, *, members=()):
    org = Organization(name=f"Org {uuid.uuid4().hex[:6]}", slug=f"org-{uuid.uuid4().hex[:10]}",
                       owner_user_id=owner.id, plan_key="free")
    session.add(org)
    session.flush()
    for user, role in ((owner, "owner"), *((m, "creator") for m in members)):
        session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role, status="active"))
    session.flush()
    return org


def _establish(session, org, actor=None, **overrides):
    values = dict(organization_id=org.id, actor_user_id=org.owner_user_id if actor is None else actor.id,
                  currency="usd", origin_type="test", origin_id=f"test:{org.id}", config=ON)
    values.update(overrides)
    return bc.establish_modern_billing_identity(session, **values)


def _modern(session):
    owner = _user(session)
    org = _org(session, owner)
    assignment, _state = _establish(session, org)
    session.commit()
    return owner, org, assignment


# ---------------------------------------------------------------------------
# Family switches
# ---------------------------------------------------------------------------

def test_every_family_is_off_by_default():
    config = bc.load_cutover_config({})
    assert config.families == frozenset() and config.errors == ()
    assert not any(config.enabled(family) for family in bc.FAMILIES)


def test_families_must_be_enabled_in_d18_order():
    assert bc.load_cutover_config({bc.SETTING: "identity"}).families == {"identity"}
    assert bc.load_cutover_config({bc.SETTING: "identity, financial_events"}).families == {
        "identity", "financial_events"}
    for value in ("financial_events", "identity,credit_funding", "identity,bogus", "identity,identity"):
        config = bc.load_cutover_config({bc.SETTING: value})
        assert config.families == frozenset() and config.errors, value


@pytest.mark.parametrize("variable,value", [("APP_ENV", "production"), ("STRIPE_SECRET_KEY", "sk_live_x")])
def test_switches_are_refused_in_a_production_runtime(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    config = bc.load_cutover_config({bc.SETTING: "identity"})
    assert config.families == frozenset()
    assert any("production runtime" in error for error in config.errors)


def test_unknown_family_names_are_programming_errors():
    with pytest.raises(ValueError):
        ON.enabled("payments")


# ---------------------------------------------------------------------------
# Identity family command
# ---------------------------------------------------------------------------

def test_establish_is_refused_while_the_identity_family_is_off(db):
    session = db.session
    owner = _user(session)
    org = _org(session, owner)
    with pytest.raises(bc.BillingFamilyDisabledError):
        _establish(session, org, config=bc.load_cutover_config({}))
    session.rollback()
    assert session.query(BillingAccount).count() == 0 and session.query(BillingModelAssignment).count() == 0


def test_establish_creates_the_account_owner_role_and_assignment_once(db):
    session = db.session
    owner, org, assignment = _modern(session)
    account = session.get(BillingAccount, assignment.billing_account_id)
    assert account.organization_id == org.id and account.status == "active" and account.currency == "usd"
    assert account.processor is None and account.processor_customer_id is None
    assert account.account_anchor_at.replace(tzinfo=timezone.utc) == org.created_at.replace(tzinfo=timezone.utc)
    grants = session.query(BillingRoleGrant).filter_by(billing_account_id=account.id).all()
    assert [(g.user_id, g.role, g.state) for g in grants] == [(owner.id, "billing_owner", "active")]
    assert assignment.model == "modern" and assignment.footprint_json == {"checked_users": [owner.id], "codes": []}
    assert bc.organization_billing_model(session, org.id) == "modern"
    assert bc.user_billing_model(session, owner.id) == "modern"

    replay, state = _establish(session, org)
    assert state == "replayed" and replay.id == assignment.id
    with pytest.raises(bc.BillingIdentityConflictError):
        _establish(session, org, currency="eur")
    session.rollback()
    assert session.query(BillingAccount).count() == 1 and session.query(BillingRoleGrant).count() == 1


def test_only_the_owner_establishes_and_input_is_validated(db):
    session = db.session
    owner = _user(session)
    member = _user(session)
    org = _org(session, owner, members=[member])
    with pytest.raises(bc.BillingIdentityError, match="owner"):
        _establish(session, org, actor=member)
    session.rollback()
    for bad in ({"currency": "USD"}, {"currency": "us"}, {"origin_type": " "}, {"organization_id": ""}):
        with pytest.raises(bc.BillingIdentityError):
            _establish(session, org, **bad)
        session.rollback()


def _stripe_customer(session, user, org):
    user.stripe_customer_id = f"cus_{uuid.uuid4().hex[:10]}"


def _payment(session, user, org):
    session.add(Payment(external_reference=f"pi_{uuid.uuid4().hex[:10]}", source="stripe", user_id=user.id,
                        amount_paid_cents=100, amount_due_cents=100, currency="usd"))


def _grant(session, user, org):
    session.add(PersistentCreditGrant(user_id=user.id, organization_id=org.id, source="admin", original_amount=1,
                                      remaining_amount=1, external_reference=f"g_{uuid.uuid4().hex[:10]}"))


def _operation(session, user, org):
    session.add(AIOperation(id=str(uuid.uuid4()), user_id=user.id, organization_id=org.id, status="succeeded",
                            operation_type="conversation", router_version="t", policy_version="t"))


def _other_legacy_membership(session, user, org):
    _org(session, _user(session), members=[user])


def _thinking_power(session, user, org):
    org.settings = {"thinking_power": {"remaining": 1}}


def _phase14_account(session, user, org):
    session.add(BillingAccount(organization_id=org.id, status="proposed", currency="usd",
                               account_anchor_at=org.created_at.replace(tzinfo=timezone.utc)))


def _attr(target, **values):
    def make(session, user, org):
        for name, value in values.items():
            setattr(user if target == "user" else org, name, value)
    return make


@pytest.mark.parametrize("make,code", [
    (_attr("user", subscription_plan="team"), "legacy_plan"),
    (_attr("user", subscription_status="active"), "legacy_subscription_status"),
    (_attr("user", unlimited_analysis=True), "unlimited_analysis"),
    (_attr("user", credits_remaining=None), "unlimited_credits"),
    (_attr("user", credits_remaining=999_999_999), "legacy_credit_balance"),
    (_attr("user", seat_limit=5), "legacy_seats"),
    (_attr("org", plan_key="team"), "organization_plan"),
    (_attr("org", max_total_paid_seats=4), "organization_seats"),
    (_stripe_customer, "processor_customer"),
    (_payment, "payments"),
    (_grant, "persistent_credit_grants"),
    (_operation, "ai_operations"),
    (_thinking_power, "organization_thinking_power"),
    (_phase14_account, "billing_account_exists"),
])
def test_an_organization_with_legacy_billing_state_is_never_assigned(db, make, code):
    session = db.session
    owner = _user(session)
    org = _org(session, owner)
    make(session, owner, org)
    session.flush()
    with pytest.raises(bc.BillingModelConflictError) as raised:
        _establish(session, org)
    assert code in raised.value.codes
    session.rollback()
    assert session.query(BillingModelAssignment).count() == 0


def test_only_the_organization_and_its_owner_must_be_clean(db):
    """A member's personal legacy state stays theirs; the owner's is synced into the organization by legacy code."""
    session = db.session
    owner = _user(session)
    member = _user(session)
    org = _org(session, owner, members=[member])
    _payment(session, member, org)
    _other_legacy_membership(session, member, org)
    member.subscription_plan = "team"
    session.flush()
    assignment, state = _establish(session, org)
    assert state == "inserted"
    session.rollback()


# ---------------------------------------------------------------------------
# The central legacy write guard
# ---------------------------------------------------------------------------

def test_without_any_modern_organization_legacy_writes_are_untouched(db):
    session = db.session
    user = _user(session)
    org = _org(session, user)
    _stripe_customer(session, user, org)
    _payment(session, user, org)
    _grant(session, user, org)
    _other_legacy_membership(session, user, org)
    session.commit()


def _org_payment(session, user, org):
    session.add(Payment(external_reference=f"pi_{uuid.uuid4().hex[:10]}", source="stripe", user_id=user.id,
                        organization_id=org.id, amount_paid_cents=100, amount_due_cents=100, currency="usd"))


def test_legacy_money_attributed_to_a_modern_organization_is_refused(db):
    session = db.session
    owner, org, _assignment = _modern(session)
    for write in (_org_payment, _grant):
        write(session, owner, org)
        with pytest.raises(bc.BillingModelConflictError):
            session.flush()
        session.rollback()
    # Personal legacy state of the same person stays legacy, and a legacy organization keeps every write.
    _stripe_customer(session, owner, org)
    _payment(session, owner, org)
    session.commit()
    legacy = _user(session)
    legacy_org = _org(session, legacy)
    for write in (_stripe_customer, _org_payment, _grant):
        write(session, legacy, legacy_org)
    session.commit()


def test_a_modern_accounts_processor_customer_never_becomes_a_legacy_payer(db):
    session = db.session
    owner, org, assignment = _modern(session)
    bc.bind_processor_customer(session, billing_account_id=assignment.billing_account_id, processor="stripe",
                               processor_customer_id="cus_modern_only", actor_user_id=owner.id, config=ON)
    session.commit()
    legacy = _user(session)
    legacy.stripe_customer_id = "cus_modern_only"
    with pytest.raises(bc.BillingModelConflictError, match="modern billing account"):
        session.flush()
    session.rollback()


@pytest.mark.parametrize("field,value", [
    ("plan_key", "business"), ("max_total_paid_seats", 9), ("seat_policy_overrides", {"creator": 9}),
])
def test_direct_legacy_entitlement_edits_of_a_modern_organization_are_refused(db, field, value):
    """Admin edits and plan sync write these straight onto the row; a modern organization never takes them."""
    session = db.session
    _owner, org, _assignment = _modern(session)
    setattr(org, field, value)
    with pytest.raises(bc.BillingModelConflictError):
        session.flush()
    session.rollback()
    legacy_org = _org(session, _user(session))
    session.commit()
    setattr(legacy_org, field, value)
    session.commit()  # a legacy organization keeps them


def test_the_owners_personal_plan_is_never_synced_into_a_modern_organization(db):
    from app.orgs import sync_org_plan_from_owner
    session = db.session
    owner, org, _assignment = _modern(session)
    owner.subscription_plan = "team"  # personal legacy state: allowed
    session.commit()
    assert sync_org_plan_from_owner(org) is False and org.plan_key == "free"
    session.commit()


def test_rewriting_an_unchanged_value_is_not_an_edit(db):
    session = db.session
    owner, org, _assignment = _modern(session)
    org.plan_key = "free"
    session.commit()


def test_people_may_belong_to_both_models(db):
    """The multi-user organization model: memberships never decide billing ownership."""
    session = db.session
    owner, org, _assignment = _modern(session)
    paid = _user(session)
    _payment(session, paid, org)
    _other_legacy_membership(session, paid, org)
    session.add(OrganizationMember(organization_id=org.id, user_id=paid.id, role="creator", status="active"))
    legacy_org = _org(session, _user(session))
    session.add(OrganizationMember(organization_id=legacy_org.id, user_id=owner.id, role="creator",
                                   status="active"))
    session.commit()
    assert bc.organization_billing_model(session, org.id) == "modern"
    assert bc.organization_billing_model(session, legacy_org.id) == "legacy"


def test_legacy_billing_commands_answer_409_for_a_modern_account_and_never_reach_stripe(
        client, db, test_user, auth_headers, monkeypatch):
    import app.routes.billing as billing_routes

    def forbidden(*args, **kwargs):
        raise AssertionError("Stripe must not be called for a modern account")

    monkeypatch.setattr(billing_routes.stripe.checkout.Session, "create", forbidden)
    monkeypatch.setattr(billing_routes.stripe.Customer, "create", forbidden)
    session = db.session
    org = _org(session, test_user)
    _establish(session, org)
    session.commit()
    response = client.post("/api/v1/billing/create-checkout-session", json={"plan": "essential"},
                           headers=auth_headers)
    assert response.status_code == 409
    assert response.get_json()["error"] == "billing_model_conflict"
    # Reads and the processor webhook are not commands and keep their own behavior.
    assert client.get("/api/v1/billing/plans").status_code == 200
    assert client.post("/api/v1/billing/webhook", data=b"{}", headers=auth_headers).status_code != 409


def test_billing_commands_follow_the_context_organization(client, db, test_user, auth_headers):
    """A member of a modern organization whose context is a legacy organization keeps legacy commands."""
    session = db.session
    _owner, modern_org, _assignment = _modern(session)
    own = _org(session, test_user)
    session.add(OrganizationMember(organization_id=modern_org.id, user_id=test_user.id, role="creator",
                                   status="active"))
    test_user.active_organization_id = own.id
    session.commit()
    assert bc.context_organization_id(session, test_user.id) == own.id
    response = client.post("/api/v1/billing/create-payment-intent", json={"amount": 0}, headers=auth_headers)
    assert response.status_code == 400  # the route's own validation, not the boundary
    test_user.active_organization_id = modern_org.id
    session.commit()
    response = client.post("/api/v1/billing/create-payment-intent", json={"amount": 0}, headers=auth_headers)
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Phase 14 never establishes a modern organization
# ---------------------------------------------------------------------------

def test_phase14_quarantines_a_modern_organization(db):
    session = db.session
    _owner, org, _assignment = _modern(session)
    plan = bm.plan_establishment(session, organization_id=org.id)
    assert "modern_billing_account" in [c["code"] for c in plan["quarantine"]]
    session.rollback()


# ---------------------------------------------------------------------------
# Processor customer binding
# ---------------------------------------------------------------------------

def test_a_processor_customer_binds_once_to_a_modern_account(db):
    session = db.session
    owner, org, assignment = _modern(session)
    bind = dict(billing_account_id=assignment.billing_account_id, processor="stripe", actor_user_id=owner.id,
                config=ON)
    account, state = bc.bind_processor_customer(session, processor_customer_id="cus_modern_1", **bind)
    assert state == "bound" and account.processor_customer_id == "cus_modern_1"
    assert bc.bind_processor_customer(session, processor_customer_id="cus_modern_1", **bind)[1] == "unchanged"
    with pytest.raises(bc.BillingIdentityConflictError):
        bc.bind_processor_customer(session, processor_customer_id="cus_other", **bind)
    stranger = _user(session)
    with pytest.raises(bc.BillingIdentityError, match="billing authority"):
        bc.bind_processor_customer(session, processor_customer_id="cus_modern_1",
                                   **{**bind, "actor_user_id": stranger.id})
    with pytest.raises(bc.BillingFamilyDisabledError):
        bc.bind_processor_customer(session, processor_customer_id="cus_modern_1",
                                   **{**bind, "config": bc.load_cutover_config({})})
    session.rollback()


def test_binding_refuses_legacy_accounts_and_legacy_payers_customers(db):
    session = db.session
    owner, org, assignment = _modern(session)
    legacy = _user(session)
    legacy.stripe_customer_id = "cus_legacy_payer"
    legacy_org = _org(session, legacy)
    legacy_account = BillingAccount(organization_id=legacy_org.id, status="proposed", currency="usd",
                                    account_anchor_at=legacy_org.created_at.replace(tzinfo=timezone.utc))
    session.add(legacy_account)
    session.commit()
    with pytest.raises(bc.BillingModelConflictError):
        bc.bind_processor_customer(session, billing_account_id=legacy_account.id, processor="stripe",
                                   processor_customer_id="cus_x", actor_user_id=legacy.id, config=ON)
    with pytest.raises(bc.BillingModelConflictError, match="legacy payer"):
        bc.bind_processor_customer(session, billing_account_id=assignment.billing_account_id, processor="stripe",
                                   processor_customer_id="cus_legacy_payer", actor_user_id=owner.id, config=ON)
    session.rollback()


# ---------------------------------------------------------------------------
# Schema: the revision, its literal checks, SQLite guards and round trip
# ---------------------------------------------------------------------------

def _revision():
    from alembic.script import ScriptDirectory
    from tests.test_billing_migration import MIGRATIONS_DIR
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_revision(REVISION).module


def test_revision_extends_bi1_and_is_the_single_head():
    from alembic.script import ScriptDirectory
    from tests.test_billing_migration import MIGRATIONS_DIR
    script = ScriptDirectory(str(MIGRATIONS_DIR))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == "c8a9989843b5"


def test_revision_check_constraints_are_literal_copies_of_the_model():
    model = {c.name: str(c.sqltext) for c in BillingModelAssignment.__table__.constraints
             if isinstance(c, sa.CheckConstraint)}
    assert {name: sql for sql, name in _revision().CHECKS} == model


STUBS = (
    "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)",
    "CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY, owner_user_id VARCHAR(36))",
    "CREATE TABLE billing_accounts (id VARCHAR(36) PRIMARY KEY, organization_id VARCHAR(36), status VARCHAR(24))",
    "CREATE TABLE idempotency_registry (id VARCHAR(36) PRIMARY KEY, namespace VARCHAR(64), key VARCHAR(255))",
    "CREATE TABLE billing_migration_establishments (id VARCHAR(36) PRIMARY KEY, organization_id VARCHAR(36), "
    "outcome VARCHAR(24))",
)


def _sqlite_engine(tmp_path):
    """The parent tables the revision and its guards reference, reduced to the columns they read."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'i1.sqlite'}")
    with engine.begin() as connection:
        for statement in STUBS:
            connection.execute(sa.text(statement))
    return engine


def _schema(engine):
    with engine.connect() as connection:
        return sorted(tuple(r) for r in connection.execute(sa.text(
            "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")))


def _ops(engine):
    from tests.test_billing_migration import _ops as ops
    return ops(engine)


def _seed(connection, *, owner="u1", status="active", claim=True):
    connection.execute(sa.text("INSERT INTO users (id) VALUES ('u1'), ('u2')"))
    connection.execute(sa.text("INSERT INTO organizations (id, owner_user_id) VALUES ('o1', :owner)"),
                       {"owner": owner})
    connection.execute(sa.text("INSERT INTO billing_accounts (id, organization_id, status) VALUES ('a1', 'o1', :s)"),
                       {"s": status})
    if claim:
        connection.execute(sa.text("INSERT INTO idempotency_registry (id, namespace, key) "
                                   f"VALUES ('r1', '{bc.NAMESPACE}', 'organization:o1')"))


INSERT = (f"INSERT INTO {TABLE} (id, organization_id, billing_account_id, model, rule_version, "
          "assigned_by_user_id, origin_type, origin_id, footprint_json, request_fingerprint, "
          "idempotency_registry_id, assigned_at) VALUES ('m1', 'o1', 'a1', 'modern', "
          "'jaspen.billing.model_assignment.v1', 'u1', 'test', 'test', '{}', :fp, 'r1', CURRENT_TIMESTAMP)")


def test_sqlite_round_trip_is_exact_and_the_guards_hold(tmp_path):
    module = _revision()
    engine = _sqlite_engine(tmp_path)
    try:
        parent = _schema(engine)
        with _ops(engine):
            module.upgrade()
        assert set(module.SQLITE_TRIGGERS) <= {row[1] for row in _schema(engine)}
        with _ops(engine):
            module.downgrade()
        assert _schema(engine) == parent
        with _ops(engine):
            module.upgrade()
        for seed, match in ((dict(claim=False), "idempotency claim"), (dict(status="proposed"), "active billing"),
                            (dict(owner="u2"), "owner")):
            with engine.connect() as connection:
                transaction = connection.begin()
                _seed(connection, **seed)
                with pytest.raises(sa.exc.DatabaseError, match=match):
                    connection.execute(sa.text(INSERT), {"fp": "a" * 64})
                transaction.rollback()
        with engine.begin() as connection:
            _seed(connection)
            connection.execute(sa.text(INSERT), {"fp": "a" * 64})
        for statement in (f"UPDATE {TABLE} SET origin_id='x'", f"DELETE FROM {TABLE}"):
            with engine.begin() as connection, pytest.raises(sa.exc.DatabaseError, match="immutable"):
                connection.execute(sa.text(statement))
        with engine.begin() as connection, pytest.raises(sa.exc.DatabaseError, match="Phase 14 cannot establish"):
            connection.execute(sa.text("INSERT INTO billing_migration_establishments (id, organization_id, outcome) "
                                       "VALUES ('e1', 'o1', 'established')"))
        with engine.begin() as connection:  # the quarantine is still recorded
            connection.execute(sa.text("INSERT INTO billing_migration_establishments (id, organization_id, outcome) "
                                       "VALUES ('e2', 'o1', 'quarantined')"))
        with pytest.raises(module.ModelAssignmentsNotEmptyError), _ops(engine):
            module.downgrade()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL 18: the fully migrated database, guards live
# ---------------------------------------------------------------------------

def _pg_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("local disposable PostgreSQL is not configured")
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision != REVISION:
        engine.dispose()
        pytest.fail(f"I1 migrated tests require Alembic head {REVISION}; found {revision!r}")
    return engine


@PG
def test_postgres_the_command_writes_and_the_guards_refuse_everything_else():
    from sqlalchemy.orm import Session
    engine = _pg_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            owner = _user(session)
            org = _org(session, owner)
            assignment, state = _establish(session, org)
            session.commit()
            assert state == "inserted"
        values = {c.name: getattr(assignment, c.name) for c in BillingModelAssignment.__table__.columns
                  if c.name != "created_at"}
        for statement in (f"UPDATE {TABLE} SET origin_id='x' WHERE id=:id", f"DELETE FROM {TABLE} WHERE id=:id"):
            with engine.begin() as connection, pytest.raises(sa.exc.DBAPIError, match="immutable"):
                connection.execute(sa.text(statement), {"id": assignment.id})
        with engine.begin() as connection, pytest.raises(sa.exc.DBAPIError, match="immutable"):
            connection.execute(sa.text(f"TRUNCATE {TABLE}"))
        # A second assignment forged around the command: a fresh organization and account, no claim.
        with Session(engine, expire_on_commit=False) as session:
            other_owner = _user(session)
            other = _org(session, other_owner)
            account = BillingAccount(organization_id=other.id, status="active", currency="usd",
                                     account_anchor_at=other.created_at.replace(tzinfo=timezone.utc))
            session.add(account)
            session.commit()
        forged = {**values, "id": str(uuid.uuid4()), "organization_id": other.id, "billing_account_id": account.id,
                  "assigned_by_user_id": other_owner.id}
        with engine.begin() as connection, pytest.raises(sa.exc.DBAPIError, match="idempotency claim"):
            connection.execute(sa.insert(BillingModelAssignment.__table__).values(**forged))
    finally:
        engine.dispose()


@PG
def test_postgres_both_guards_are_installed_by_the_revision():
    engine = _pg_engine()
    try:
        with engine.connect() as connection:
            triggers = set(connection.execute(sa.text(
                "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN "
                "('billing_model_assignments'::regclass, 'billing_migration_establishments'::regclass)"
            )).scalars())
        assert {name for name, _table, _body in _revision().PG_TRIGGERS} <= triggers
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The operator command line
# ---------------------------------------------------------------------------

def _cli(app, argv, capsys):
    import importlib.util
    import json
    from tests.test_billing_migration import BACKEND
    spec = importlib.util.spec_from_file_location("billing_identity", BACKEND / "scripts" / "billing_identity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.run(argv, app=app)
    return code, json.loads(capsys.readouterr().out or "null")


@pytest.mark.parametrize("variable,value", [("APP_ENV", "production"), ("STRIPE_SECRET_KEY", "sk_live_example")])
def test_the_command_line_refuses_a_production_runtime(app, capsys, monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    code, out = _cli(app, ["status", "--organization-id", "x"], capsys)
    assert code == 2 and "production runtime" in out["error"]


def test_the_command_line_establishes_only_when_confirmed_and_enabled(db, app, capsys, monkeypatch):
    session = db.session
    owner = _user(session)
    org = _org(session, owner)
    session.commit()
    argv = ["establish", "--organization-id", org.id, "--actor-user-id", owner.id, "--currency", "usd",
            "--origin-id", "seed:test"]
    code, out = _cli(app, argv, capsys)
    assert code == 2 and "--confirm-write" in out["error"]
    code, out = _cli(app, argv + ["--confirm-write"], capsys)
    assert code == 3 and "not enabled" in out["error"]
    assert session.query(BillingModelAssignment).count() == 0
    monkeypatch.setenv(bc.SETTING, "identity")
    code, out = _cli(app, argv + ["--confirm-write"], capsys)
    assert code == 0 and out["state"] == "inserted"
    code, out = _cli(app, ["status", "--organization-id", org.id], capsys)
    assert code == 0 and out["billing_model"] == "modern" and out["families_enabled"] == ["identity"]
    assert out["billing_account"]["status"] == "active" and out["footprint"] == []


@PG
def test_postgres_a_legacy_grant_racing_the_first_assignment_is_serialized_and_refused():
    """The guard's FOR KEY SHARE waits for establish's FOR UPDATE, then sees the committed assignment."""
    import threading
    from sqlalchemy.orm import Session
    engine = _pg_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            owner = _user(session)
            org = _org(session, owner)
            session.commit()
        written = {}
        with Session(engine.execution_options(isolation_level="READ COMMITTED"), expire_on_commit=False) as first:
            _establish(first, org)  # holds FOR UPDATE on the organization until commit

            def grant():
                with Session(engine.execution_options(isolation_level="READ COMMITTED")) as second:
                    _grant(second, owner, org)
                    try:
                        second.flush()
                        second.commit()
                        written["result"] = "written"
                    except bc.BillingModelConflictError:
                        second.rollback()
                        written["result"] = "refused"

            worker = threading.Thread(target=grant)
            worker.start()
            worker.join(timeout=2)
            assert worker.is_alive(), "the guarded write must wait for the assignment's transaction"
            first.commit()
        worker.join(timeout=30)
        assert written == {"result": "refused"}
    finally:
        engine.dispose()


@PG
def test_postgres_the_guard_lock_never_deadlocks_two_legacy_updates_of_one_organization():
    """With no modern organization at all (production), two members' guarded writes followed by updates of
    their shared organization both succeed: the guard's lock does not conflict with an ordinary UPDATE."""
    import threading
    from sqlalchemy.orm import Session
    engine = _pg_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            owner = _user(session)
            member = _user(session)
            org = _org(session, owner, members=[member])
            session.commit()
        barrier, results = threading.Barrier(2, timeout=10), {}

        def work(label, user_id, seats):
            with Session(engine.execution_options(isolation_level="READ COMMITTED")) as session:
                try:
                    _grant(session, session.get(User, user_id), session.get(Organization, org.id))
                    session.flush()  # the guard runs and locks the organization
                    barrier.wait()
                    session.get(Organization, org.id).name = f"Updated by {label}"
                    session.flush()
                    session.commit()
                    results[label] = "ok"
                except Exception as exc:  # noqa: BLE001 - the regression is any failure here
                    session.rollback()
                    results[label] = type(exc).__name__

        threads = [threading.Thread(target=work, args=("a", owner.id, 2)),
                   threading.Thread(target=work, args=("b", member.id, 3))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert results == {"a": "ok", "b": "ok"}
    finally:
        engine.dispose()


def test_the_dispatch_contract_names_exactly_one_handler(db):
    session = db.session
    owner, org, assignment = _modern(session)
    legacy = _user(session)
    _org(session, legacy)
    session.commit()
    assert bc.modern_context(session, family="financial_events", user_id=legacy.id, config=ON) is None
    with pytest.raises(bc.BillingFamilyDisabledError):
        bc.modern_context(session, family="financial_events", user_id=owner.id, config=ON)
    both = bc.CutoverConfig(frozenset({"identity", "financial_events"}), ())
    context = bc.modern_context(session, family="financial_events", organization_id=org.id, config=both)
    assert context == bc.ModernContext(org.id, assignment.billing_account_id)
