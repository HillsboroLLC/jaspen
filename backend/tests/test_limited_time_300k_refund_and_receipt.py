"""A purchase is confirmed to the buyer, and reversing it takes the credits back.

Both paths matter equally: a full-price purchase settles on a PaymentIntent, a
discounted one settles on an invoice, and the invoice route is the one that had
been missed.
"""
import pytest

from app.founder_entitlements import (
    grant_limited_time_300k_offer,
    has_limited_time_300k_entitlement,
    limited_time_300k_credit_balance,
)


@pytest.fixture
def buyer(db, test_user):
    test_user.stripe_customer_id = 'cus_limited_time_300k'
    db.session.commit()
    return test_user


def _charge(**overrides):
    charge = {
        'id': 'ch_limited_time_300k',
        'customer': 'cus_limited_time_300k',
        'amount_refunded': 99900,
        'metadata': {},
    }
    charge.update(overrides)
    return charge


# —— Reversing a purchase ————————————————————————————————


def test_refunding_a_full_price_purchase_reverses_the_credits(app, db, buyer):
    from app.routes import billing

    grant_limited_time_300k_offer(
        buyer, 300_000_000,
        payment_reference='pi_full_price',
        metadata={'stripe_payment_intent_id': 'pi_full_price'},
    )
    db.session.commit()

    assert billing._is_limited_time_300k_charge(
        buyer, _charge(payment_intent='pi_full_price'),
    ) is True


def test_refunding_a_discounted_purchase_reverses_the_credits(app, db, buyer):
    """The invoice route: its charge carries no metadata of ours.

    Matching only on the payment intent let a promo-code buyer keep all 300,000
    credits after a refund or a dispute.
    """
    from app.routes import billing

    grant_limited_time_300k_offer(
        buyer, 300_000_000,
        payment_reference='in_discounted',
        metadata={'stripe_invoice_id': 'in_discounted', 'promotion_code': 'LAUNCH20'},
    )
    db.session.commit()

    assert billing._is_limited_time_300k_charge(
        buyer,
        _charge(payment_intent='pi_belonging_to_the_invoice', invoice='in_discounted'),
    ) is True


def test_an_unrelated_charge_is_not_treated_as_the_offer(app, db, buyer):
    from app.routes import billing

    grant_limited_time_300k_offer(
        buyer, 300_000_000,
        payment_reference='in_discounted',
        metadata={'stripe_invoice_id': 'in_discounted'},
    )
    db.session.commit()

    assert billing._is_limited_time_300k_charge(
        buyer, _charge(payment_intent='pi_something_else', invoice='in_a_subscription'),
    ) is False


def test_a_refund_webhook_takes_back_a_discounted_purchase(client, app, db, buyer, monkeypatch):
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_refund_test'
    grant_limited_time_300k_offer(
        buyer, 300_000_000,
        payment_reference='in_discounted_hook',
        metadata={'stripe_invoice_id': 'in_discounted_hook'},
    )
    db.session.commit()
    assert limited_time_300k_credit_balance(buyer) == 300_000_000

    event = {
        'id': 'evt_charge_refunded_discounted',
        'type': 'charge.refunded',
        'data': {'object': _charge(
            payment_intent='pi_of_the_invoice', invoice='in_discounted_hook',
        )},
    }
    monkeypatch.setattr(billing.stripe.Webhook, 'construct_event', lambda *_args: event)

    response = client.post(
        '/api/v1/billing/webhook', data=b'{}', headers={'Stripe-Signature': 'test'},
    )

    assert response.status_code == 200
    assert limited_time_300k_credit_balance(buyer) == 0
    assert has_limited_time_300k_entitlement(buyer) is False


# —— Telling the buyer ————————————————————————————————


def test_the_buyer_is_emailed_once_when_the_credits_land(app, db, buyer, monkeypatch):
    from app.routes import billing

    app.config['LIMITED_TIME_300K_CREDIT_TOKENS'] = 300_000_000
    sent = []
    monkeypatch.setattr(
        billing, '_send_limited_time_300k_welcome_email',
        lambda user, **kwargs: sent.append({'user': user, **kwargs}) or True,
    )
    intent = {
        'id': 'pi_welcome_once',
        'status': 'succeeded',
        'customer': 'cus_limited_time_300k',
        'metadata': {
            'user_id': str(buyer.id),
            'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
            'tokens': '300000000',
        },
    }

    first = billing._fulfill_limited_time_300k_payment_intent(intent)
    db.session.commit()
    second = billing._fulfill_limited_time_300k_payment_intent(intent)
    db.session.commit()

    assert first['granted'] is True
    assert second.get('granted') is not True
    # A redelivered event must not send a second receipt.
    assert len(sent) == 1
    assert sent[0]['reference'] == 'pi_welcome_once'


