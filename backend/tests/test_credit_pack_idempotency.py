"""One credit-pack purchase must add its tokens exactly once.

Stripe announces a hosted-checkout purchase twice - as
checkout.session.completed and again as payment_intent.succeeded - under two
different event ids. The webhook's event ledger deduplicates events, not sales,
so it cannot see that those two are the same purchase. These tests hold the
line at the purchase level instead.

The claim rows outlive a test (the db fixture does not clear
StripeWebhookEvent), so every test buys under its own purchase id.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import StripeWebhookEvent

PACK_TOKENS = 8_000_000


@pytest.fixture
def purchase(request):
    """Ids unique to this test: intent, session, and the claim they share."""
    slug = request.node.name[:60]
    intent_id = f'pi_{slug}'
    return {
        'intent': intent_id,
        'session': f'cs_{slug}',
        'claim': f'credit_pack_payment:{intent_id}',
    }


def _metadata(test_user):
    return {
        'user_id': str(test_user.id),
        'checkout_type': 'credit_pack',
        'pack_key': 'credits_8000',
        'credits': '8000',
        'tokens': str(PACK_TOKENS),
    }


def _session_event(test_user, purchase, event_id='evt_session'):
    return {
        'id': f'{event_id}_{purchase["session"]}',
        'type': 'checkout.session.completed',
        'data': {'object': {
            'id': purchase['session'],
            'payment_intent': purchase['intent'],
            'customer': 'cus_credit_pack',
            'metadata': _metadata(test_user),
        }},
    }


def _intent_event(test_user, purchase, event_id='evt_intent'):
    return {
        'id': f'{event_id}_{purchase["intent"]}',
        'type': 'payment_intent.succeeded',
        'data': {'object': {
            'id': purchase['intent'],
            'status': 'succeeded',
            'customer': 'cus_credit_pack',
            'metadata': _metadata(test_user),
        }},
    }


def _deliver(client, billing, monkeypatch, event):
    monkeypatch.setattr(billing.stripe.Webhook, 'construct_event', lambda *_args: event)
    return client.post('/api/v1/billing/webhook', data=b'{}', headers={'Stripe-Signature': 'test'})


def _overage_tokens(user):
    meter = (user.ui_preferences or {}).get('thinking_power') or {}
    return int(meter.get('overage_tokens') or 0)


def _claims(claim_id):
    return StripeWebhookEvent.query.filter_by(stripe_event_id=claim_id).all()


def test_credit_pack_checkout_session_adds_tokens_once(
    client, app, db, test_user, purchase, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_credit_pack'

    response = _deliver(client, billing, monkeypatch, _session_event(test_user, purchase))

    assert response.status_code == 200
    assert _overage_tokens(test_user) == PACK_TOKENS
    claims = _claims(purchase['claim'])
    assert len(claims) == 1
    assert claims[0].processed is True


def test_credit_pack_payment_intent_adds_tokens_once(
    client, app, db, test_user, purchase, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_credit_pack'

    response = _deliver(client, billing, monkeypatch, _intent_event(test_user, purchase))

    assert response.status_code == 200
    assert _overage_tokens(test_user) == PACK_TOKENS
    assert len(_claims(purchase['claim'])) == 1


def test_duplicate_credit_pack_event_id_does_not_double_credit(
    client, app, db, test_user, purchase, monkeypatch
):
    """Stripe retries an unacknowledged event under the same id."""
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_credit_pack'
    event = _intent_event(test_user, purchase)

    first = _deliver(client, billing, monkeypatch, event)
    second = _deliver(client, billing, monkeypatch, event)

    assert first.status_code == 200
    assert second.status_code == 200
    assert _overage_tokens(test_user) == PACK_TOKENS


def test_duplicate_credit_pack_session_event_id_does_not_double_credit(
    client, app, db, test_user, purchase, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_credit_pack'
    event = _session_event(test_user, purchase)

    first = _deliver(client, billing, monkeypatch, event)
    second = _deliver(client, billing, monkeypatch, event)

    assert first.status_code == 200
    assert second.status_code == 200
    assert _overage_tokens(test_user) == PACK_TOKENS


def test_one_credit_pack_purchase_delivered_as_two_event_types_credits_once(
    client, app, db, test_user, purchase, monkeypatch
):
    """The case the event ledger cannot catch: same sale, two event ids.

    Both events carry the same PaymentIntent, and that is what the claim is
    keyed on - so whichever arrives second adds nothing.
    """
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_credit_pack'

    session_delivery = _deliver(client, billing, monkeypatch, _session_event(test_user, purchase))
    intent_delivery = _deliver(client, billing, monkeypatch, _intent_event(test_user, purchase))

    assert session_delivery.status_code == 200
    assert intent_delivery.status_code == 200
    assert _overage_tokens(test_user) == PACK_TOKENS
    assert len(_claims(purchase['claim'])) == 1


def test_two_event_types_credit_once_in_either_order(
    client, app, db, test_user, purchase, monkeypatch
):
    """Stripe does not promise which of the two arrives first."""
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_credit_pack'

    intent_delivery = _deliver(client, billing, monkeypatch, _intent_event(test_user, purchase))
    session_delivery = _deliver(client, billing, monkeypatch, _session_event(test_user, purchase))

    assert intent_delivery.status_code == 200
    assert session_delivery.status_code == 200
    assert _overage_tokens(test_user) == PACK_TOKENS
    assert len(_claims(purchase['claim'])) == 1


def test_concurrent_credit_pack_delivery_stands_down_instead_of_crediting_twice(
    app, db, test_user, purchase, monkeypatch
):
    """Two workers race for the same purchase; the unique index picks one.

    The loser must not fall through and add the tokens anyway - for credit
    packs there is no grant row underneath with its own constraint to catch it.
    """
    from app.routes import billing

    real_flush = db.session.flush
    lost_race = {'done': False}

    def flush_losing_the_race(*args, **kwargs):
        claimed = any(
            isinstance(obj, StripeWebhookEvent) and obj.stripe_event_id == purchase['claim']
            for obj in db.session.new
        )
        if claimed and not lost_race['done']:
            lost_race['done'] = True
            raise IntegrityError('INSERT INTO stripe_webhook_events', {}, Exception('duplicate key'))
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db.session, 'flush', flush_losing_the_race)

    result = billing._fulfill_credit_pack_purchase(
        purchase['intent'],
        _metadata(test_user),
        event_type='payment_intent.succeeded',
        customer_id='cus_credit_pack',
    )

    assert lost_race['done'] is True
    assert result['granted'] is False
    assert result['reason'] == 'in_flight'
    assert _overage_tokens(test_user) == 0


def test_credit_pack_session_without_an_intent_still_claims_the_purchase(
    client, app, db, test_user, purchase, monkeypatch
):
    """A session that never produced an intent falls back to its own id."""
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_credit_pack'
    event = _session_event(test_user, purchase)
    event['data']['object'].pop('payment_intent')

    first = _deliver(client, billing, monkeypatch, event)
    event['id'] = f'{event["id"]}_retry'
    second = _deliver(client, billing, monkeypatch, event)

    assert first.status_code == 200
    assert second.status_code == 200
    assert _overage_tokens(test_user) == PACK_TOKENS
    assert StripeWebhookEvent.query.filter_by(
        stripe_event_id=f'credit_pack_payment:{purchase["session"]}'
    ).count() == 1
