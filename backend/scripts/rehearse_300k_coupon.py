"""Rehearse the 300K coupon checkout against real Stripe, in test mode.

The unit tests mock Stripe, so they prove our call sequence is internally
consistent but not that Stripe accepts it - which is exactly how a removed
parameter reached production. This runs the real calls against the real API,
with no browser and no account of yours involved.

TEST MODE ONLY. It refuses to run with a live key, and it creates its own
throwaway product, price, coupon, promotion code, and customer, then deletes
them again.

    cd ~/sekki-platform/backend
    STRIPE_SECRET_KEY=sk_test_... PYTHONPATH=. ./venv/bin/python scripts/rehearse_300k_coupon.py

Exit code 0 means Stripe accepted every call the checkout makes: a 100%-off
code settles the invoice as paid with nothing to charge, and a partial code
comes back with a client secret the card fields can be mounted against.
"""
import sys
import time

import stripe
from flask import current_app

from app import create_app
from app.routes.billing import (
    LIMITED_TIME_300K_CHECKOUT_TYPE,
    _create_invoice_item_for_price,
    _invoice_payment_client_secret,
    _stripe_field,
)

PRICE_CENTS = 99_900


def _run_checkout_sequence(customer_id, price_id, promotion_code_id, label):
    """The same calls, in the same order, as apply_300k_limited_time_coupon."""
    invoice = stripe.Invoice.create(
        customer=customer_id,
        discounts=[{'promotion_code': promotion_code_id}],
        auto_advance=False,
        collection_method='charge_automatically',
        description=f'Jaspen 300K Limited-Time offer ({label} rehearsal)',
        metadata={
            'user_id': 'rehearsal',
            'checkout_type': LIMITED_TIME_300K_CHECKOUT_TYPE,
            'tokens': '300000000',
        },
    )
    _create_invoice_item_for_price(customer_id, price_id, _stripe_field(invoice, 'id'))
    return stripe.Invoice.finalize_invoice(
        _stripe_field(invoice, 'id'), expand=['confirmation_secret'],
    )


def rehearse():
    if str(stripe.api_key).startswith('sk_live'):
        print('REFUSED  This is a live key. Re-run with STRIPE_SECRET_KEY=sk_test_...')
        return 2
    print(f'Stripe mode: TEST   API version: {stripe.api_version}')

    stamp = str(int(time.time()))
    created = {}
    failures = []
    try:
        product = stripe.Product.create(name=f'Jaspen 300K rehearsal {stamp}')
        created['product'] = product.id
        price = stripe.Price.create(product=product.id, unit_amount=PRICE_CENTS, currency='usd')
        created['price'] = price.id
        customer = stripe.Customer.create(
            email=f'rehearsal+{stamp}@jaspen.invalid', description='300K coupon rehearsal',
        )
        created['customer'] = customer.id
        print(f'Fixtures:    product={product.id} price={price.id} customer={customer.id}')

        for label, percent, expectation in (('100% off', 100, 'free'), ('20% off', 20, 'partial')):
            coupon = stripe.Coupon.create(
                percent_off=percent, duration='once', applies_to={'products': [product.id]},
                name=f'Jaspen rehearsal {percent} {stamp}',
            )
            promotion = stripe.PromotionCode.create(
                coupon=coupon.id, code=f'REHEARSE{percent}{stamp}',
            )
            created.setdefault('coupons', []).append(coupon.id)

            invoice = _run_checkout_sequence(customer.id, price.id, promotion.id, label)
            status = _stripe_field(invoice, 'status')
            subtotal = int(_stripe_field(invoice, 'subtotal', 0) or 0)
            total = int(_stripe_field(invoice, 'total', 0) or 0)
            amount_due = int(_stripe_field(invoice, 'amount_due', 0) or 0)
            print(f'\n{label}:  invoice={_stripe_field(invoice, "id")} status={status}')
            print(f'             subtotal={subtotal / 100:,.2f} total={total / 100:,.2f} '
                  f'amount_due={amount_due / 100:,.2f}')

            if subtotal != PRICE_CENTS:
                failures.append(
                    f'{label}: the offer line never landed on the invoice '
                    f'(subtotal {subtotal}, expected {PRICE_CENTS}).'
                )
                continue
            if expectation == 'free':
                # The buyer must owe nothing, and Stripe must consider it settled -
                # we only grant credits once it reports the invoice paid.
                if amount_due != 0:
                    failures.append(f'{label}: expected nothing to pay, got {amount_due}.')
                elif status != 'paid':
                    failures.append(f'{label}: invoice is {status}, not paid, so no credits would be granted.')
                else:
                    print('             OK  settled as paid; checkout grants the credits with no card charged.')
            else:
                if amount_due != int(round(PRICE_CENTS * 0.8)):
                    failures.append(f'{label}: expected 79920 due, got {amount_due}.')
                client_secret = _invoice_payment_client_secret(invoice)
                if not client_secret:
                    failures.append(f'{label}: no client secret, so the card fields cannot be mounted.')
                else:
                    print(f'             OK  card fields can mount against {client_secret.split("_secret_")[0]}.')
                stripe.Invoice.void_invoice(_stripe_field(invoice, 'id'))
    except stripe.error.StripeError as exc:
        print(f'\nFAIL  Stripe rejected a call the checkout makes: {exc}')
        failures.append(str(exc))
    finally:
        _cleanup(created)

    print()
    if failures:
        for failure in failures:
            print(f'FAIL  {failure}')
        return 1
    print('PASS  Stripe accepted every call the 300K coupon checkout makes.')
    return 0


def _cleanup(created):
    """Leave the test account as we found it."""
    for coupon_id in created.get('coupons', []):
        try:
            stripe.Coupon.delete(coupon_id)  # takes its promotion codes with it
        except stripe.error.StripeError as exc:
            print(f'NOTE  could not delete coupon {coupon_id}: {exc}')
    if created.get('customer'):
        try:
            stripe.Customer.delete(created['customer'])
        except stripe.error.StripeError as exc:
            print(f'NOTE  could not delete customer {created["customer"]}: {exc}')
    if created.get('price'):
        try:
            stripe.Price.modify(created['price'], active=False)
        except stripe.error.StripeError:
            pass  # prices cannot be deleted; archived is as clean as it gets
    if created.get('product'):
        try:
            stripe.Product.modify(created['product'], active=False)
        except stripe.error.StripeError as exc:
            print(f'NOTE  could not archive product {created["product"]}: {exc}')


def main():
    app = create_app()
    with app.app_context():
        current_app.logger.disabled = True
        return rehearse()


if __name__ == '__main__':
    sys.exit(main())
