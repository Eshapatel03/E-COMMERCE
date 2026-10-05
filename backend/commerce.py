from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from backend.database import get_connection


class CommerceError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail


class CommerceService:
    def get_cart(self, user_id):
        with get_connection() as connection:
            cart_id = self._active_cart_id(connection, user_id)
            return self._cart_response(connection, cart_id)

    def add_cart_item(self, user_id, product_id, quantity):
        with get_connection() as connection:
            cart_id = self._active_cart_id(connection, user_id)
            product = connection.execute(
                "SELECT id, stock FROM products WHERE id = %s FOR UPDATE",
                (product_id,),
            ).fetchone()
            if product is None:
                raise CommerceError(404, "Product not found")
            existing = connection.execute(
                "SELECT quantity FROM cart_items WHERE cart_id = %s AND product_id = %s",
                (cart_id, product_id),
            ).fetchone()
            new_quantity = quantity + (existing["quantity"] if existing else 0)
            if new_quantity > product["stock"]:
                raise CommerceError(409, "Requested quantity exceeds available stock")
            connection.execute(
                """
                INSERT INTO cart_items (cart_id, product_id, quantity)
                VALUES (%s, %s, %s)
                ON CONFLICT (cart_id, product_id) DO UPDATE
                SET quantity = EXCLUDED.quantity, updated_at = NOW()
                """,
                (cart_id, product_id, new_quantity),
            )
            return self._cart_response(connection, cart_id)

    def set_cart_item_quantity(self, user_id, product_id, quantity):
        with get_connection() as connection:
            cart_id = self._active_cart_id(connection, user_id)
            product = connection.execute(
                "SELECT stock FROM products WHERE id = %s FOR UPDATE",
                (product_id,),
            ).fetchone()
            if product is None:
                raise CommerceError(404, "Product not found")
            if quantity > product["stock"]:
                raise CommerceError(409, "Requested quantity exceeds available stock")
            result = connection.execute(
                """
                UPDATE cart_items SET quantity = %s, updated_at = NOW()
                WHERE cart_id = %s AND product_id = %s
                RETURNING id
                """,
                (quantity, cart_id, product_id),
            ).fetchone()
            if result is None:
                raise CommerceError(404, "Cart item not found")
            return self._cart_response(connection, cart_id)

    def remove_cart_item(self, user_id, product_id):
        with get_connection() as connection:
            cart_id = self._active_cart_id(connection, user_id)
            result = connection.execute(
                "DELETE FROM cart_items WHERE cart_id = %s AND product_id = %s RETURNING id",
                (cart_id, product_id),
            ).fetchone()
            if result is None:
                raise CommerceError(404, "Cart item not found")
            return self._cart_response(connection, cart_id)

    def create_checkout_order(self, user_id, idempotency_key, currency):
        with get_connection() as connection:
            existing_order = connection.execute(
                """
                SELECT * FROM orders
                WHERE user_id = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (user_id, idempotency_key),
            ).fetchone()
            if existing_order is not None:
                if existing_order["status"] != "pending_payment":
                    raise CommerceError(409, "This checkout request is no longer active")
                return self._checkout_response(connection, existing_order)

            self._expire_unattached_orders(connection, user_id)

            cart = connection.execute(
                "SELECT id FROM carts WHERE user_id = %s AND status = 'active' FOR UPDATE",
                (user_id,),
            ).fetchone()
            if cart is None:
                raise CommerceError(400, "Your cart is empty")

            items = connection.execute(
                """
                SELECT cart_items.product_id, cart_items.quantity,
                       products.name, products.category, products.price,
                       products.stock, products.image
                FROM cart_items
                JOIN products ON products.id = cart_items.product_id
                WHERE cart_items.cart_id = %s
                ORDER BY products.id
                FOR UPDATE OF products
                """,
                (cart["id"],),
            ).fetchall()
            if not items:
                raise CommerceError(400, "Your cart is empty")
            if any(item["quantity"] > item["stock"] for item in items):
                raise CommerceError(409, "Cart contains a quantity that is no longer available")

            subtotal = sum(
                (item["price"] * item["quantity"] for item in items), Decimal("0.00")
            )
            if not amount_to_minor_units(subtotal, currency):
                raise CommerceError(400, "Checkout total must be greater than zero")
            for item in items:
                amount_to_minor_units(item["price"], currency)

            order_public_id = uuid4()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=45)
            order = connection.execute(
                """
                INSERT INTO orders (
                    public_id, user_id, cart_id, status, currency,
                    subtotal, total, idempotency_key, stock_reserved, expires_at
                )
                VALUES (%s, %s, %s, 'pending_payment', %s, %s, %s, %s, TRUE, %s)
                RETURNING *
                """,
                (
                    order_public_id,
                    user_id,
                    cart["id"],
                    currency,
                    subtotal,
                    subtotal,
                    idempotency_key,
                    expires_at,
                ),
            ).fetchone()
            for item in items:
                connection.execute(
                    "UPDATE products SET stock = stock - %s, updated_at = NOW() WHERE id = %s",
                    (item["quantity"], item["product_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO order_items (
                        order_id, product_id, product_name, product_category,
                        product_image, unit_price, quantity, line_total
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        order["id"],
                        item["product_id"],
                        item["name"],
                        item["category"],
                        item["image"],
                        item["price"],
                        item["quantity"],
                        item["price"] * item["quantity"],
                    ),
                )
            connection.execute(
                "INSERT INTO payments (order_id, amount, currency) VALUES (%s, %s, %s)",
                (order["id"], subtotal, currency),
            )
            connection.execute(
                "UPDATE carts SET status = 'converted', updated_at = NOW() WHERE id = %s",
                (cart["id"],),
            )
            return self._checkout_response(connection, order)

    def attach_checkout_session(self, public_id, session_id, expires_at):
        with get_connection() as connection:
            order = connection.execute(
                "SELECT id FROM orders WHERE public_id = %s AND status = 'pending_payment' FOR UPDATE",
                (public_id,),
            ).fetchone()
            if order is None:
                raise CommerceError(409, "Order is no longer awaiting payment")
            payment = connection.execute(
                "SELECT id, stripe_session_id FROM payments WHERE order_id = %s "
                "ORDER BY id DESC LIMIT 1 FOR UPDATE",
                (order["id"],),
            ).fetchone()
            if payment["stripe_session_id"] not in (None, session_id):
                raise CommerceError(409, "A different payment session is already attached")
            connection.execute(
                "UPDATE payments SET stripe_session_id = %s, updated_at = NOW() WHERE id = %s",
                (session_id, payment["id"]),
            )
            connection.execute(
                "UPDATE orders SET expires_at = %s, updated_at = NOW() WHERE id = %s",
                (expires_at, order["id"]),
            )

    def cancel_pending_order(self, public_id, user_id=None):
        return self._close_pending_order(public_id, user_id, "cancelled")

    def expire_pending_order(self, public_id, user_id=None):
        return self._close_pending_order(public_id, user_id, "expired")

    def _close_pending_order(self, public_id, user_id, terminal_status):
        with get_connection() as connection:
            query = "SELECT * FROM orders WHERE public_id = %s"
            parameters = [public_id]
            if user_id is not None:
                query += " AND user_id = %s"
                parameters.append(user_id)
            order = connection.execute(query + " FOR UPDATE", parameters).fetchone()
            if order is None:
                raise CommerceError(404, "Order not found")
            if order["status"] in {"cancelled", "expired"}:
                return order["status"]
            if order["status"] != "pending_payment":
                raise CommerceError(409, "Only a pending order can be closed")
            self._release_reserved_stock(connection, order, terminal_status)
            connection.execute(
                "UPDATE payments SET status = %s, updated_at = NOW() "
                "WHERE order_id = %s AND status = 'pending'",
                (terminal_status, order["id"]),
            )
            return terminal_status

    def get_order_session(self, public_id, user_id):
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT payments.stripe_session_id, orders.status
                FROM orders
                LEFT JOIN payments ON payments.order_id = orders.id
                WHERE orders.public_id = %s AND orders.user_id = %s
                ORDER BY payments.id DESC LIMIT 1
                """,
                (public_id, user_id),
            ).fetchone()
            if row is None:
                raise CommerceError(404, "Order not found")
            if row["status"] != "pending_payment":
                raise CommerceError(409, "Only a pending order can be cancelled")
            return row["stripe_session_id"]

    def process_checkout_event(self, event_id, event_type, session):
        if event_type not in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
            "checkout.session.async_payment_failed",
            "checkout.session.expired",
            "payment_intent.payment_failed",
        }:
            return

        metadata = session.get("metadata") or {}
        public_id = metadata.get("order_public_id")
        if not public_id:
            return
        try:
            public_id = UUID(str(public_id))
        except ValueError:
            return

        with get_connection() as connection:
            inserted = connection.execute(
                """
                INSERT INTO stripe_webhook_events (event_id, event_type)
                VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING event_id
                """,
                (event_id, event_type),
            ).fetchone()
            if inserted is None:
                return
            order = connection.execute(
                "SELECT * FROM orders WHERE public_id = %s FOR UPDATE",
                (public_id,),
            ).fetchone()
            if order is None:
                return
            payment = connection.execute(
                "SELECT * FROM payments WHERE order_id = %s "
                "ORDER BY id DESC LIMIT 1 FOR UPDATE",
                (order["id"],),
            ).fetchone()
            if event_type == "payment_intent.payment_failed":
                if not session.get("id"):
                    raise CommerceError(400, "Stripe payment event is missing its identifier")
                if payment is not None and order["status"] == "pending_payment":
                    connection.execute(
                        "UPDATE payments SET status = 'failed', "
                        "stripe_payment_intent_id = COALESCE(%s, stripe_payment_intent_id), "
                        "updated_at = NOW() WHERE id = %s",
                        (session.get("id"), payment["id"]),
                    )
                return
            session_id = session.get("id")
            if not session_id:
                raise CommerceError(400, "Stripe Checkout event is missing its identifier")
            if payment is None or payment["stripe_session_id"] not in (None, session_id):
                raise CommerceError(409, "Stripe event does not match the order payment")
            payment_intent = session.get("payment_intent")
            if isinstance(payment_intent, dict):
                payment_intent = payment_intent.get("id")
            connection.execute(
                """
                UPDATE payments
                SET stripe_session_id = COALESCE(stripe_session_id, %s),
                    stripe_payment_intent_id = COALESCE(%s, stripe_payment_intent_id),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (session_id, payment_intent, payment["id"]),
            )

            if event_type in {
                "checkout.session.completed",
                "checkout.session.async_payment_succeeded",
            }:
                if session.get("payment_status") != "paid":
                    return
                self._verify_session_amount(session, order)
                if order["status"] in {"payment_failed", "cancelled", "expired"}:
                    raise CommerceError(409, "Stripe reported payment for a closed order")
                if order["status"] == "pending_payment":
                    self._save_shipping_address(connection, order["id"], session)
                    connection.execute(
                        "UPDATE orders SET status = 'paid', stock_reserved = FALSE, "
                        "updated_at = NOW() WHERE id = %s",
                        (order["id"],),
                    )
                    connection.execute(
                        "UPDATE payments SET status = 'succeeded', updated_at = NOW() WHERE id = %s",
                        (payment["id"],),
                    )
            elif event_type == "checkout.session.async_payment_failed":
                connection.execute(
                    "UPDATE payments SET status = 'failed', updated_at = NOW() WHERE id = %s",
                    (payment["id"],),
                )
                if order["status"] == "pending_payment":
                    self._release_reserved_stock(connection, order, "payment_failed")
            elif event_type == "checkout.session.expired":
                connection.execute(
                    "UPDATE payments SET status = 'expired', updated_at = NOW() WHERE id = %s",
                    (payment["id"],),
                )
                if order["status"] == "pending_payment":
                    self._release_reserved_stock(connection, order, "expired")

    def list_orders(self, user_id, limit, offset):
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM orders WHERE user_id = %s "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (user_id, limit, offset),
            ).fetchall()
            return [self._order_response(connection, row) for row in rows]

    def get_order(self, user_id, public_id):
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE user_id = %s AND public_id = %s",
                (user_id, public_id),
            ).fetchone()
            return self._order_response(connection, row) if row else None

    def get_order_by_session(self, user_id, session_id):
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT orders.* FROM orders
                JOIN payments ON payments.order_id = orders.id
                WHERE orders.user_id = %s AND payments.stripe_session_id = %s
                """,
                (user_id, session_id),
            ).fetchone()
            return self._order_response(connection, row) if row else None

    @staticmethod
    def _active_cart_id(connection, user_id):
        row = connection.execute(
            """
            INSERT INTO carts (user_id) VALUES (%s)
            ON CONFLICT (user_id) WHERE status = 'active'
            DO UPDATE SET updated_at = NOW()
            RETURNING id
            """,
            (user_id,),
        ).fetchone()
        return row["id"]

    @staticmethod
    def _cart_response(connection, cart_id):
        items = connection.execute(
            """
            SELECT products.id AS product_id, products.name, products.category,
                   products.price, products.stock, products.image, cart_items.quantity
            FROM cart_items
            JOIN products ON products.id = cart_items.product_id
            WHERE cart_items.cart_id = %s ORDER BY products.name
            """,
            (cart_id,),
        ).fetchall()
        total = sum(
            (item["price"] * item["quantity"] for item in items), Decimal("0.00")
        )
        return {"items": items, "item_count": sum(item["quantity"] for item in items), "total": total}

    @staticmethod
    def _checkout_response(connection, order):
        items = connection.execute(
            "SELECT * FROM order_items WHERE order_id = %s ORDER BY id",
            (order["id"],),
        ).fetchall()
        payment = connection.execute(
            "SELECT stripe_session_id FROM payments WHERE order_id = %s "
            "ORDER BY id DESC LIMIT 1",
            (order["id"],),
        ).fetchone()
        return {
            "id": order["id"],
            "public_id": order["public_id"],
            "status": order["status"],
            "currency": order["currency"],
            "total": order["total"],
            "expires_at": order["expires_at"],
            "items": items,
            "stripe_session_id": payment["stripe_session_id"] if payment else None,
        }

    @staticmethod
    def _order_response(connection, order):
        items = connection.execute(
            """
            SELECT product_id, product_name, product_category, product_image,
                   unit_price, quantity, line_total
            FROM order_items WHERE order_id = %s ORDER BY id
            """,
            (order["id"],),
        ).fetchall()
        return {
            "id": order["public_id"],
            "status": order["status"],
            "currency": order["currency"],
            "subtotal": order["subtotal"],
            "total": order["total"],
            "shipping": {
                "name": order["shipping_name"],
                "address_line1": order["shipping_address_line1"],
                "address_line2": order["shipping_address_line2"],
                "city": order["shipping_city"],
                "region": order["shipping_region"],
                "postal_code": order["shipping_postal_code"],
                "country": order["shipping_country"],
            },
            "created_at": order["created_at"],
            "items": items,
        }

    @staticmethod
    def _verify_session_amount(session, order):
        expected_amount = amount_to_minor_units(order["total"], order["currency"])
        if session.get("amount_total") != expected_amount:
            raise CommerceError(400, "Stripe amount does not match the order total")
        if (session.get("currency") or "").lower() != order["currency"]:
            raise CommerceError(400, "Stripe currency does not match the order currency")

    @staticmethod
    def _save_shipping_address(connection, order_id, session):
        shipping = session.get("shipping_details") or {}
        address = shipping.get("address") or {}
        customer = session.get("customer_details") or {}
        name = shipping.get("name") or customer.get("name")
        if not name or not address.get("line1") or not address.get("city") or not address.get("country"):
            raise CommerceError(400, "Stripe checkout is missing a required shipping address")
        connection.execute(
            """
            UPDATE orders SET shipping_name = %s, shipping_address_line1 = %s,
                shipping_address_line2 = %s, shipping_city = %s, shipping_region = %s,
                shipping_postal_code = %s, shipping_country = %s
            WHERE id = %s
            """,
            (
                name,
                address.get("line1"),
                address.get("line2"),
                address.get("city"),
                address.get("state"),
                address.get("postal_code"),
                address.get("country"),
                order_id,
            ),
        )

    @staticmethod
    def _release_reserved_stock(connection, order, terminal_status):
        if order["stock_reserved"]:
            items = connection.execute(
                "SELECT product_id, quantity FROM order_items "
                "WHERE order_id = %s AND product_id IS NOT NULL FOR UPDATE",
                (order["id"],),
            ).fetchall()
            for item in items:
                connection.execute(
                    "UPDATE products SET stock = stock + %s, updated_at = NOW() WHERE id = %s",
                    (item["quantity"], item["product_id"]),
                )
            connection.execute(
                "UPDATE orders SET status = %s, stock_reserved = FALSE, updated_at = NOW() "
                "WHERE id = %s",
                (terminal_status, order["id"]),
            )
        if terminal_status in {"payment_failed", "expired", "cancelled"} and order["cart_id"] is not None:
            cart_id = CommerceService._active_cart_id(connection, order["user_id"])
            items = connection.execute(
                "SELECT product_id, quantity FROM order_items "
                "WHERE order_id = %s AND product_id IS NOT NULL",
                (order["id"],),
            ).fetchall()
            for item in items:
                connection.execute(
                    """
                    INSERT INTO cart_items (cart_id, product_id, quantity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (cart_id, product_id) DO UPDATE
                    SET quantity = GREATEST(cart_items.quantity, EXCLUDED.quantity),
                        updated_at = NOW()
                    """,
                    (cart_id, item["product_id"], item["quantity"]),
                )

    @staticmethod
    def _expire_unattached_orders(connection, user_id):
        stale_orders = connection.execute(
            """
            SELECT orders.* FROM orders
            WHERE orders.user_id = %s
              AND orders.status = 'pending_payment'
              AND orders.stock_reserved = TRUE
              AND orders.expires_at < NOW()
              AND NOT EXISTS (
                  SELECT 1 FROM payments
                  WHERE payments.order_id = orders.id
                    AND payments.stripe_session_id IS NOT NULL
              )
            FOR UPDATE
            """,
            (user_id,),
        ).fetchall()
        for order in stale_orders:
            connection.execute(
                "UPDATE payments SET status = 'expired', updated_at = NOW() "
                "WHERE order_id = %s AND status = 'pending'",
                (order["id"],),
            )
            CommerceService._release_reserved_stock(connection, order, "expired")


def amount_to_minor_units(amount, currency):
    zero_decimal = {
        "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg",
        "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
    }
    three_decimal = {"bhd", "jod", "kwd", "omr", "tnd"}
    exponent = 0 if currency in zero_decimal else 3 if currency in three_decimal else 2
    multiplier = Decimal(10) ** exponent
    minor_amount = amount * multiplier
    if minor_amount != minor_amount.to_integral_value():
        raise CommerceError(400, "A product price cannot be represented in the configured currency")
    result = int(minor_amount)
    if result < 0:
        raise CommerceError(400, "Amount cannot be negative")
    return result