from datetime import datetime, timedelta

import pytest

from app.billing_config import (
    apply_plan_to_user,
    consume_credits,
    effective_plan_key,
    get_usage_meter_state,
    release_consumed_credits,
    reset_user_monthly_credits,
)
from app.founder_entitlements import (
    limited_time_300k_credit_balance,
    limited_time_300k_limits_active,
    grant_limited_time_300k_offer,
    has_limited_time_300k_entitlement,
    reverse_limited_time_300k_credits,
)
from app.models import AccountEntitlement, PersistentCreditGrant, Scorecard, StripeWebhookEvent, UsageEvent, UserSession
from app.routes.sessions import save_user_sessions
from app.scorecards import backfill_legacy_scorecards, collect_peer_scorecards, scorecard_limit_for, upsert_scorecard


def _card(card_id, name, score=70, rubric_key='value'):
    return {
        'id': card_id,
        'analysis_id': card_id,
        'project_name': name,
        'name': name,
        'jaspen_score': score,
        'dimensions': {
            rubric_key: {'label': rubric_key.title(), 'score': score, 'confidence': 'medium'},
        },
        'rubric': {'criteria': [{'key': rubric_key, 'label': rubric_key.title(), 'weight': 1.0}]},
        'createdAt': datetime.utcnow().isoformat(),
    }


def _session_payload(user_id, thread_id, cards):
    first = dict(cards[0])
    first['_baseline_scorecard'] = dict(cards[0], isBaseline=True)
    first['scorecard_snapshots'] = [dict(card, isBaseline=False) for card in cards[1:]]
    first['selected_scorecard_id'] = cards[0]['id']
    return {
        'session_id': thread_id,
        'user_id': str(user_id),
        'name': 'Portfolio',
        'status': 'completed',
        'result': first,
        'analysis_history': [{
            'id': cards[0]['id'],
            'analysis_id': cards[0]['id'],
            'result': first,
        }],
    }


def test_limited_time_300k_grant_is_idempotent_and_independent_of_plan(app, db, test_user):
    apply_plan_to_user(test_user, 'free', app.config, reset_credits=True)
    _, first_grant, created = grant_limited_time_300k_offer(
        test_user,
        300_000_000,
        payment_reference='pi_limited_time_300k_1',
    )
    _, second_grant, created_again = grant_limited_time_300k_offer(
        test_user,
        300_000_000,
        payment_reference='pi_limited_time_300k_1',
    )
    db.session.commit()

    assert created is True
    assert created_again is False
    assert first_grant.id == second_grant.id
    assert AccountEntitlement.query.count() == 1
    assert PersistentCreditGrant.query.count() == 1
    assert has_limited_time_300k_entitlement(test_user)
    assert limited_time_300k_credit_balance(test_user) == 300_000_000
    assert test_user.subscription_plan == 'free'


def test_limited_time_300k_is_standalone_billing_with_individual_output_access(
    client, app, db, test_user, auth_headers
):
    apply_plan_to_user(test_user, 'free', app.config, reset_credits=True)
    grant_limited_time_300k_offer(test_user, 300_000_000, payment_reference='pi_limited_time_300k_access')
    db.session.commit()

    response = client.get('/api/v1/billing/status', headers=auth_headers)
    payload = response.get_json()

    assert response.status_code == 200
    assert test_user.subscription_plan == 'free'
    assert payload['plan_key'] == 'free'
    assert payload['effective_plan_key'] == 'essential'
    assert payload['has_300k_limited_time'] is True
    assert payload['access_restricted'] is False
    assert effective_plan_key(test_user, app.config) == 'essential'


def test_limited_time_300k_refund_revokes_standalone_output_access(app, db, test_user):
    apply_plan_to_user(test_user, 'free', app.config, reset_credits=True)
    grant_limited_time_300k_offer(test_user, 300_000_000, payment_reference='pi_limited_time_300k_refund')
    db.session.commit()

    reversed_amount = reverse_limited_time_300k_credits(
        test_user,
        reason='refund',
        external_reference='re_test',
    )
    db.session.commit()

    assert reversed_amount == 300_000_000
    assert limited_time_300k_credit_balance(test_user) == 0
    assert has_limited_time_300k_entitlement(test_user) is False
    assert effective_plan_key(test_user, app.config) == 'free'


