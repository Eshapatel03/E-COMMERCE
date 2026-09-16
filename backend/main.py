from pathlib import Path
from uuid import uuid4

import re

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from backend.models import Product
from backend.auth import AuthService
from backend.services import ProductService

app = FastAPI()
app.mount(
    "/images",
    StaticFiles(directory=Path(__file__).resolve().parent / "data" / "images"),
    name="images",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

product_service = ProductService()
auth_service = AuthService()


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


def _get_current_user(authorization: str | None = Header(default=None)):
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    user = auth_service.get_user_for_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in to continue")
    return user


def require_admin(user=Depends(_get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required")
    return user


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
def logout(authorization: str | None = Header(default=None)):
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    auth_service.logout(token)
    return {"message": "Logged out successfully"}


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
    matching_products = product_service.search_products(keyword, category)
    total = len(matching_products)
    start = (page - 1) * page_size
    return {
        "products": matching_products[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "categories": sorted({
            product.category for product in product_service.get_products()
        }),
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
    price: float = Form(...),
    stock: int = Form(...),
    image: UploadFile = File(...),
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
    if not image.filename:
        raise HTTPException(status_code=400, detail="Product image is required")
    if product_service.has_duplicate(name, category):
        raise HTTPException(
            status_code=400,
            detail="A product with this name already exists in this category",
        )

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if image.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Image must be a JPG, PNG, WEBP, or GIF file",
        )

    image_content = await image.read()
    if not image_content:
        raise HTTPException(status_code=400, detail="Product image cannot be empty")
    if len(image_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Product image must be 5 MB or smaller")

    extension = Path(image.filename).suffix.lower()
    filename = f"{uuid4().hex}{extension}"
    image_path = product_service.save_product_image(filename, image_content)
    product = Product(
        id=0,
        name=name,
        category=category,
        price=price,
        stock=stock,
        image=image_path,
    )

    return product_service.add_product(product)


async def _validate_image(image: UploadFile):
    if not image.filename:
        raise HTTPException(status_code=400, detail="Product image cannot be empty")
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if image.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Image must be a JPG, PNG, WEBP, or GIF file",
        )
    content = await image.read()
    if not content:
        raise HTTPException(status_code=400, detail="Product image cannot be empty")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Product image must be 5 MB or smaller")
    return product_service.save_product_image(
        f"{uuid4().hex}{Path(image.filename).suffix.lower()}",
        content,
    )


@app.put("/products/{product_id}")
async def edit_product(
    product_id: int,
    name: str = Form(...),
    category: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    image: UploadFile | None = File(None),
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
    image_path = await _validate_image(image) if image else None
    return product_service.update_product(
        product_id, name, category, price, stock, image_path
    )


@app.delete("/products/{product_id}")
def remove_product(product_id: int, _admin=Depends(require_admin)):
    if product_service.delete_product(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted successfully"}