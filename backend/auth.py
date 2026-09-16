import hashlib
import hmac
import json
import secrets
from pathlib import Path


class AuthService:
    """Stores users in their own JSON file and manages simple in-memory sessions."""

    def __init__(self):
        self.data_dir = Path(__file__).resolve().parent / "data"
        self.file_path = self.data_dir / "users.json"
        self.sessions = {}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save_users([])

    def signup(self, name, email, password):
        users = self._load_users()
        normalized_email = email.strip().lower()
        if any(user["email"] == normalized_email for user in users):
            raise ValueError("Email already registered")

        user = {
            "id": self._next_id(users),
            "name": name.strip(),
            "email": normalized_email,
            "password": self._hash_password(password),
            "role": "user",
        }
        users.append(user)
        self._save_users(users)
        return self._public_user(user)

    def login(self, email, password):
        normalized_email = email.strip().lower()
        user = next(
            (item for item in self._load_users() if item["email"] == normalized_email),
            None,
        )
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
        return next(
            (user for user in self._load_users() if user["id"] == user_id),
            None,
        )

    def _load_users(self):
        with self.file_path.open() as file:
            return json.load(file)

    def _save_users(self, users):
        with self.file_path.open("w") as file:
            json.dump(users, file, indent=4)

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

    @staticmethod
    def _next_id(users):
        return max((user["id"] for user in users), default=0) + 1
