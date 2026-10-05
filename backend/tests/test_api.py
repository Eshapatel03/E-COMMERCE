import hashlib
import hmac
import json
import time
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.dependencies import get_current_user
from backend.main import app, auth_service as main_auth_service
from backend import commerce_routes, webhook_routes


def test_cart_endpoint_requires_authentication():
    response = TestClient(app).get("/cart")
    assert response.status_code == 401


def test_cart_endpoint_uses_authenticated_user(monkeypatch):
    seen = []
    monkeypatch.setattr(
        commerce_routes.commerce_service,
        "get_cart",
        lambda user_id: seen.append(user_id) or {"items": [], "item_count": 0, "total": "0.00"},
    )
    app.dependency_overrides[get_current_user] = lambda: {"id": 74, "role": "user"}
    try:
        response = TestClient(app).get("/cart")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200
    assert seen == [74]


def test_signup_and_login_keep_the_existing_api_contract(monkeypatch):
    monkeypatch.setattr(
        main_auth_service,
        "signup",
        lambda name, email, password: {"id": 3, "name": name, "email": email, "role": "user"},
    )
    monkeypatch.setattr(
        main_auth_service,
        "login",
        lambda email, password: {
            "token": "opaque-token",
            "user": {"id": 3, "name": "Customer", "email": email, "role": "user"},
        },
    )
    client = TestClient(app)
    signup = client.post("/auth/signup", json={
        "name": "Customer",
        "email": "customer@example.com",
        "password": "StrongPassword9!",
        "confirm_password": "StrongPassword9!",
    })
    login = client.post("/auth/login", json={
        "email": "customer@example.com",
        "password": "StrongPassword9!",
    })
    assert signup.status_code == 201
    assert login.status_code == 200
    assert set(login.json()) == {"token", "user"}


def test_order_list_is_scoped_to_current_user(monkeypatch):
    seen = []
    monkeypatch.setattr(
        commerce_routes.commerce_service,
        "list_orders",
        lambda user_id, limit, offset: seen.append((user_id, limit, offset)) or [],
    )
    app.dependency_overrides[get_current_user] = lambda: {"id": 91, "role": "user"}
    try:
        response = TestClient(app).get("/orders?limit=5&offset=10")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200
    assert seen == [(91, 5, 10)]


def test_checkout_creates_a_server_priced_stripe_session(monkeypatch):
    now = int(time.time()) + 1900
    settings = SimpleNamespace(
        stripe_secret_key="local-checkout-test-key",
        stripe_webhook_secret="local-webhook-test-key",
        stripe_currency="usd",
        stripe_success_url="http://localhost:5173/?session_id={CHECKOUT_SESSION_ID}",
        stripe_cancel_url="http://localhost:5173/?checkout=cancelled",
        stripe_allowed_countries=("US",),
    )
    monkeypatch.setattr(commerce_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        commerce_routes.commerce_service,
        "create_checkout_order",
        lambda user_id, key, currency: {
            "public_id": "2ef6e906-bbcc-47e4-b292-02a36aa2bac4",
            "items": [{"product_name": "Lamp", "unit_price": Decimal("12.50"), "quantity": 2}],
            "stripe_session_id": None,
        },
    )
    created = {}

    def create_session(**values):
        created.update(values)
        return {
            "id": "cs_test_session",
            "url": "https://checkout.stripe.com/test",
            "expires_at": now,
        }

    monkeypatch.setattr(commerce_routes.stripe.checkout.Session, "create", create_session)
    monkeypatch.setattr(
        commerce_routes.commerce_service,
        "attach_checkout_session",
        lambda *values: None,
    )
    app.dependency_overrides[get_current_user] = lambda: {"id": 8, "role": "user"}
    try:
        response = TestClient(app).post(
            "/checkout/session",
            headers={"Idempotency-Key": "checkout-request-1"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200
    assert created["line_items"][0]["price_data"]["unit_amount"] == 1250
    assert created["line_items"][0]["quantity"] == 2
    assert created["metadata"]["order_public_id"] == "2ef6e906-bbcc-47e4-b292-02a36aa2bac4"
    assert "payment_method_data" not in created


def test_webhook_rejects_invalid_signature(monkeypatch):
    secret = "local-webhook-test-key"
    monkeypatch.setattr(
        webhook_routes,
        "get_settings",
        lambda: SimpleNamespace(stripe_webhook_secret=secret),
    )
    response = TestClient(app).post(
        "/webhooks/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=invalid"},
    )
    assert response.status_code == 400


def test_webhook_verifies_signature_before_dispatch(monkeypatch):
    secret = "local-webhook-test-key"
    monkeypatch.setattr(
        webhook_routes,
        "get_settings",
        lambda: SimpleNamespace(stripe_webhook_secret=secret),
    )
    processed = []
    monkeypatch.setattr(
        webhook_routes.commerce_service,
        "process_checkout_event",
        lambda *values: processed.append(values),
    )
    payload = json.dumps({
        "id": "evt_test_1",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"order_public_id": "not-a-uuid"}}},
    }).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    response = TestClient(app).post(
        "/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": f"t={timestamp},v1={signature}"},
    )
    assert response.status_code == 200
    assert len(processed) == 1
    assert processed[0][0:2] == ("evt_test_1", "checkout.session.completed")