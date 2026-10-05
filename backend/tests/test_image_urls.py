import pytest
from fastapi import HTTPException

from backend.main import _validate_image_url


def test_https_image_url_is_trimmed_and_preserved():
    assert (
        _validate_image_url("  https://images.example.com/products/item.webp  ")
        == "https://images.example.com/products/item.webp"
    )


@pytest.mark.parametrize(
    "image_url",
    [
        "http://images.example.com/item.jpg",
        "javascript:alert(1)",
        "data:image/png;base64,AA==",
        "https://user:password@images.example.com/item.jpg",
        "not-a-url",
        f"https://images.example.com/{'a' * 2040}",
    ],
)
def test_rejects_non_https_or_invalid_image_urls(image_url):
    with pytest.raises(HTTPException) as error:
        _validate_image_url(image_url)
    assert error.value.status_code == 400