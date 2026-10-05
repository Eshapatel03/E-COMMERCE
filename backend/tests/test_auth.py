import pytest
from fastapi import HTTPException

from backend.auth import AuthService
from backend.dependencies import extract_bearer_token, require_admin
from backend.main import SignupRequest, _validate_signup


def test_password_hash_is_salted_and_verifiable():
    first_hash = AuthService._hash_password("StrongPassword9!")
    second_hash = AuthService._hash_password("StrongPassword9!")
    assert first_hash != second_hash
    assert AuthService._verify_password("StrongPassword9!", first_hash)
    assert not AuthService._verify_password("incorrect", first_hash)


def test_session_token_is_stored_as_a_digest():
    token = "random-session-token"
    digest = AuthService._hash_token(token)
    assert digest != token
    assert len(digest) == 64
    assert AuthService._hash_token(token) == digest


def test_bearer_token_is_normalized_and_malformed_headers_rejected():
    assert extract_bearer_token("bEaReR token-value") == "token-value"
    for header in (None, "Basic token-value", "Bearer "):
        with pytest.raises(HTTPException) as error:
            extract_bearer_token(header)
        assert error.value.status_code == 401


def test_admin_dependency_rejects_regular_user():
    with pytest.raises(HTTPException) as error:
        require_admin({"role": "user"})
    assert error.value.status_code == 403
    assert require_admin({"role": "admin"})["role"] == "admin"


def test_signup_enforces_password_confirmation_and_strength():
    valid = SignupRequest(
        name="Customer",
        email="customer@example.com",
        password="StrongPassword9!",
        confirm_password="StrongPassword9!",
    )
    _validate_signup(valid)
    invalid = valid.model_copy(update={"confirm_password": "different"})
    with pytest.raises(HTTPException) as error:
        _validate_signup(invalid)
    assert error.value.status_code == 400