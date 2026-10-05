from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CartItemRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100)


class CartQuantityRequest(BaseModel):
    quantity: int = Field(gt=0, le=100)


class CartItemResponse(BaseModel):
    product_id: int
    name: str
    category: str
    price: Decimal
    stock: int
    image: str
    quantity: int


class CartResponse(BaseModel):
    items: list[CartItemResponse]
    item_count: int
    total: Decimal


class CheckoutResponse(BaseModel):
    order_id: UUID
    checkout_url: str
    session_id: str


class OrderItemResponse(BaseModel):
    product_id: int | None
    product_name: str
    product_category: str
    product_image: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal


class ShippingAddressResponse(BaseModel):
    name: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None


class OrderResponse(BaseModel):
    id: UUID
    status: Literal[
        "pending_payment", "payment_failed", "paid", "cancelled", "expired",
        "fulfilled", "refunded"
    ]
    currency: str
    subtotal: Decimal
    total: Decimal
    shipping: ShippingAddressResponse
    created_at: datetime
    items: list[OrderItemResponse]