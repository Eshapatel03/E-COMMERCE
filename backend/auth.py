import hashlib
import hmac
import secrets

import psycopg

from backend.database import get_connection


class AuthService:

    def __init__(self):
        self.sessions = {}

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
        return self._public_user(user)

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
        self.sessions[token] = user["id"]
        return {"token": token, "user": self._public_user(user)}

    def logout(self, token):
        self.sessions.pop(token, None)

    def get_user_for_token(self, token):
        if not token:
            return None
        user_id = self.sessions.get(token)
        if user_id is None:
            return None
        with get_connection() as connection:
            return connection.execute(
                "SELECT id, name, email, password, role FROM users WHERE id = %s",
                (user_id,),
            ).fetchone()

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
    def _public_user(user):
        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
        }

