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
    assert calls[0][1]['items'] == [{'price': 'price_team_seat', 'quantity': 1}]

    response = client.post('/api/v1/billing/seats', headers=auth_headers, json={})
    assert response.status_code == 400
    assert 'up to 4 users' in response.get_json()['msg']
