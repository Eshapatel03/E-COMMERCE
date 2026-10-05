from fastapi import Depends, Header, HTTPException

from backend.auth import AuthService


auth_service = AuthService()


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Please log in to continue")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="Please log in to continue")
    return token.strip()


def get_current_user(authorization: str | None = Header(default=None)):
    token = extract_bearer_token(authorization)
    user = auth_service.get_user_for_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in to continue")
    return user


def require_admin(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required")
    return user