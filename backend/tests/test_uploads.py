import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import Headers, UploadFile

from backend.main import _read_validated_image


def make_upload(content, content_type="image/png", filename="upload.png"):
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_upload_accepts_decodable_image_and_uses_detected_extension():
    image = BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, format="PNG")
    content = image.getvalue()
    result, extension = asyncio.run(
        _read_validated_image(make_upload(content, filename="misleading.jpg"))
    )
    assert result == content
    assert extension == ".png"


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"\x89PNG\r\n\x1a\ndata", "image/png"),
        (b"not an image", "image/jpeg"),
    ],
)
def test_upload_rejects_forged_or_mismatched_image(content, content_type):
    with pytest.raises(HTTPException) as error:
        asyncio.run(_read_validated_image(make_upload(content, content_type)))
    assert error.value.status_code == 400


def test_upload_rejects_files_over_size_limit():
    oversized = b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024)
    with pytest.raises(HTTPException) as error:
        asyncio.run(_read_validated_image(make_upload(oversized)))
    assert error.value.status_code == 400