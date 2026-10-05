from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import re

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from backend.models import Product
from backend.config import get_settings
from backend.database import initialize_database
from backend.dependencies import auth_service, get_current_user, require_admin, extract_bearer_token
from backend.commerce import CommerceError
from backend.commerce_routes import router as commerce_router
from backend.services import ProductService
from backend.webhook_routes import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(commerce_router)
app.include_router(webhook_router)
app.mount(
    "/images",
    StaticFiles(directory=Path(__file__).resolve().parent / "data" / "images"),
    name="images",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().frontend_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)

product_service = ProductService()


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _validate_signup(request: SignupRequest):
    if not all(value.strip() for value in (
        request.name, request.email, request.password, request.confirm_password
    )):
        raise HTTPException(status_code=400, detail="All fields are required")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", request.email):
        raise HTTPException(status_code=400, detail="Please enter a valid email")
    if request.password != request.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    if len(request.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not re.search(r"[A-Z]", request.password):
        raise HTTPException(status_code=400, detail="Password must contain an uppercase letter")
    if not re.search(r"[a-z]", request.password):
        raise HTTPException(status_code=400, detail="Password must contain a lowercase letter")
    if not re.search(r"\d", request.password):
        raise HTTPException(status_code=400, detail="Password must contain a number")
    if not re.search(r"[^A-Za-z0-9]", request.password):
        raise HTTPException(status_code=400, detail="Password must contain a special character")


@app.post("/auth/signup", status_code=201)
def signup(request: SignupRequest):
    _validate_signup(request)
    try:
        return {"user": auth_service.signup(request.name, request.email, request.password)}
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/auth/login")
def login(request: LoginRequest):
    if not request.email.strip() or not request.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    try:
        return auth_service.login(request.email, request.password)
    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


@app.post("/auth/logout")
def logout(
    authorization: str | None = Header(default=None),
    _user=Depends(get_current_user),
):
    token = extract_bearer_token(authorization)
    auth_service.logout(token)
    return {"message": "Logged out successfully"}


@app.get("/auth/me")
def current_user(user=Depends(get_current_user)):
    return {"user": auth_service.public_user(user)}


@app.exception_handler(CommerceError)
async def commerce_error_handler(_, error: CommerceError):
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": error.detail},
    )


@app.get("/")
def home():
    return {"message": "Ecommerce API is running"}


@app.get("/products")
def get_products(
    keyword: str = None,
    category: str = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(8, ge=1, le=100),
):
    matching_products, total = product_service.search_products(
        keyword, category, page, page_size
    )
    return {
        "products": matching_products,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "categories": product_service.get_categories(),
    }


@app.get("/products/{product_id}")
def get_product(product_id: int):
    product = product_service.get_product_by_id(product_id)

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    return product


@app.post("/products")
async def add_product(
    name: str = Form(...),
    category: str = Form(...),
    price: Decimal = Form(...),
    stock: int = Form(...),
    image: str = Form(...),
    _admin=Depends(require_admin),
):
    name = name.strip()
    category = category.strip()

    if not name:
        raise HTTPException(status_code=400, detail="Product name cannot be empty")
    if not category:
        raise HTTPException(status_code=400, detail="Category cannot be empty")
    if price <= 0:
        raise HTTPException(status_code=400, detail="Price must be greater than 0")
    if stock < 0:
        raise HTTPException(status_code=400, detail="Stock cannot be negative")
    if product_service.has_duplicate(name, category):
        raise HTTPException(
            status_code=400,
            detail="A product with this name already exists in this category",
        )

    image_url = _validate_image_url(image)
    product = Product(
        id=0,
        name=name,
        category=category,
        price=price,
        stock=stock,
        image=image_url,
    )


def _validate_image_url(image: str):
    image_url = image.strip()
    parsed_url = urlparse(image_url)
    if (
        len(image_url) > 2048
        or parsed_url.scheme != "https"
        or not parsed_url.hostname
        or not parsed_url.netloc
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise HTTPException(status_code=400, detail="Image must be a valid HTTPS URL")
    return image_url


@app.put("/products/{product_id}")
async def edit_product(
    product_id: int,
    name: str = Form(...),
    category: str = Form(...),
    price: Decimal = Form(...),
    stock: int = Form(...),
    image: str | None = Form(None),
    _admin=Depends(require_admin),
):
    name, category = name.strip(), category.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Product name cannot be empty")
    if not category:
        raise HTTPException(status_code=400, detail="Category cannot be empty")
    if price <= 0:
        raise HTTPException(status_code=400, detail="Price must be greater than 0")
    if stock < 0:
        raise HTTPException(status_code=400, detail="Stock cannot be negative")
    if product_service.get_product_by_id(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product_service.has_duplicate(name, category, exclude_id=product_id):
        raise HTTPException(
            status_code=400,
            detail="A product with this name already exists in this category",
        )
    image_url = _validate_image_url(image) if image else None
    return product_service.update_product(
        product_id, name, category, price, stock, image_url
    )


@app.delete("/products/{product_id}")
def remove_product(product_id: int, _admin=Depends(require_admin)):
    if product_service.delete_product(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted successfully"}