def test_a_failed_send_never_costs_the_buyer_their_credits(app, db, buyer, monkeypatch):
    """The credits are already paid for; a mail outage cannot undo that."""
    from app.routes import billing

    def explode(*_args, **_kwargs):
        raise RuntimeError('SMTP is down')

    monkeypatch.setattr(billing, '_price_label', lambda amount: '$799.20')
    monkeypatch.setattr('flask_mail.Mail.send', explode)

    invoice = {
        'id': 'in_mail_outage',
        'status': 'paid',
        'amount_paid': 79920,
        'customer': 'cus_limited_time_300k',
        'metadata': {
            'user_id': str(buyer.id),
            'checkout_type': billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
            'tokens': '300000000',
        },
    }

    result = billing._fulfill_limited_time_300k_invoice(invoice)
    db.session.commit()

    assert result['granted'] is True
    assert limited_time_300k_credit_balance(buyer) == 300_000_000


def test_the_receipt_states_what_was_bought():
    from app.email_templates.limited_time_300k_welcome import (
        render_limited_time_300k_welcome_email,
    )

    rendered = render_limited_time_300k_welcome_email(
        recipient_name='Lydia Bailey', amount_label='$999', receipt_reference='in_abc123',
    )

    assert '300,000' in rendered['subject']
    for part in (rendered['body'], rendered['html']):
        assert '300,000' in part
        assert '$999' in part
        assert 'in_abc123' in part
        assert 'do not expire' in part
    # The offer never starts a subscription, and the receipt has to say so.
    assert 'No subscription was started' in rendered['html']


def test_the_receipt_greets_the_buyer_by_first_name():
    from app.email_templates.limited_time_300k_welcome import (
        render_limited_time_300k_welcome_email,
    )

    named = render_limited_time_300k_welcome_email(recipient_name='Lydia Bailey')
    assert 'Hi Lydia,' in named['html']
    assert 'Hi Lydia,' in named['body']
    # Surname dropped: a $999 receipt should not read like a form letter.
    assert 'Hi Lydia Bailey,' not in named['html']

    # An account with no name still gets a greeting rather than a blank line.
    anonymous = render_limited_time_300k_welcome_email(recipient_name='')
    assert 'Hi there,' in anonymous['html']


def test_the_buyers_name_reaches_the_email(app, db, buyer, monkeypatch):
    from app.routes import billing

    buyer.name = 'Lydia Bailey'
    db.session.commit()
    captured = {}
    monkeypatch.setattr(
        'app.routes.billing.render_limited_time_300k_welcome_email'
        if hasattr(billing, 'render_limited_time_300k_welcome_email') else
        'app.email_templates.limited_time_300k_welcome.render_limited_time_300k_welcome_email',
        lambda **kwargs: captured.update(kwargs) or {
            'subject': 's', 'preview_text': 'p', 'body': 'b', 'html': 'h',
        },
    )
    monkeypatch.setattr('flask_mail.Mail.send', lambda *_a, **_k: None)

    billing._send_limited_time_300k_welcome_email(buyer, reference='pi_named')

    assert captured['recipient_name'] == 'Lydia Bailey'


def test_no_preview_placeholder_can_reach_a_buyer():
    """The preview reference must never be reachable from the app itself.

    Real sends pass the Stripe id - the invoice for a discounted purchase, the
    payment intent for a full-price one - which is what a buyer quotes back to
    support. The preview script's stand-in lives only in scripts/.
    """
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / 'app'
    offenders = [
        str(path.relative_to(app_dir))
        for path in app_dir.rglob('*.py')
        if 'in_preview_example' in path.read_text()
    ]

    assert offenders == []


def test_the_receipt_omits_the_reference_line_entirely_when_absent():
    from app.email_templates.limited_time_300k_welcome import (
        render_limited_time_300k_welcome_email,
    )

    rendered = render_limited_time_300k_welcome_email(recipient_name='Lydia')

    assert 'Reference:' not in rendered['html']
    assert 'Reference:' not in rendered['body']
