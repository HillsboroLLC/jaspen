"""Backfill the payments table from Stripe.

The payments table only starts filling from the moment webhook recording
shipped, so every sale before that is missing. This reads settled invoices and
payment intents from Stripe and writes the same rows the webhook path would
have written.

STRICTLY READ-ONLY AGAINST STRIPE. It creates local rows and nothing else — it
never modifies a Stripe object, never grants credits, and never sends mail.
That is why it does not reuse the fulfilment helpers in billing.py: those do
all three. It writes through billing._record_payment, which is the same
idempotent helper the webhooks use, keyed on the Stripe object id — so it is
safe to re-run, and safe to run while webhooks are live.

    cd backend
    PYTHONPATH=. ./venv/bin/python scripts/backfill_payments.py --dry-run
    PYTHONPATH=. ./venv/bin/python scripts/backfill_payments.py --since 2026-01-01

Run the dry run first and check the totals against the Stripe dashboard before
writing anything.
"""
import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone

import stripe

from app import create_app, db
from app.models import Payment, User

LIMITED_TIME_300K_CHECKOUT_TYPE = '300k_limited_time'
CREDIT_PACK_CHECKOUT_TYPES = {'credit_pack', 'overage_pack'}


def _parse_since(raw):
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        raise SystemExit(f"--since must be ISO-8601 (e.g. 2026-01-01), got: {raw!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _field(obj, name, default=None):
    value = getattr(obj, name, None)
    if value is None and hasattr(obj, 'get'):
        value = obj.get(name)
    return default if value is None else value


def _resolve_user(customer_id, metadata):
    user_id = str((metadata or {}).get('user_id') or '').strip()
    if user_id:
        user = User.query.filter_by(id=user_id).first()
        if user:
            return user
    if customer_id:
        return User.query.filter_by(stripe_customer_id=str(customer_id)).first()
    return None


def _invoice_interval(invoice):
    data = (_field(invoice, 'lines', {}) or {}).get('data') or []
    if not data:
        return None
    recurring = (_field(data[0], 'price', {}) or {}).get('recurring') or {}
    interval = recurring.get('interval')
    return str(interval).strip().lower() if interval else None


def _invoice_source(invoice):
    metadata = _field(invoice, 'metadata', {}) or {}
    if str(metadata.get('checkout_type') or '').strip() == LIMITED_TIME_300K_CHECKOUT_TYPE:
        return 'limited_time_300k'
    return 'subscription_invoice'


def _intent_source(intent):
    metadata = _field(intent, 'metadata', {}) or {}
    checkout_type = str(metadata.get('checkout_type') or '').strip()
    if checkout_type == LIMITED_TIME_300K_CHECKOUT_TYPE:
        return 'limited_time_300k'
    if checkout_type in CREDIT_PACK_CHECKOUT_TYPES:
        return 'credit_pack'
    return None


def _paid_at(obj):
    stamp = _field(obj, 'status_transitions', {}) or {}
    epoch = stamp.get('paid_at') or _field(obj, 'created')
    if not epoch:
        return datetime.utcnow()
    return datetime.utcfromtimestamp(int(epoch))


def collect_invoices(since):
    """Settled invoices — subscriptions and the one-time 300K purchases."""
    rows = []
    params = {'status': 'paid', 'limit': 100, 'expand': ['data.lines']}
    if since:
        params['created'] = {'gte': since}
    for invoice in stripe.Invoice.list(**params).auto_paging_iter():
        metadata = _field(invoice, 'metadata', {}) or {}
        rows.append({
            'external_reference': _field(invoice, 'id'),
            'source': _invoice_source(invoice),
            'customer_id': _field(invoice, 'customer'),
            'metadata': metadata,
            'amount_paid': int(_field(invoice, 'amount_paid', 0) or 0),
            'amount_due': int(_field(invoice, 'amount_due', 0) or 0),
            'currency': _field(invoice, 'currency', 'usd'),
            'billing_interval': _invoice_interval(invoice),
            'subscription_id': _field(invoice, 'subscription'),
            'promotion_code': str(metadata.get('promotion_code') or '').strip() or None,
            'paid_at': _paid_at(invoice),
        })
    return rows


def collect_payment_intents(since):
    """Succeeded intents for purchases that never became an invoice."""
    rows = []
    params = {'limit': 100}
    if since:
        params['created'] = {'gte': since}
    for intent in stripe.PaymentIntent.list(**params).auto_paging_iter():
        if str(_field(intent, 'status') or '') != 'succeeded':
            continue
        source = _intent_source(intent)
        if source is None:
            continue
        # An intent attached to an invoice is already covered by that invoice.
        if _field(intent, 'invoice'):
            continue
        metadata = _field(intent, 'metadata', {}) or {}
        rows.append({
            'external_reference': _field(intent, 'id'),
            'source': source,
            'customer_id': _field(intent, 'customer'),
            'metadata': metadata,
            'amount_paid': int(_field(intent, 'amount_received', 0) or 0),
            'amount_due': int(_field(intent, 'amount', 0) or 0),
            'currency': _field(intent, 'currency', 'usd'),
            'billing_interval': None,
            'subscription_id': None,
            'promotion_code': str(metadata.get('promotion_code') or '').strip() or None,
            'paid_at': _paid_at(intent),
        })
    return rows


def summarize(rows):
    by_source = defaultdict(lambda: {'rows': 0, 'cents': 0, 'comped': 0})
    for row in rows:
        bucket = by_source[row['source']]
        bucket['rows'] += 1
        bucket['cents'] += row['amount_paid']
        if row['amount_paid'] == 0 and row['amount_due'] > 0:
            bucket['comped'] += 1
    return by_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', help='ISO date of the first production sale, e.g. 2026-01-01')
    parser.add_argument('--dry-run', action='store_true',
                        help='report what would be written without writing anything')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        secret = app.config.get('STRIPE_SECRET_KEY')
        if not secret:
            raise SystemExit('STRIPE_SECRET_KEY is not configured.')
        stripe.api_key = secret

        since = _parse_since(args.since)
        print(f"Reading Stripe{' since ' + args.since if args.since else ' (all time)'}…")
        rows = collect_invoices(since) + collect_payment_intents(since)
        print(f"Found {len(rows)} settled Stripe objects.\n")

        for source, totals in sorted(summarize(rows).items()):
            print(f"  {source:<22} {totals['rows']:>5} rows  "
                  f"${totals['cents'] / 100:>12,.2f}  "
                  f"({totals['comped']} fully discounted)")

        existing = {
            reference for (reference,) in db.session.query(Payment.external_reference).all()
        }
        new_rows = [row for row in rows if row['external_reference'] not in existing]
        print(f"\n{len(rows) - len(new_rows)} already recorded, {len(new_rows)} to write.")

        if args.dry_run:
            print("\nDry run — nothing written.")
            return 0

        if not new_rows:
            print("Nothing to do.")
            return 0

        from app.routes import billing

        written = 0
        unresolved = 0
        for row in new_rows:
            user = _resolve_user(row['customer_id'], row['metadata'])
            if user is None:
                unresolved += 1
            _payment, created = billing._record_payment(
                external_reference=row['external_reference'],
                source=row['source'],
                user=user,
                amount_paid=row['amount_paid'],
                amount_due=row['amount_due'],
                currency=row['currency'],
                billing_interval=row['billing_interval'],
                subscription_id=row['subscription_id'],
                promotion_code=row['promotion_code'],
                paid_at=row['paid_at'],
            )
            if created:
                written += 1
        db.session.commit()

        print(f"Wrote {written} payment rows.")
        if unresolved:
            # Kept rather than dropped: the money was received either way, and
            # a row with no user still belongs in gross revenue.
            print(f"{unresolved} could not be matched to a local user "
                  f"(recorded with user_id NULL).")
        return 0


if __name__ == '__main__':
    sys.exit(main())
