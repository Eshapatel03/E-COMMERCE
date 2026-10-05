import stripe
from fastapi import APIRouter, Header, HTTPException, Request

from backend.commerce import CommerceService
from backend.config import get_settings


router = APIRouter(tags=["payments"])
commerce_service = CommerceService()
MAX_WEBHOOK_SIZE = 1024 * 1024


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
):
    webhook_secret = get_settings().stripe_webhook_secret
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Payment webhook is not configured")
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_WEBHOOK_SIZE:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > MAX_WEBHOOK_SIZE:
            raise HTTPException(status_code=413, detail="Webhook payload is too large")
        payload.extend(chunk)
    try:
        event = stripe.Webhook.construct_event(
            bytes(payload), stripe_signature, webhook_secret
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from error
    except stripe.error.SignatureVerificationError as error:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature") from error

    data = event["data"]["object"]
    try:
        commerce_service.process_checkout_event(event["id"], event["type"], data)
    except Exception as error:
        raise HTTPException(status_code=500, detail="Webhook processing failed") from error
    return {"received": True}