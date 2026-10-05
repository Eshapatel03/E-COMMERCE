import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import psycopg

from backend.database import get_connection
from backend.config import get_settings


class AuthService:

    def __init__(self):
        self.session_ttl = timedelta(hours=get_settings().session_ttl_hours)

    def signup(self, name, email, password):
        normalized_email = email.strip().lower()
        try:
            with get_connection() as connection:
                user = connection.execute(
                    """
                    INSERT INTO users (name, email, password, role)
                    VALUES (%s, %s, %s, 'user')
                    RETURNING id, name, email, password, role
                    """,
                    (
                        name.strip(),
                        normalized_email,
                        self._hash_password(password),
                    ),
                ).fetchone()
        except psycopg.errors.UniqueViolation as error:
            raise ValueError("Email already registered") from error
        return self.public_user(user)

    def login(self, email, password):
        normalized_email = email.strip().lower()
        with get_connection() as connection:
            user = connection.execute(
                "SELECT id, name, email, password, role FROM users WHERE email = %s",
                (normalized_email,),
            ).fetchone()
        if user is None or not self._verify_password(password, user["password"]):
            raise ValueError("Invalid email or password")
        if user.get("role") not in {"user", "admin"}:
            raise ValueError("This account has an invalid role")

        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        expires_at = datetime.now(timezone.utc) + self.session_ttl
        with get_connection() as connection:
            connection.execute(
                "DELETE FROM user_sessions WHERE expires_at <= NOW() "
                "OR revoked_at < NOW() - INTERVAL '30 days'"
            )
            connection.execute(
                "INSERT INTO user_sessions (user_id, token_hash, expires_at) "
                "VALUES (%s, %s, %s)",
                (user["id"], token_hash, expires_at),
            )
        return {"token": token, "user": self.public_user(user)}

    def logout(self, token):
        if not token:
            return
        with get_connection() as connection:
            connection.execute(
                "UPDATE user_sessions SET revoked_at = NOW() "
                "WHERE token_hash = %s AND revoked_at IS NULL",
                (self._hash_token(token),),
            )

    def get_user_for_token(self, token):
        if not token:
            return None
        token_hash = self._hash_token(token)
        with get_connection() as connection:
            return connection.execute(
                """
                SELECT users.id, users.name, users.email, users.role
                FROM user_sessions
                JOIN users ON users.id = user_sessions.user_id
                WHERE user_sessions.token_hash = %s
                  AND user_sessions.revoked_at IS NULL
                  AND user_sessions.expires_at > NOW()
                """,
                (token_hash,),
            ).fetchone()

    @staticmethod
    def _hash_token(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_password(password):
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, 600_000
        )
        return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"

    @staticmethod
    def _verify_password(password, stored_password):
        try:
            algorithm, iterations, salt, expected_digest = stored_password.split("$")
            if algorithm != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode(),
                bytes.fromhex(salt),
                int(iterations),
            ).hex()
            return hmac.compare_digest(digest, expected_digest)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def public_user(user):
        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
        }

