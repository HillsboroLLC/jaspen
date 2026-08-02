"""Preflight a promo code against the 300K Limited-Time offer.

Read-only: it looks the code up and asks Stripe to price a preview invoice.
Nothing is created, charged, or redeemed, so it is safe to point at the live
key before testing the real checkout.

    PYTHONPATH=. ./venv/bin/python scripts/check_300k_promo_code.py 300KTEST
    PYTHONPATH=. ./venv/bin/python scripts/check_300k_promo_code.py 300KTEST cus_123

Answers the two questions that actually break this flow: does the code exist
and is it usable, and does it discount THIS price (a coupon restricted to the
subscription products will not).
"""
import sys

import stripe
from flask import current_app

from app import create_app


def _field(obj, name, default=None):
    value = getattr(obj, name, None)
    if value is None and hasattr(obj, 'get'):
        value = obj.get(name)
    return default if value is None else value


def _money(amount, currency='usd'):
    return f'{amount / 100:,.2f} {currency.upper()}'


def check(code, customer_id=''):
    price_id = current_app.config.get('STRIPE_LIMITED_TIME_300K_PRICE_ID')
    if not price_id:
        print('FAIL  PRICE_ID_300K_LIMITED_TIME is not set in this environment.')
        return 1

    mode = 'LIVE' if str(stripe.api_key).startswith('sk_live') else 'TEST'
    print(f'Stripe mode: {mode}   API version: {stripe.api_version}')

    price = stripe.Price.retrieve(price_id)
    amount = int(_field(price, 'unit_amount', 0) or 0)
    currency = _field(price, 'currency', 'usd')
    product_id = _field(price, 'product')
    print(f'Offer price:  {price_id}  {_money(amount, currency)}  product={product_id}')
    if not _field(price, 'active', True):
        print('FAIL  That price is archived in Stripe.')
        return 1

    matches = stripe.PromotionCode.list(code=code, active=True, limit=1)
    promotion = (_field(matches, 'data') or [None])[0]
    if not promotion:
        print(f'FAIL  No active promotion code "{code}". Create the code (not just the coupon) in Stripe.')
        return 1
    promotion_id = _field(promotion, 'id')
    # The nested coupon on a list result comes back empty, so read it back.
    promotion = stripe.PromotionCode.retrieve(promotion_id, expand=['coupon'])
    coupon = _field(promotion, 'coupon') or {}
    applies_to = _field(coupon, 'applies_to') or {}
    products = list(_field(applies_to, 'products') or [])
    print(f'Promo code:   {code} -> {promotion_id}  coupon={_field(coupon, "id")}')
    print(f'              percent_off={_field(coupon, "percent_off")} amount_off={_field(coupon, "amount_off")} '
          f'duration={_field(coupon, "duration")}')
    print(f'              max_redemptions={_field(promotion, "max_redemptions")} '
          f'times_redeemed={_field(promotion, "times_redeemed")} expires_at={_field(promotion, "expires_at")}')
    if products:
        print(f'              restricted to products: {products}')
        if product_id not in products:
            print('FAIL  This coupon is restricted to other products, so it will not discount this offer.')
            print('      In Stripe, edit the coupon to apply to all products, or add this product to it.')
            return 1
    restrictions = _field(promotion, 'restrictions') or {}
    if _field(restrictions, 'first_time_transaction'):
        print('WARN  Code is limited to first-time customers; an account that has bought before cannot use it.')
    if _field(restrictions, 'minimum_amount'):
        print(f'WARN  Code requires a minimum of {_money(int(_field(restrictions, "minimum_amount")), currency)}.')

    # Price it the way checkout will, without creating anything. Stripe wants a
    # customer for a preview; without one, fall back to the coupon's own math.
    try:
        preview_args = {
            'currency': currency,
            'invoice_items': [{'price': price_id}],
            'discounts': [{'promotion_code': promotion_id}],
        }
        if customer_id:
            preview_args['customer'] = customer_id
        preview = stripe.Invoice.create_preview(**preview_args)
        subtotal = int(_field(preview, 'subtotal', 0) or 0)
        total = int(_field(preview, 'total', subtotal) or 0)
    except stripe.error.StripeError as exc:
        percent_off = _field(coupon, 'percent_off')
        amount_off = _field(coupon, 'amount_off')
        subtotal = amount
        if percent_off:
            total = round(amount * (100 - float(percent_off)) / 100)
        elif amount_off:
            total = max(0, amount - int(amount_off))
        else:
            print(f'FAIL  Could not price the code and it has no discount on it: {exc}')
            return 1
        print(f'NOTE  Stripe would not price a preview without a customer ({exc.__class__.__name__});'
              ' figures below come from the coupon itself.')
        print('      Pass a customer id as the second argument for an exact preview.')
    print(f'Preview:      subtotal {_money(subtotal, currency)} -> total {_money(total, currency)}')
    if total >= subtotal:
        print('FAIL  The code applies but discounts nothing on this price.')
        return 1
    if total <= 0:
        print('OK    Fully covered: checkout will grant the credits with no card charge.')
    else:
        print(f'OK    Buyer pays {_money(total, currency)} through the invoice Stripe prices.')
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    app = create_app()
    with app.app_context():
        try:
            return check(sys.argv[1].strip(), sys.argv[2].strip() if len(sys.argv) > 2 else '')
        except stripe.error.StripeError as exc:
            print(f'FAIL  Stripe rejected the check: {exc}')
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
