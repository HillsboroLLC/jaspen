"""Focused Phase 2.1 organization-first billing foundation tests."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models import (
    BillingAccount,
    BillingRoleGrant,
    Organization,
    OrganizationMember,
)


def _organization(db, user, suffix="primary"):
    organization = Organization(
        name=f"Billing foundation {suffix}",
        slug=f"billing-foundation-{suffix}",
        owner_user_id=user.id,
        plan_key="free",
    )
    db.session.add(organization)
    db.session.commit()
    return organization


def _account(db, organization, suffix="primary"):
    account = BillingAccount(
        organization_id=organization.id,
        currency="usd",
        account_anchor_at=datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc),
        processor="stripe",
        processor_customer_id=f"cus_phase_2_1_{suffix}",
    )
    db.session.add(account)
    db.session.commit()
    return account


def test_existing_organization_creation_does_not_provision_billing_rows(db, test_user):
    _organization(db, test_user)

    assert db.session.query(BillingAccount).count() == 0
    assert db.session.query(BillingRoleGrant).count() == 0


def test_billing_account_is_owned_only_by_the_organization(db, test_user):
    organization = _organization(db, test_user)
    account = _account(db, organization)

    assert account.organization_id == organization.id
    assert account.organization is organization
    assert organization.billing_account is account
    assert "user_id" not in BillingAccount.__table__.columns
    assert "owner_user_id" not in BillingAccount.__table__.columns


def test_billing_role_is_independent_of_membership_plan_and_admin(db, test_user):
    organization = _organization(db, test_user)
    account = _account(db, organization)
    starts_at = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)

    grant = BillingRoleGrant(
        billing_account_id=account.id,
        user_id=test_user.id,
        role="billing_owner",
        starts_at=starts_at,
        granted_by_user_id=test_user.id,
        origin_type="authorized_command",
        origin_id="phase-2-1-test",
    )
    db.session.add(grant)
    db.session.commit()

    assert grant.billing_account_id == account.id
    assert grant.user_id == test_user.id
    assert grant.role == "billing_owner"
    assert grant.state == "active"
    assert db.session.query(OrganizationMember).count() == 0
    assert organization.plan_key == "free"


def test_billing_account_constraints_and_processor_uniqueness(db, test_user):
    first_org = _organization(db, test_user, "first")
    second_org = _organization(db, test_user, "second")
    _account(db, first_org, "shared")

    duplicate_org = BillingAccount(
        organization_id=first_org.id,
        currency="usd",
        account_anchor_at=datetime.now(timezone.utc),
    )
    db.session.add(duplicate_org)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    invalid_status = BillingAccount(
        organization_id=second_org.id,
        status="paid",
        currency="usd",
        account_anchor_at=datetime.now(timezone.utc),
    )
    db.session.add(invalid_status)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    duplicate_processor = BillingAccount(
        organization_id=second_org.id,
        currency="usd",
        account_anchor_at=datetime.now(timezone.utc),
        processor="stripe",
        processor_customer_id="cus_phase_2_1_shared",
    )
    db.session.add(duplicate_processor)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    invalid_currency = BillingAccount(
        organization_id=second_org.id,
        currency="USD",
        account_anchor_at=datetime.now(timezone.utc),
    )
    db.session.add(invalid_currency)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    nonalphabetic_currency = BillingAccount(
        organization_id=second_org.id,
        currency="u5d",
        account_anchor_at=datetime.now(timezone.utc),
    )
    db.session.add(nonalphabetic_currency)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    incomplete_processor = BillingAccount(
        organization_id=second_org.id,
        currency="usd",
        account_anchor_at=datetime.now(timezone.utc),
        processor="stripe",
    )
    db.session.add(incomplete_processor)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_billing_role_constraints_and_open_role_uniqueness(db, test_user):
    organization = _organization(db, test_user)
    account = _account(db, organization)
    starts_at = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)

    db.session.add(BillingRoleGrant(
        billing_account_id=account.id,
        user_id=test_user.id,
        role="billing_owner",
        starts_at=starts_at,
        origin_type="authorized_command",
        origin_id="initial-owner",
    ))
    db.session.commit()

    duplicate_open_role = BillingRoleGrant(
        billing_account_id=account.id,
        user_id=test_user.id,
        role="billing_owner",
        starts_at=starts_at + timedelta(seconds=1),
        origin_type="authorized_command",
        origin_id="duplicate-owner",
    )
    db.session.add(duplicate_open_role)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    invalid_role = BillingRoleGrant(
        billing_account_id=account.id,
        user_id=test_user.id,
        role="organization_admin",
        starts_at=starts_at,
        origin_type="authorized_command",
        origin_id="invalid-role",
    )
    db.session.add(invalid_role)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    invalid_interval = BillingRoleGrant(
        billing_account_id=account.id,
        user_id=test_user.id,
        role="billing_viewer",
        starts_at=starts_at,
        ends_at=starts_at,
        origin_type="authorized_command",
        origin_id="invalid-interval",
    )
    db.session.add(invalid_interval)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_foundation_foreign_keys_and_indexes_match_the_approved_boundary(db):
    inspector = inspect(db.engine)

    account_fks = {fk["name"]: fk for fk in inspector.get_foreign_keys("billing_accounts")}
    assert account_fks["fk_billing_accounts_organization_id"]["referred_table"] == "organizations"
    assert account_fks["fk_billing_accounts_organization_id"]["options"]["ondelete"] == "RESTRICT"

    role_fks = {fk["name"]: fk for fk in inspector.get_foreign_keys("billing_role_grants")}
    assert role_fks["fk_billing_role_grants_billing_account_id"]["options"]["ondelete"] == "RESTRICT"
    assert role_fks["fk_billing_role_grants_user_id"]["options"]["ondelete"] == "RESTRICT"
    assert role_fks["fk_billing_role_grants_granted_by_user_id"]["options"]["ondelete"] == "SET NULL"

    account_indexes = {index["name"]: index for index in inspector.get_indexes("billing_accounts")}
    assert account_indexes["uq_billing_accounts_processor_customer"]["unique"]
    assert "ix_billing_accounts_status_created_at" in account_indexes

    role_indexes = {index["name"]: index for index in inspector.get_indexes("billing_role_grants")}
    assert role_indexes["uq_billing_role_grants_open_role"]["unique"]
    assert "ix_billing_role_grants_account_state" in role_indexes
    assert "ix_billing_role_grants_user_state" in role_indexes