def test_duplicate_limited_time_300k_checkout_webhook_does_not_duplicate_grant(
    client, app, db, test_user, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_founder_test'
    test_user.stripe_customer_id = 'cus_limited_time_300k'
    db.session.commit()
    session = {
        'id': 'cs_limited_time_300k',
        'payment_intent': 'pi_limited_time_300k',
        'customer': 'cus_limited_time_300k',
        'metadata': {
            'user_id': str(test_user.id),
            'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
            'tokens': '300000000',
            'campaign_id': 'limited_time_300k_pmo',
        },
    }
    event = {
        'id': 'evt_limited_time_300k_checkout',
        'type': 'checkout.session.completed',
        'data': {'object': session},
    }
    monkeypatch.setattr(billing.stripe.Webhook, 'construct_event', lambda *_args: event)

    first = client.post('/api/v1/billing/webhook', data=b'{}', headers={'Stripe-Signature': 'test'})
    second = client.post('/api/v1/billing/webhook', data=b'{}', headers={'Stripe-Signature': 'test'})

    assert first.status_code == 200
    assert second.status_code == 200
    assert PersistentCreditGrant.query.filter_by(user_id=str(test_user.id)).count() == 1
    assert AccountEntitlement.query.filter_by(user_id=str(test_user.id)).count() == 1
    assert StripeWebhookEvent.query.filter_by(stripe_event_id='evt_limited_time_300k_checkout', processed=True).count() == 1
    assert test_user.subscription_plan == 'free'


def test_limited_time_300k_payment_intent_uses_one_time_price_without_subscription(
    client, app, auth_headers, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_LIMITED_TIME_300K_PRICE_ID'] = 'price_limited_time_300k_999'
    app.config['LIMITED_TIME_300K_CREDIT_TOKENS'] = 300_000_000
    app.config['STRIPE_PUBLISHABLE_KEY'] = 'pk_test_limited_time_300k'
    captured = {}

    monkeypatch.setattr(
        billing.stripe.Price, 'retrieve',
        lambda price_id: {'id': price_id, 'unit_amount': 99900, 'currency': 'usd'},
    )

    def fake_create(**kwargs):
        captured.update(kwargs)
        return type('Intent', (), {'client_secret': 'pi_limited_time_300k_secret_abc'})()

    monkeypatch.setattr(billing, '_ensure_customer_for_user', lambda _user: 'cus_limited_time_300k')
    monkeypatch.setattr(billing.stripe.PaymentIntent, 'create', fake_create)
    response = client.post(
        '/api/v1/billing/create-300k-limited-time-payment-intent',
        headers=auth_headers,
        json={
            'campaign_id': 'limited_time_300k_pmo',
            'return_path': '/limited-time/project-prioritization',
            'terms_accepted': True,
            'final_sale_acknowledged': True,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['client_secret'] == 'pi_limited_time_300k_secret_abc'
    assert body['publishable_key'] == 'pk_test_limited_time_300k'
    assert captured['amount'] == 99900
    assert captured['currency'] == 'usd'
    assert captured['metadata']['checkout_type'] == billing.LIMITED_TIME_300K_CHECKOUT_TYPE
    assert captured['metadata']['tokens'] == '300000000'
    assert captured['metadata']['terms_accepted'] == 'true'
    assert captured['metadata']['final_sale_acknowledged'] == 'true'
    assert captured['metadata']['acknowledged_at'].endswith('Z')
    assert 'subscription_data' not in captured


def test_limited_time_300k_payment_intent_is_created_at_full_price(
    client, app, auth_headers, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_LIMITED_TIME_300K_PRICE_ID'] = 'price_limited_time_300k_999'
    app.config['LIMITED_TIME_300K_CREDIT_TOKENS'] = 300_000_000
    app.config['STRIPE_PUBLISHABLE_KEY'] = 'pk_test_limited_time_300k'
    captured = {}

    monkeypatch.setattr(
        billing.stripe.Price, 'retrieve',
        lambda price_id: {'id': price_id, 'unit_amount': 99900, 'currency': 'usd'},
    )

    def fake_create(**kwargs):
        captured.update(kwargs)
        return type('Intent', (), {'client_secret': 'pi_limited_time_300k_secret_abc'})()

    monkeypatch.setattr(billing, '_ensure_customer_for_user', lambda _user: 'cus_limited_time_300k')
    monkeypatch.setattr(billing.stripe.PaymentIntent, 'create', fake_create)
    response = client.post(
        '/api/v1/billing/create-300k-limited-time-payment-intent',
        headers=auth_headers,
        json={
            'campaign_id': 'limited_time_300k_pmo',
            'return_path': '/limited-time/project-prioritization',
            'terms_accepted': True,
            'final_sale_acknowledged': True,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['price_label'] == '$999'
    assert captured['amount'] == 99900
    assert 'promotion_code' not in captured['metadata']


def _limited_time_intent(test_user, billing, **overrides):
    metadata = {
        'user_id': str(test_user.id),
        'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
        'tokens': '300000000',
        'campaign_id': 'limited_time_300k_pmo',
    }
    metadata.update(overrides.pop('metadata', {}))
    intent = {
        'id': 'pi_limited_time_300k_abc',
        'status': 'requires_payment_method',
        'customer': 'cus_limited_time_300k',
        'metadata': metadata,
    }
    intent.update(overrides)
    return intent


def _stub_limited_time_coupon_stripe(monkeypatch, billing, test_user, invoice, open_invoices=(), **overrides):
    """Wire up the Stripe calls the coupon endpoint makes.

    These fakes deliberately enforce the shape of the Stripe API version this
    app actually talks to, because permissive fakes hid two production
    failures: an invoice item created with a top-level `price` (removed - the
    price now goes under `pricing`), and a confirmation_secret read off an
    invoice that was finalized without expanding it.

    The discount must ride on a real invoice so Stripe records the redemption,
    so PromotionCode.list() deliberately returns an EMPTY nested coupon here -
    matching production. Any implementation that reads percent_off off it
    instead of using the invoice Stripe priced will fail these tests.
    """
    calls = {}
    monkeypatch.setattr(
        billing.stripe.PaymentIntent, 'retrieve',
        lambda payment_intent_id: _limited_time_intent(test_user, billing, **overrides),
    )
    monkeypatch.setattr(
        billing.stripe.PromotionCode, 'list',
        lambda code, active, limit: {'data': [{'id': 'promo_300ktest', 'coupon': {}}]},
    )
    monkeypatch.setattr(billing, '_ensure_customer_for_user', lambda _user: 'cus_limited_time_300k')

    def fake_invoice_item_create(**kwargs):
        if 'price' in kwargs:
            raise billing.stripe.error.InvalidRequestError(
                'Received unknown parameter: price', 'price',
            )
        if not kwargs.get('pricing', {}).get('price'):
            raise billing.stripe.error.InvalidRequestError('Missing required param: pricing.', 'pricing')
        if not kwargs.get('invoice'):
            # Stripe leaves an unattached item pending on the customer, and a
            # standalone invoice does not pick it up - so the invoice would
            # finalize empty and look fully discounted.
            raise AssertionError('invoice item must be attached to the invoice it belongs to')
        calls['invoice_item'] = kwargs
        return dict(kwargs, id='ii_limited_time_300k')

    monkeypatch.setattr(billing.stripe.InvoiceItem, 'create', fake_invoice_item_create)

    def fake_invoice_create(**kwargs):
        calls['invoice'] = kwargs
        return {'id': 'in_limited_time_300k', 'status': 'draft'}

    def fake_finalize(invoice_id, **kwargs):
        calls['finalize'] = kwargs
        finalized = dict(invoice, id=invoice_id)
        if 'confirmation_secret' not in (kwargs.get('expand') or []):
            finalized.pop('confirmation_secret', None)
        return finalized

    monkeypatch.setattr(billing.stripe.Invoice, 'create', fake_invoice_create)
    monkeypatch.setattr(billing.stripe.Invoice, 'finalize_invoice', fake_finalize)
    monkeypatch.setattr(
        billing.stripe.Invoice, 'list',
        lambda **kwargs: {'data': list(open_invoices)},
    )
    monkeypatch.setattr(
        billing.stripe.Invoice, 'void_invoice',
        lambda invoice_id: calls.setdefault('voided', []).append(invoice_id),
    )
    monkeypatch.setattr(
        billing.stripe.Invoice, 'delete',
        lambda invoice_id: calls.setdefault('deleted', []).append(invoice_id),
    )
    monkeypatch.setattr(
        billing.stripe.PaymentIntent, 'cancel',
        lambda payment_intent_id: calls.setdefault('canceled', payment_intent_id),
    )
    return calls


def test_apply_300k_limited_time_coupon_settles_a_full_discount_through_stripe(
    client, app, auth_headers, test_user, monkeypatch
):
    """A fully covered offer must be paid via a Stripe invoice, not granted locally.

    Granting credits without an invoice left Stripe showing zero redemptions
    and a canceled payment, so our records and Stripe's disagreed.
    """
    from app.routes import billing

    app.config['STRIPE_LIMITED_TIME_300K_PRICE_ID'] = 'price_limited_time_300k_999'
    app.config['LIMITED_TIME_300K_CREDIT_TOKENS'] = 300_000_000
    calls = _stub_limited_time_coupon_stripe(
        monkeypatch, billing, test_user,
        invoice={
            'id': 'in_limited_time_300k',
            'status': 'paid',
            'amount_due': 0,
            'subtotal': 99900,
            'total': 0,
            'customer': 'cus_limited_time_300k',
            'metadata': {
                'user_id': str(test_user.id),
                'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
                'tokens': '300000000',
                'campaign_id': 'limited_time_300k_pmo',
                'promotion_code': '300KTest',
            },
        },
    )

    response = client.post(
        '/api/v1/billing/apply-300k-limited-time-coupon',
        headers=auth_headers,
        json={'payment_intent_id': 'pi_limited_time_300k_abc', 'coupon_code': '300KTest'},
    )

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body['free'] is True
    assert body['price_label'] == '$0.00'
    assert body['granted'] is True
    assert body['invoice_id'] == 'in_limited_time_300k'

    # Stripe applied the discount and therefore records the redemption.
    assert calls['invoice']['discounts'] == [{'promotion_code': 'promo_300ktest'}]
    assert calls['invoice_item']['pricing'] == {'price': 'price_limited_time_300k_999'}
    assert calls['invoice_item']['invoice'] == 'in_limited_time_300k'
    assert calls['invoice']['metadata']['checkout_type'] == billing.LIMITED_TIME_300K_CHECKOUT_TYPE

    entitlement = AccountEntitlement.query.filter_by(
        user_id=test_user.id, entitlement_key='300k_limited_time'
    ).first()
    assert entitlement is not None
    grant = PersistentCreditGrant.query.filter_by(user_id=str(test_user.id)).first()
    assert grant is not None


def test_apply_300k_limited_time_coupon_will_not_grant_an_unpaid_invoice(
    client, app, auth_headers, test_user, monkeypatch
):
    """Stripe is the source of truth - an invoice it has not marked paid grants nothing."""
    from app.routes import billing

    app.config['STRIPE_LIMITED_TIME_300K_PRICE_ID'] = 'price_limited_time_300k_999'
    _stub_limited_time_coupon_stripe(
        monkeypatch, billing, test_user,
        invoice={
            'id': 'in_limited_time_300k',
            'status': 'open',
            'amount_due': 0,
            'subtotal': 99900,
            'total': 0,
            'customer': 'cus_limited_time_300k',
            'metadata': {
                'user_id': str(test_user.id),
                'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
                'tokens': '300000000',
            },
        },
    )

    response = client.post(
        '/api/v1/billing/apply-300k-limited-time-coupon',
        headers=auth_headers,
        json={'payment_intent_id': 'pi_limited_time_300k_abc', 'coupon_code': '300KTest'},
    )

    assert response.status_code == 409
    assert AccountEntitlement.query.filter_by(user_id=test_user.id).count() == 0


def test_apply_300k_limited_time_coupon_sends_a_partial_discount_to_the_invoice_payment(
    client, app, auth_headers, test_user, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_LIMITED_TIME_300K_PRICE_ID'] = 'price_limited_time_300k_999'
    _stub_limited_time_coupon_stripe(
        monkeypatch, billing, test_user,
        invoice={
            'id': 'in_limited_time_300k',
            'status': 'open',
            'amount_due': 79920,
            'subtotal': 99900,
            'total': 79920,
            'customer': 'cus_limited_time_300k',
            'confirmation_secret': {'client_secret': 'pi_invoice_secret_xyz'},
            'metadata': {
                'user_id': str(test_user.id),
                'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
                'tokens': '300000000',
            },
        },
    )

    response = client.post(
        '/api/v1/billing/apply-300k-limited-time-coupon',
        headers=auth_headers,
        json={'payment_intent_id': 'pi_limited_time_300k_abc', 'coupon_code': 'LAUNCH20'},
    )

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body['price_label'] == '$799.20'
    assert body['client_secret'] == 'pi_invoice_secret_xyz'
    assert body.get('free') is not True
    # Nothing is granted until Stripe reports the invoice paid.
    assert AccountEntitlement.query.filter_by(user_id=test_user.id).count() == 0


def test_apply_300k_limited_time_coupon_rejects_a_code_that_does_not_touch_this_offer(
    client, app, auth_headers, test_user, monkeypatch
):
    """A coupon restricted to the subscription prices must be reported, not accepted.

    Stripe happily attaches such a code and discounts nothing, which would
    otherwise show the buyer a "discount applied" message at full price.
    """
    from app.routes import billing

    app.config['STRIPE_LIMITED_TIME_300K_PRICE_ID'] = 'price_limited_time_300k_999'
    calls = _stub_limited_time_coupon_stripe(
        monkeypatch, billing, test_user,
        invoice={
            'id': 'in_limited_time_300k',
            'status': 'open',
            'amount_due': 99900,
            'subtotal': 99900,
            'total': 99900,
            'customer': 'cus_limited_time_300k',
            'metadata': {
                'user_id': str(test_user.id),
                'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
                'tokens': '300000000',
            },
        },
    )

    response = client.post(
        '/api/v1/billing/apply-300k-limited-time-coupon',
        headers=auth_headers,
        json={'payment_intent_id': 'pi_limited_time_300k_abc', 'coupon_code': 'SUBSONLY'},
    )

    assert response.status_code == 400
    assert 'does not reduce the price' in response.get_json()['msg']
    # The buyer's original full-price payment must still be usable.
    assert 'canceled' not in calls
    assert calls['voided'] == ['in_limited_time_300k']


def test_apply_300k_limited_time_coupon_never_grants_on_an_empty_invoice(
    client, app, auth_headers, test_user, monkeypatch
):
    """A $0 invoice with no offer line is a bug, not a fully covered purchase."""
    from app.routes import billing

    app.config['STRIPE_LIMITED_TIME_300K_PRICE_ID'] = 'price_limited_time_300k_999'
    _stub_limited_time_coupon_stripe(
        monkeypatch, billing, test_user,
        invoice={
            'id': 'in_limited_time_300k',
            'status': 'paid',
            'amount_due': 0,
            'subtotal': 0,
            'total': 0,
            'customer': 'cus_limited_time_300k',
            'metadata': {
                'user_id': str(test_user.id),
                'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
                'tokens': '300000000',
            },
        },
    )

    response = client.post(
        '/api/v1/billing/apply-300k-limited-time-coupon',
        headers=auth_headers,
        json={'payment_intent_id': 'pi_limited_time_300k_abc', 'coupon_code': '300KTest'},
    )

    assert response.status_code == 400
    assert AccountEntitlement.query.filter_by(user_id=test_user.id).count() == 0


def test_apply_300k_limited_time_coupon_allows_a_second_code_after_the_first(
    client, app, auth_headers, test_user, monkeypatch
):
    """Trying another code must work, and must not leave the first invoice payable.

    The first code moves the charge onto an invoice and cancels the original
    intent, so the second attempt arrives with that intent already canceled.
    """
    from app.routes import billing

    app.config['STRIPE_LIMITED_TIME_300K_PRICE_ID'] = 'price_limited_time_300k_999'
    calls = _stub_limited_time_coupon_stripe(
        monkeypatch, billing, test_user,
        status='canceled',
        open_invoices=[{
            'id': 'in_limited_time_300k_first_try',
            'status': 'open',
            'metadata': {'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE},
        }, {
            'id': 'in_someone_elses_subscription',
            'status': 'open',
            'metadata': {},
        }],
        invoice={
            'id': 'in_limited_time_300k',
            'status': 'paid',
            'amount_due': 0,
            'subtotal': 99900,
            'total': 0,
            'customer': 'cus_limited_time_300k',
            'metadata': {
                'user_id': str(test_user.id),
                'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
                'tokens': '300000000',
            },
        },
    )

    response = client.post(
        '/api/v1/billing/apply-300k-limited-time-coupon',
        headers=auth_headers,
        json={'payment_intent_id': 'pi_limited_time_300k_abc', 'coupon_code': '300KTest'},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()['free'] is True
    # The abandoned first attempt is voided; unrelated invoices are untouched.
    assert calls['voided'] == ['in_limited_time_300k_first_try']


def test_confirm_300k_limited_time_payment_fulfills_a_discounted_invoice(
    client, app, auth_headers, test_user, monkeypatch
):
    """A partially discounted purchase is paid through the invoice's own intent.

    That intent carries none of the offer metadata, so the frontend names the
    invoice and fulfilment reads it from there.
    """
    from app.routes import billing

    app.config['LIMITED_TIME_300K_CREDIT_TOKENS'] = 300_000_000
    monkeypatch.setattr(
        billing.stripe.Invoice, 'retrieve',
        lambda invoice_id, **kwargs: {
            'id': invoice_id,
            'status': 'paid',
            'amount_due': 0,
            'customer': 'cus_limited_time_300k',
            'metadata': {
                'user_id': str(test_user.id),
                'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
                'tokens': '300000000',
                'promotion_code': 'LAUNCH20',
            },
        },
    )

    response = client.post(
        '/api/v1/billing/confirm-300k-limited-time-payment',
        headers=auth_headers,
        json={'payment_intent_id': 'pi_from_the_invoice', 'invoice_id': 'in_limited_time_300k_partial'},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()['granted'] is True
    assert AccountEntitlement.query.filter_by(
        user_id=test_user.id, entitlement_key='300k_limited_time'
    ).first() is not None


def test_apply_300k_limited_time_coupon_rejects_unknown_code(
    client, app, auth_headers, test_user, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_LIMITED_TIME_300K_PRICE_ID'] = 'price_limited_time_300k_999'
    monkeypatch.setattr(
        billing.stripe.PaymentIntent, 'retrieve',
        lambda payment_intent_id: _limited_time_intent(test_user, billing),
    )
    monkeypatch.setattr(billing, '_ensure_customer_for_user', lambda _user: 'cus_limited_time_300k')
    monkeypatch.setattr(billing.stripe.PromotionCode, 'list', lambda code, active, limit: {'data': []})

    response = client.post(
        '/api/v1/billing/apply-300k-limited-time-coupon',
        headers=auth_headers,
        json={'payment_intent_id': 'pi_limited_time_300k_abc', 'coupon_code': 'NOTREAL'},
    )

    assert response.status_code == 400
    assert 'not found' in response.get_json()['msg'].lower()


def test_limited_time_300k_invoice_webhook_is_idempotent(
    client, app, db, test_user, monkeypatch
):
    """Stripe may deliver invoice.paid more than once; credits are granted once."""
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_founder_test'
    invoice = {
        'id': 'in_limited_time_300k_hook',
        'status': 'paid',
        'amount_due': 0,
        'customer': 'cus_limited_time_300k',
        'metadata': {
            'user_id': str(test_user.id),
            'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
            'tokens': '300000000',
            'campaign_id': 'limited_time_300k_pmo',
        },
    }
    event = {
        'id': 'evt_limited_time_300k_invoice',
        'type': 'invoice.paid',
        'data': {'object': invoice},
    }
    monkeypatch.setattr(billing.stripe.Webhook, 'construct_event', lambda *_args: event)

    first = client.post('/api/v1/billing/webhook', data=b'{}', headers={'Stripe-Signature': 'test'})
    second = client.post('/api/v1/billing/webhook', data=b'{}', headers={'Stripe-Signature': 'test'})

    assert first.status_code == 200
    assert second.status_code == 200
    assert PersistentCreditGrant.query.filter_by(user_id=str(test_user.id)).count() == 1
    assert AccountEntitlement.query.filter_by(user_id=str(test_user.id)).count() == 1


def test_apply_300k_limited_time_coupon_rejects_other_users_intent(
    client, app, auth_headers, monkeypatch
):
    from app.routes import billing

    monkeypatch.setattr(
        billing.stripe.PaymentIntent, 'retrieve',
        lambda payment_intent_id: {
            'id': payment_intent_id,
            'status': 'requires_payment_method',
            'metadata': {
                'user_id': 'someone-else',
                'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
            },
        },
    )

    response = client.post(
        '/api/v1/billing/apply-300k-limited-time-coupon',
        headers=auth_headers,
        json={'payment_intent_id': 'pi_limited_time_300k_abc', 'coupon_code': ''},
    )

    assert response.status_code == 403


def test_limited_time_300k_payment_intent_requires_both_purchase_acknowledgements(client, auth_headers):
    response = client.post(
        '/api/v1/billing/create-300k-limited-time-payment-intent',
        headers=auth_headers,
        json={'terms_accepted': True, 'final_sale_acknowledged': False},
    )

    assert response.status_code == 400
    assert response.get_json()['msg'] == 'Accept both purchase acknowledgements before continuing.'


def test_founder_credits_survive_renewal_downgrade_and_reset(app, db, test_user):
    apply_plan_to_user(test_user, 'essential', app.config, reset_credits=True)
    grant_limited_time_300k_offer(test_user, 300_000_000, payment_reference='pi_limited_time_300k_reset')
    db.session.commit()

    test_user.credits_reset_at = datetime.utcnow() - timedelta(days=35)
    reset_user_monthly_credits(test_user, app.config, force=True)
    apply_plan_to_user(test_user, 'free', app.config, reset_credits=True)
    state = get_usage_meter_state(test_user, app.config)
    db.session.commit()

    assert has_limited_time_300k_entitlement(test_user)
    assert limited_time_300k_credit_balance(test_user) == 300_000_000
    assert state['remaining'] == 300_300_000
    assert state['founder_credits'] == 300_000_000


def test_monthly_credits_are_consumed_before_founder_credits(app, db, test_user):
    apply_plan_to_user(test_user, 'essential', app.config, reset_credits=True)
    grant_limited_time_300k_offer(test_user, 1_000, payment_reference='pi_limited_time_300k_order')
    db.session.commit()

    ok, remaining = consume_credits(test_user, 7_000_100)
    db.session.commit()

    assert ok is True
    assert remaining == 900
    assert limited_time_300k_credit_balance(test_user) == 900


def test_reservation_release_restores_only_the_current_debit_sources(app, db, test_user):
    apply_plan_to_user(test_user, 'essential', app.config, reset_credits=True)
    grant_limited_time_300k_offer(test_user, 1_000, payment_reference='pi_limited_time_300k_release')
    db.session.commit()

    consume_credits(test_user, 7_000_100)
    assert limited_time_300k_credit_balance(test_user) == 900
    release_consumed_credits(test_user, 50)
    state = get_usage_meter_state(test_user, app.config)
    db.session.commit()

    assert limited_time_300k_credit_balance(test_user) == 950
    assert state['monthly_remaining'] == 0
    assert state['remaining'] == 950


def test_founder_limits_end_automatically_at_zero_balance(app, db, test_user):
    apply_plan_to_user(test_user, 'essential', app.config, reset_credits=True)
    grant_limited_time_300k_offer(test_user, 10, payment_reference='pi_limited_time_300k_limits')
    db.session.commit()
    assert limited_time_300k_limits_active(test_user) is True

    consume_credits(test_user, 7_000_010)
    db.session.commit()
    assert limited_time_300k_credit_balance(test_user) == 0
    assert limited_time_300k_limits_active(test_user) is False
    assert has_limited_time_300k_entitlement(test_user) is True


def test_founder_balance_remains_usable_after_upgrade_to_shared_team_pool(app, db, test_user):
    from app.orgs import ensure_default_organization_for_user

    ensure_default_organization_for_user(test_user)
    apply_plan_to_user(test_user, 'team', app.config, reset_credits=True)
    grant_limited_time_300k_offer(test_user, 1_000, payment_reference='pi_limited_time_300k_team')
    db.session.commit()

    ok, remaining = consume_credits(test_user, 29_000_100)
    db.session.commit()

    assert ok is True
    assert remaining == 900
    assert limited_time_300k_credit_balance(test_user) == 900
    reset_user_monthly_credits(test_user, app.config, force=True)
    assert limited_time_300k_credit_balance(test_user) == 900
    assert get_usage_meter_state(test_user, app.config)['remaining'] == 29_000_900


def test_peer_collection_merges_native_and_legacy_without_baseline(db, test_user):
    thread_id = 'peer-thread'
    legacy = _card('legacy-1', 'Legacy')
    native = _card('native-1', 'Native', rubric_key='risk')
    upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=native)
    db.session.commit()

    peers = collect_peer_scorecards(
        test_user.id,
        thread_id,
        legacy_session=_session_payload(test_user.id, thread_id, [legacy]),
    )

    assert {item['id'] for item in peers} == {'legacy-1', 'native-1'}
    assert all(item['isBaseline'] is False for item in peers)
    assert all('delta_vs_baseline' not in item for item in peers)


def test_backfill_preserves_long_legacy_scorecard_ids_idempotently(db, test_user):
    thread_id = 'legacy-edited-thread'
    legacy_id = '7bd32f48-e851-4ed9-87f2-682687e7d6cc__edited'
    legacy = _card(legacy_id, 'Edited legacy scorecard')
    session = _session_payload(test_user.id, thread_id, [legacy])

    created = backfill_legacy_scorecards(
        user_id=test_user.id,
        thread_id=thread_id,
        legacy_session=session,
    )
    db.session.commit()
    created_again = backfill_legacy_scorecards(
        user_id=test_user.id,
        thread_id=thread_id,
        legacy_session=session,
    )

    assert Scorecard.__table__.c.id.type.length == 255
    assert UsageEvent.__table__.c.scorecard_id.type.length == 255
    assert created == 1
    assert created_again == 0
    assert Scorecard.query.get(legacy_id).data['id'] == legacy_id


def test_deleting_first_middle_and_last_scorecard_keeps_session(
    client, db, test_user, auth_headers
):
    thread_id = 'delete-peers'
    cards = [_card('first', 'First'), _card('middle', 'Middle'), _card('last', 'Last')]
    assert save_user_sessions(test_user.id, {thread_id: _session_payload(test_user.id, thread_id, cards)})
    for card in cards:
        upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    for card_id in ('first', 'middle', 'last'):
        response = client.delete(
            f'/api/v1/strategy/scores/{thread_id}/{card_id}',
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert UserSession.query.filter_by(user_id=str(test_user.id), session_id=thread_id).first() is not None

    assert Scorecard.query.filter_by(user_id=str(test_user.id), thread_id=thread_id, archived_at=None).count() == 0


def test_explicit_session_delete_is_separate_and_archives_peers(
    client, db, test_user, auth_headers
):
    thread_id = 'delete-session'
    card = _card('session-card', 'Session Card')
    assert save_user_sessions(test_user.id, {thread_id: _session_payload(test_user.id, thread_id, [card])})
    upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    response = client.delete(f'/api/v1/sessions/{thread_id}', headers=auth_headers)
    assert response.status_code == 200
    row = UserSession.query.filter_by(user_id=str(test_user.id), session_id=thread_id).first()
    scorecard = Scorecard.query.get('session-card')
    assert row.archived_at is not None
    assert scorecard.archived_at is not None


def test_bundle_and_exports_return_all_peer_scorecards_without_baseline_fields(
    client, db, test_user, auth_headers
):
    from app.routes.export import _scorecard_variants_for_export

    thread_id = 'complete-peers'
    cards = [_card(f'card-{index}', f'Project {index}', score=60 + index) for index in range(12)]
    assert save_user_sessions(test_user.id, {thread_id: _session_payload(test_user.id, thread_id, cards[:1])})
    for card in cards:
        upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    response = client.get(f'/api/v1/strategy/threads/{thread_id}/bundle', headers=auth_headers)
    assert response.status_code == 200
    bundle = response.get_json()
    assert len(bundle['peer_scorecards']) == 12
    assert len(bundle['scorecard_snapshots']) == 12

    variants = _scorecard_variants_for_export(
        _session_payload(test_user.id, thread_id, cards[:1]),
        thread_id,
        user_id=test_user.id,
    )
    assert len(variants) == 12
    assert all(item['is_baseline'] is False for item in variants)
    assert all('delta_vs_baseline' not in item for item in variants)


def test_export_collection_does_not_truncate_portfolios_above_twelve(db, test_user):
    from app.routes.export import _scorecard_variants_for_export

    thread_id = 'fourteen-export-peers'
    cards = [_card(f'export-{index}', f'Export Project {index}') for index in range(14)]
    session = _session_payload(test_user.id, thread_id, cards[:1])
    assert save_user_sessions(test_user.id, {thread_id: session})
    for card in cards:
        upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    variants = _scorecard_variants_for_export(session, thread_id, user_id=test_user.id)

    assert len(variants) == 14
    assert {variant['id'] for variant in variants} == {card['id'] for card in cards}


def test_portfolio_limits_gate_creation_but_not_retention(db, test_user):
    assert scorecard_limit_for(test_user, 'free') == 30
    assert scorecard_limit_for(test_user, 'business') == 30
    grant_limited_time_300k_offer(test_user, 1, payment_reference='pi_limited_time_300k_capacity')
    db.session.commit()
    assert scorecard_limit_for(test_user, 'free') == 30


def _empty_portfolio_session(user_id, thread_id):
    return {
        'session_id': thread_id,
        'user_id': str(user_id),
        'name': 'Batch portfolio',
        'status': 'in_progress',
        'result': {},
        'scorecard_queue': [],
        'chat_history': [],
    }


def _mock_batch_accounting(monkeypatch):
    from app.routes import ai_agent, strategy

    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())
    monkeypatch.setattr(
        ai_agent,
        '_reserve_preflight_credits',
        lambda *args, **kwargs: {'ok': True, 'reserved': 100, 'remaining': 200},
    )
    monkeypatch.setattr(ai_agent, '_charge_for_usage', lambda *args, **kwargs: 10)
    monkeypatch.setattr(
        ai_agent,
        '_settle_reserved_credits',
        lambda *args, **kwargs: {'ok': True, 'charged': 10, 'remaining': 290, 'payload': None},
    )


@pytest.mark.parametrize('requested', [29, 30, 31])
def test_batch_generation_respects_free_portfolio_boundary_without_silent_discard(
    requested, client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import strategy

    thread_id = f'batch-{requested}'
    assert save_user_sessions(test_user.id, {thread_id: _empty_portfolio_session(test_user.id, thread_id)})
    ideas = [{'name': f'Project {index}', 'description': 'Evaluate it'} for index in range(requested)]
    generated_sizes = []

    def fake_generate(_client, generated_ideas, **_kwargs):
        generated_sizes.append(len(generated_ideas))
        return ([_card(f'tmp-{i}', item['name']) for i, item in enumerate(generated_ideas)], {}, {
            'provider': 'anthropic', 'model': 'claude-test', 'input_tokens': 50,
            'output_tokens': 50, 'total_tokens': 100,
        })

    _mock_batch_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_generate_batch_scorecards', fake_generate)

    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/score-batch',
        headers=auth_headers,
        json={'ideas': ideas},
    )
    payload = response.get_json()
    expected = min(requested, 30)

    assert response.status_code == 200
    assert generated_sizes == [expected]
    assert payload['requested_project_count'] == requested
    assert payload['generated_project_count'] == expected
    assert payload['persisted_project_count'] == expected
    assert len(payload['not_persisted_project_names']) == requested - expected
    assert Scorecard.query.filter_by(user_id=str(test_user.id), thread_id=thread_id).count() == expected
    usage_events = UsageEvent.query.filter_by(thread_id=thread_id, operation_type='score_batch').all()
    assert len(usage_events) == expected
    assert sum(event.reserved_credits for event in usage_events) == 100
    assert sum(event.settled_credits for event in usage_events) == 10
    assert len({event.evaluation_id for event in usage_events}) == expected
    assert all(event.raw_provider_cost_usd is not None for event in usage_events)
    if requested > 30:
        assert payload['reason'] == 'comparison_session_limit_reached'
        assert 'existing scorecards remain saved and accessible' in payload['message'].lower()


def test_batch_reports_partial_model_failure(
    client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import strategy

    thread_id = 'batch-model-partial'
    assert save_user_sessions(test_user.id, {thread_id: _empty_portfolio_session(test_user.id, thread_id)})
    ideas = [{'name': name} for name in ('One', 'Two', 'Three')]
    _mock_batch_accounting(monkeypatch)
    monkeypatch.setattr(
        strategy,
        '_generate_batch_scorecards',
        lambda *_args, **_kwargs: ([_card('one', 'One'), None, _card('three', 'Three')], {}, {}),
    )

    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/score-batch',
        headers=auth_headers,
        json={'ideas': ideas},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['generated_project_count'] == 2
    assert payload['persisted_project_count'] == 2
    assert payload['not_persisted_project_names'] == ['Two']
    assert payload['reason'] == 'partial_model_failure'


def test_batch_reports_partial_persistence_failure(
    client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import strategy

    thread_id = 'batch-persist-partial'
    assert save_user_sessions(test_user.id, {thread_id: _empty_portfolio_session(test_user.id, thread_id)})
    ideas = [{'name': name} for name in ('Keep', 'Fail')]
    _mock_batch_accounting(monkeypatch)
    monkeypatch.setattr(
        strategy,
        '_generate_batch_scorecards',
        lambda *_args, **_kwargs: ([_card('keep', 'Keep'), _card('fail', 'Fail')], {}, {}),
    )
    real_upsert = strategy.upsert_scorecard

    def selective_upsert(**kwargs):
        if kwargs['payload'].get('project_name') == 'Fail':
            raise RuntimeError('simulated persistence failure')
        return real_upsert(**kwargs)

    monkeypatch.setattr(strategy, 'upsert_scorecard', selective_upsert)
    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/score-batch',
        headers=auth_headers,
        json={'ideas': ideas},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['generated_project_count'] == 2
    assert payload['persisted_project_count'] == 1
    assert payload['not_persisted_project_names'] == ['Fail']
    assert payload['reason'] == 'partial_persistence_failure'


def test_execution_plan_generation_is_metered(
    client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import strategy

    thread_id = 'metered-execution-plan'
    scorecard = _card('wbs-card', 'WBS Project')
    scorecard['executive_summary'] = 'A grounded project ready for planning.'
    assert save_user_sessions(test_user.id, {thread_id: _session_payload(test_user.id, thread_id, [scorecard])})
    upsert_scorecard(
        user_id=test_user.id,
        thread_id=thread_id,
        payload=scorecard,
        evaluation_id='11111111-1111-4111-8111-111111111111',
    )
    db.session.commit()
    _mock_batch_accounting(monkeypatch)
    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())
    monkeypatch.setattr(
        strategy,
        '_generate_ai_wbs_suggestion',
        lambda *_args, **_kwargs: ({
            'name': 'Execution plan',
            'summary': 'Metered plan',
            'phases': [{'name': 'Delivery', 'tasks': [{
                'id': 'task-1', 'title': 'Deliver WBS Project', 'estimated_days': 3,
                'priority': 'high', 'dependencies': [],
            }]}],
        }, {
            'provider': 'anthropic', 'model': 'claude-test',
            'input_tokens': 80, 'output_tokens': 120, 'total_tokens': 200,
        }, True, None),
    )

    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/ai-wbs',
        headers=auth_headers,
        json={'commit': False, 'scorecard_id': 'wbs-card'},
    )

    assert response.status_code == 200
    event = UsageEvent.query.filter_by(thread_id=thread_id, operation_type='execution_plan').one()
    assert event.endpoint == '/threads/<id>/ai-wbs'
    assert event.reserved_credits == 100
    assert event.settled_credits == 10
    assert event.input_tokens == 80
    assert event.output_tokens == 120
    assert event.evaluation_id == '11111111-1111-4111-8111-111111111111'
