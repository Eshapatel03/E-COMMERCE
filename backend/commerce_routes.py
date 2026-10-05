from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Query

from backend.commerce import CommerceService, amount_to_minor_units
from backend.config import get_settings
from backend.dependencies import get_current_user
from backend.schemas import (
    CartItemRequest,
    CartQuantityRequest,
    CartResponse,
    CheckoutResponse,
    OrderResponse,
)


router = APIRouter(tags=["commerce"])
commerce_service = CommerceService()


def _cancel_url(base_url, public_id):
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"checkout": "cancelled", "order_id": str(public_id)})
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


@router.get("/cart", response_model=CartResponse)
def get_cart(user=Depends(get_current_user)):
    return commerce_service.get_cart(user["id"])


@router.post("/cart/items", response_model=CartResponse)
def add_cart_item(request: CartItemRequest, user=Depends(get_current_user)):
    return commerce_service.add_cart_item(
        user["id"], request.product_id, request.quantity
    )


@router.patch("/cart/items/{product_id}", response_model=CartResponse)
def update_cart_item(
    product_id: int,
    request: CartQuantityRequest,
    user=Depends(get_current_user),
):
    return commerce_service.set_cart_item_quantity(
        user["id"], product_id, request.quantity
    )


@router.delete("/cart/items/{product_id}", response_model=CartResponse)
def delete_cart_item(product_id: int, user=Depends(get_current_user)):
    return commerce_service.remove_cart_item(user["id"], product_id)


@router.post("/checkout/session", response_model=CheckoutResponse)
def create_checkout_session(
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
    user=Depends(get_current_user),
):
    settings = get_settings()
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Payments are not configured")
    if len(idempotency_key.strip()) < 8:
        raise HTTPException(status_code=400, detail="Idempotency-Key must contain at least 8 characters")

    currency = settings.stripe_currency
    order = commerce_service.create_checkout_order(
        user["id"], idempotency_key.strip(), currency
    )
    if order["stripe_session_id"]:
        try:
            session = stripe.checkout.Session.retrieve(
                order["stripe_session_id"], api_key=settings.stripe_secret_key
            )
        except stripe.error.StripeError as error:
            raise HTTPException(status_code=502, detail="Unable to retrieve checkout session") from error
        if session.get("status") == "open" and session.get("url"):
            return {
                "order_id": order["public_id"],
                "checkout_url": session["url"],
                "session_id": session["id"],
            }
        if session.get("status") == "expired":
            commerce_service.expire_pending_order(order["public_id"], user["id"])
        raise HTTPException(status_code=409, detail="Checkout session is no longer open")

    expiration = datetime.now(timezone.utc) + timedelta(minutes=31)
    try:
        session = stripe.checkout.Session.create(
            api_key=settings.stripe_secret_key,
            idempotency_key=str(order["public_id"]),
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": currency,
                        "unit_amount": amount_to_minor_units(item["unit_price"], currency),
                        "product_data": {"name": item["product_name"]},
                    },
                    "quantity": item["quantity"],
                }
                for item in order["items"]
            ],
            success_url=settings.stripe_success_url,
            cancel_url=_cancel_url(settings.stripe_cancel_url, order["public_id"]),
            client_reference_id=str(order["public_id"]),
            metadata={"order_public_id": str(order["public_id"])},
            payment_intent_data={
                "metadata": {"order_public_id": str(order["public_id"])}
            },
            shipping_address_collection={
                "allowed_countries": list(settings.stripe_allowed_countries)
            },
            expires_at=int(expiration.timestamp()),
        )
    except stripe.error.StripeError as error:
        raise HTTPException(
            status_code=502, detail="Unable to start checkout. Please retry shortly."
        ) from error

    expires_at = datetime.fromtimestamp(session["expires_at"], timezone.utc)
    commerce_service.attach_checkout_session(
        order["public_id"], session["id"], expires_at
    )
    return {
        "order_id": order["public_id"],
        "checkout_url": session["url"],
        "session_id": session["id"],
    }


@router.get("/orders", response_model=list[OrderResponse])
def list_orders(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user),
):
    return commerce_service.list_orders(user["id"], limit, offset)


@router.get("/checkout/session/{session_id}", response_model=OrderResponse)
def get_checkout_order(session_id: str, user=Depends(get_current_user)):
    order = commerce_service.get_order_by_session(user["id"], session_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Checkout session not found")
    return order


@router.get("/orders/{public_id}", response_model=OrderResponse)
def get_order(public_id: UUID, user=Depends(get_current_user)):
    order = commerce_service.get_order(user["id"], public_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/orders/{public_id}/cancel")
def cancel_order(public_id: UUID, user=Depends(get_current_user)):
    settings = get_settings()
    session_id = commerce_service.get_order_session(public_id, user["id"])
    if not session_id:
        status = commerce_service.cancel_pending_order(public_id, user["id"])
        return {"status": status}
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Payments are not configured")
    try:
        session = stripe.checkout.Session.retrieve(
            session_id, api_key=settings.stripe_secret_key
        )
        if session.get("status") == "open":
            stripe.checkout.Session.expire(
                session_id, api_key=settings.stripe_secret_key
            )
            status = commerce_service.cancel_pending_order(public_id, user["id"])
            return {"status": status}
        if session.get("status") == "expired":
            status = commerce_service.expire_pending_order(public_id, user["id"])
            return {"status": status}
    except stripe.error.StripeError as error:
        raise HTTPException(status_code=502, detail="Unable to cancel checkout") from error
    raise HTTPException(status_code=409, detail="Checkout has already been completed")