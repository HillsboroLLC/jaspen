def test_stripe_webhook_requires_configured_secret(client, app):
    app.config["STRIPE_WEBHOOK_SECRET"] = ""
    resp = client.post("/api/v1/billing/webhook", data=b"{}")
    assert resp.status_code == 503


def test_stripe_webhook_rejects_invalid_signature(client, app):
    app.config["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    resp = client.post(
        "/api/v1/billing/webhook",
        data=b"{}",
        headers={"Stripe-Signature": "invalid"},
    )
    assert resp.status_code == 400


def test_seat_catalog_enforces_team_and_business_limits(client, app):
    response = client.get('/api/v1/billing/catalog')
    assert response.status_code == 200
    plans = response.get_json()['plans']
    assert plans['team']['included_seats'] == 3
    assert plans['team']['max_total_paid_seats'] == 4
    assert plans['team']['additional_seat_price'] == 25
    assert plans['business']['included_seats'] == 5
    assert plans['business']['max_total_paid_seats'] == 10
    assert plans['business']['additional_seat_price'] == 30


def test_catalog_exposes_project_estimates_and_shared_allowance_wording(client):
    response = client.get('/api/v1/billing/catalog')
    assert response.status_code == 200
    plans = response.get_json()['plans']

    assert plans['free']['monthly_credits'] == 300
    assert plans['free']['project_evaluation_estimate'] == '~1 focused evaluation with complete inputs'
    assert plans['starter']['project_evaluation_estimate'] == '~3–4 typical project evaluations'
    assert plans['essential']['project_evaluation_estimate'] == '~17–29 typical project evaluations'
    assert plans['team']['monthly_credits'] == 29_000
    assert plans['team']['project_evaluation_estimate'] == '~57–96 typical project evaluations across the shared allowance'
    assert plans['business']['monthly_credits'] == 80_000
    assert plans['business']['project_evaluation_estimate'] == '~133–222 typical project evaluations across the shared allowance'


def test_catalog_exposes_every_configured_annual_plan(client, app):
    app.config['STRIPE_ANNUAL_PRICE_IDS'] = {
        'starter': 'price_starter_annual',
        'essential': 'price_essential_annual',
        'team': 'price_team_annual',
        'business': 'price_business_annual',
    }

    response = client.get('/api/v1/billing/catalog')
    assert response.status_code == 200
    plans = response.get_json()['plans']
    assert plans['starter']['stripe_annual_price_id'] == 'price_starter_annual'
    assert plans['essential']['stripe_annual_price_id'] == 'price_essential_annual'
    assert plans['team']['stripe_annual_price_id'] == 'price_team_annual'
    assert plans['business']['stripe_annual_price_id'] == 'price_business_annual'
    assert plans['starter']['annual_monthly_price_usd'] == 6
    assert plans['essential']['annual_monthly_price_usd'] == 32
    assert plans['team']['annual_monthly_price_usd'] == 107
    assert plans['business']['annual_monthly_price_usd'] == 249


def test_embedded_checkout_uses_selected_annual_price(
    client, app, db, test_user, auth_headers, monkeypatch
):
    from app.routes import billing as billing_routes

    test_user.stripe_customer_id = 'cus_test'
    db.session.commit()
    app.config['STRIPE_ANNUAL_PRICE_IDS']['essential'] = 'price_essential_annual'

    monkeypatch.setattr(
        billing_routes.stripe.Subscription,
        'list',
        lambda **_kwargs: {'data': []},
    )
    captured = {}

    def create_subscription(**kwargs):
        captured.update(kwargs)
        subscription = {
            'id': 'sub_annual',
            'latest_invoice': {'id': 'in_annual'},
        }
        return type('StripeSubscription', (dict,), {'id': 'sub_annual'})(subscription)

    monkeypatch.setattr(billing_routes.stripe.Subscription, 'create', create_subscription)
    monkeypatch.setattr(
        billing_routes.stripe.Invoice,
        'retrieve',
        lambda _invoice_id, **_kwargs: {
            'confirmation_secret': {'client_secret': 'pi_secret'},
            'payment_intent': None,
        },
    )

    response = client.post(
        '/api/v1/billing/create-subscription',
        headers=auth_headers,
        json={'plan_key': 'essential', 'billing_interval': 'annual'},
    )
    assert response.status_code == 200
    assert captured['items'] == [{'price': 'price_essential_annual'}]
    assert captured['metadata']['billing_interval'] == 'annual'
    assert response.get_json()['billing_interval'] == 'annual'


def test_free_plan_does_not_expose_seat_billing(client, auth_headers):
    response = client.get('/api/v1/billing/seats', headers=auth_headers)
    assert response.status_code == 404


def test_team_owner_can_purchase_only_one_additional_seat(
    client, app, db, test_user, auth_headers, monkeypatch
):
    from app.routes import billing as billing_routes

    test_user.subscription_plan = 'team'
    test_user.stripe_subscription_id = 'sub_team'
    db.session.commit()
    app.config['STRIPE_ADDITIONAL_SEAT_PRICE_IDS']['team'] = 'price_team_seat'

    monkeypatch.setattr(
        billing_routes.stripe.Subscription,
        'retrieve',
        lambda _subscription_id: {
            'items': {'data': [{'id': 'si_base', 'price': {'id': 'price_team'}}]},
        },
    )
    calls = []

    def modify(subscription_id, **kwargs):
        calls.append((subscription_id, kwargs))
        return {'status': 'active', 'latest_invoice': {'status': 'paid'}}

    monkeypatch.setattr(billing_routes.stripe.Subscription, 'modify', modify)

    response = client.post('/api/v1/billing/seats', headers=auth_headers, json={})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['current_seats'] == 4
    assert payload['max_total_seats'] == 4
    assert payload['seat_product_label'] == 'Team Seat'
    assert calls[0][1]['items'] == [{'price': 'price_team_seat', 'quantity': 1}]

    response = client.post('/api/v1/billing/seats', headers=auth_headers, json={})
    assert response.status_code == 400
    assert 'up to 4 users' in response.get_json()['msg']


def test_annual_team_owner_purchases_annual_seat(
    client, app, db, test_user, auth_headers, monkeypatch
):
    from app.routes import billing as billing_routes

    test_user.subscription_plan = 'team'
    test_user.stripe_subscription_id = 'sub_team_annual'
    db.session.commit()
    app.config['STRIPE_ANNUAL_PRICE_IDS']['team'] = 'price_team_annual'
    app.config['STRIPE_ANNUAL_ADDITIONAL_SEAT_PRICE_IDS'] = {
        'team': 'price_team_seat_annual',
        'business': 'price_business_seat_annual',
    }

    monkeypatch.setattr(
        billing_routes.stripe.Subscription,
        'retrieve',
        lambda _subscription_id: {
            'items': {'data': [{'id': 'si_base', 'price': {'id': 'price_team_annual'}}]},
            'metadata': {'billing_interval': 'annual'},
        },
    )
    calls = []

    def modify(subscription_id, **kwargs):
        calls.append((subscription_id, kwargs))
        return {'status': 'active', 'latest_invoice': {'status': 'paid'}}

    monkeypatch.setattr(billing_routes.stripe.Subscription, 'modify', modify)

    response = client.post('/api/v1/billing/seats', headers=auth_headers, json={})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['billing_interval'] == 'annual'
    assert payload['additional_seat_price_usd'] == 300
    assert calls[0][1]['items'] == [{'price': 'price_team_seat_annual', 'quantity': 1}]
