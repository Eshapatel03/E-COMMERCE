from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import re
import warnings
from io import BytesIO

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image
from PIL.Image import DecompressionBombError, DecompressionBombWarning
from PIL import UnidentifiedImageError
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
MAX_IMAGE_SIZE = 5 * 1024 * 1024
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
IMAGE_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}


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
    if product_service.has_duplicate(name, category):
        raise HTTPException(
            status_code=400,
            detail="A product with this name already exists in this category",
        )

    image_content, extension = await _read_validated_image(image)
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

    try:
        return product_service.add_product(product)
    except Exception:
        product_service.delete_product_image(image_path)
        raise


async def _validate_image(image: UploadFile):
    if not image.filename:
        raise HTTPException(status_code=400, detail="Product image cannot be empty")
    content, extension = await _read_validated_image(image)
    return product_service.save_product_image(
        f"{uuid4().hex}{extension}",
        content,
    )


async def _read_validated_image(image: UploadFile):
    if not image.filename:
        raise HTTPException(status_code=400, detail="Product image is required")
    if image.content_type not in IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Image must be a JPG, PNG, WEBP, or GIF file",
        )
    content = bytearray()
    while chunk := await image.read(64 * 1024):
        if len(content) + len(chunk) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="Product image must be 5 MB or smaller")
        content.extend(chunk)
    if not content:
        raise HTTPException(status_code=400, detail="Product image cannot be empty")
    actual_type = None
    if content.startswith(b"\xff\xd8\xff"):
        actual_type = "image/jpeg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        actual_type = "image/png"
    elif len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        actual_type = "image/webp"
    elif content.startswith((b"GIF87a", b"GIF89a")):
        actual_type = "image/gif"
    if actual_type != image.content_type:
        raise HTTPException(status_code=400, detail="Image content does not match its file type")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DecompressionBombWarning)
            with Image.open(BytesIO(content)) as decoded_image:
                if decoded_image.format != IMAGE_FORMATS[actual_type]:
                    raise HTTPException(status_code=400, detail="Invalid image file")
                decoded_image.verify()
    except (DecompressionBombError, DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Invalid image file") from error
    return bytes(content), IMAGE_EXTENSIONS[actual_type]


@app.put("/products/{product_id}")
async def edit_product(
    product_id: int,
    name: str = Form(...),
    category: str = Form(...),
    price: Decimal = Form(...),
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
    try:
        return product_service.update_product(
            product_id, name, category, price, stock, image_path
        )
    except Exception:
        if image_path:
            product_service.delete_product_image(image_path)
        raise


@app.delete("/products/{product_id}")
def remove_product(product_id: int, _admin=Depends(require_admin)):
    if product_service.delete_product(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted successfully"}