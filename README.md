# Lumora Ecommerce

FastAPI + PostgreSQL backend and React/Vite storefront. PostgreSQL is the source of truth for accounts, catalog data, carts, orders, inventory, and payments. Product image URLs are stored in PostgreSQL; image files are loaded directly by the browser from their HTTPS hosts.

## Structure

```text
backend/
	migrations/       Versioned PostgreSQL migrations
	tests/             Database-free auth, API, payment, and upload tests
	commerce.py        Cart, order, inventory, and payment state operations
	commerce_routes.py Cart, checkout, and customer order APIs
	config.py          Environment configuration
	database.py        Psycopg connections and migration runner
	dependencies.py    Bearer authentication and admin authorization
	services.py        Product service
	webhook_routes.py  Stripe webhook verification
frontend/src/
	App.jsx            Storefront, account, cart, checkout, and order history
```

## Database Model

- `users` own sessions, carts, and orders. A user deletion cascades to sessions/carts but is restricted while order history exists.
- `products` are referenced by cart items. Removing a product removes it from carts; order items keep a nullable product reference and immutable name, category, image path, unit-price, quantity, and line-total snapshots.
- `carts` have one active cart per user; `cart_items` enforce positive quantities and one row per product per cart.
- `orders` store status, currency, totals, idempotency key, shipping-address snapshot, and inventory-reservation state. `payments` store Stripe session/PaymentIntent identifiers and payment status, not card data.
- `stripe_webhook_events` uses Stripe event IDs as a primary key for duplicate-delivery protection.

Money uses PostgreSQL `NUMERIC`, never floating-point database types. Product categories remain text because there is no category metadata or administration requirement yet. Saved address books, billing-address records, and a separate category table are not currently needed.

Migrations are in `backend/migrations/` and run transactionally at application startup. The existing `users` and `products` tables are retained and extended additively. The migration runner serializes concurrent application starts.

## Configuration

Copy the examples, then fill in values locally. `.env` files are ignored by Git.

```powershell
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env
```

Backend settings:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string; required to start the API |
| `FRONTEND_ORIGINS` | Comma-separated exact browser origins allowed by CORS |
| `SESSION_TTL_HOURS` | Expiration time for opaque bearer sessions |
| `STRIPE_SECRET_KEY` | Server-side Stripe test/live secret key |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for Stripe webhook verification |
| `STRIPE_PUBLISHABLE_KEY` | Reserved for a future Stripe.js flow; hosted Checkout does not use it |
| `STRIPE_CURRENCY` | Three-letter currency; keep `usd` while the storefront displays dollars |
| `STRIPE_ALLOWED_COUNTRIES` | Countries Stripe Checkout may collect shipping addresses for |
| `STRIPE_SUCCESS_URL` | Return URL; retain `{CHECKOUT_SESSION_ID}` for status lookup |
| `STRIPE_CANCEL_URL` | Return URL after leaving hosted Checkout |

Never commit `.env`, API keys, webhook secrets, or database credentials. Use separate Stripe test and live keys and webhook secrets. Do not expose the secret key through a `VITE_` variable.

## Local Development

Create a PostgreSQL database and put its connection string in the root `.env`. Install and run the backend from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

The examples above use the project virtual environment; if it does not exist, create it first with `python -m venv .venv`.

Run the frontend in a second terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

For Stripe testing, use test-mode credentials and forward events to `http://localhost:8000/webhooks/stripe` with the Stripe CLI. Put the CLI-provided webhook signing secret in the root `.env`. Checkout remains disabled unless both the Stripe secret key and webhook signing secret are configured.

## Authentication and Checkout

Signup validates email/password fields and stores salted PBKDF2-SHA256 hashes. Login returns the existing `{token, user}` shape. The bearer token is a cryptographically random opaque value; PostgreSQL stores only its SHA-256 digest with creation, expiry, and revocation timestamps. `/auth/me` validates the current token. Admin product mutations continue to require the `admin` role on the backend.

The frontend loads and changes the cart through authenticated APIs. At checkout, the backend reads current products and prices, locks inventory rows, creates the order and immutable line-item snapshots, reserves stock, and commits before requesting a hosted Stripe Checkout Session. An idempotency key protects retries. The browser receives only the hosted Checkout URL and never supplies an authoritative price, total, user ID, or payment status.

For a product image, use an HTTPS URL from a host that permits direct image embedding (for example, an image URL provided by your approved image host). Paste that URL in the admin product form. The URL string is stored in PostgreSQL; the image itself is fetched directly by each visitor's browser and is not copied to this application's disk. Verify image licensing and host terms. Existing `data/images/...` records are still served for backwards compatibility until their products are changed to remote URLs.

Stripe webhooks are verified against the raw request body and `Stripe-Signature`. Successful payment events update an order only after matching the server-calculated amount and currency. Failed/expired/cancelled flows use guarded state changes and restore reserved stock once. Event IDs prevent duplicate webhook delivery from applying changes twice. A Checkout return URL is not treated as proof of payment; the frontend queries the authenticated order API.

## API

- `POST /auth/signup`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `GET /products`, `GET /products/{product_id}`; admin-only `POST /products`, `PUT /products/{product_id}`, `DELETE /products/{product_id}`
- Authenticated cart: `GET /cart`, `POST /cart/items`, `PATCH /cart/items/{product_id}`, `DELETE /cart/items/{product_id}`
- Authenticated checkout: `POST /checkout/session`, `GET /checkout/session/{session_id}`
- Authenticated orders: `GET /orders`, `GET /orders/{public_id}`, `POST /orders/{public_id}/cancel`
- Stripe-only callback: `POST /webhooks/stripe`

Errors use FastAPI's `detail` response shape. Order queries are scoped to the authenticated user. Product reads remain public and product writes retain server-side admin authorization.

## Tests

Install test dependencies with `pip install -r requirements-dev.txt`, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests
Set-Location frontend
npm run lint
npm run build
```

The current automated suite does not require PostgreSQL or Stripe credentials. It covers auth/authorization checks, API access scoping, signed/invalid webhook requests, money conversion, PostgreSQL migration syntax, and image URL validation. It does not replace database-backed concurrency/transaction tests or an end-to-end Stripe test-mode purchase.

## Deployment Boundaries

This is a stronger internship/local application, not yet production-certified. Before deployment:

- Provide HTTPS, production-only CORS origins, secret management, PostgreSQL backups, and a migration release process. Startup migrations currently require DDL permissions.
- Use image URLs from a trusted HTTPS image host and ensure you have permission to use those images. Existing legacy `/images/...` paths may still be served, but new product changes do not save image files locally.
- Add database-backed integration tests, webhook monitoring/reconciliation, and an operational recovery path for payments whose events cannot be applied.
- Add rate limiting, login abuse controls, email verification, password recovery, and a secure admin-provisioning process.
- Browser bearer tokens remain in `localStorage`; this is vulnerable to token theft if an XSS flaw is introduced. Consider an HttpOnly/Secure cookie design with CSRF controls for a public deployment.
- Taxes and shipping charges are not calculated, and there are no fulfillment/refund administration endpoints. The schema reserves statuses for later fulfillment/refund work.
- Configure the storefront's currency formatting together with `STRIPE_CURRENCY` before using a non-USD currency.
