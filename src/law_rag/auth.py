import base64
import contextlib
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

from .models import AuthSessionResponse, UserResponse

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _hash_password(password: str) -> str:
    salt_hex = secrets.token_hex(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt_hex),
        n=16384,
        r=8,
        p=1,
    )
    return f"{salt_hex}${derived.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, hash_hex = stored_hash.split("$", 1)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=16384,
            r=8,
            p=1,
        )
    except ValueError:
        return False
    return hmac.compare_digest(derived.hex(), hash_hex)


class AuthStore:
    def __init__(
        self,
        db_path: Path,
        secret_key: str,
        token_ttl_seconds: int = 86400,
    ) -> None:
        self.db_path = Path(db_path)
        self.secret_key = secret_key
        self.token_ttl_seconds = token_ttl_seconds
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with contextlib.closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _issue_token(self, user: UserResponse) -> str:
        payload = {
            "sub": user.id,
            "email": user.email,
            "exp": int(time.time()) + self.token_ttl_seconds,
        }
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).digest()
        sig_b64 = _b64url_encode(signature)
        return f"{payload_b64}.{sig_b64}"

    def register_user(self, email: str, password: str) -> AuthSessionResponse:
        normalized_email = email.strip().lower()
        if not EMAIL_PATTERN.match(normalized_email):
            raise AuthError(
                code="invalid_email",
                message="Please enter a valid email address.",
                status_code=400,
            )
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AuthError(
                code="weak_password",
                message=f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.",
                status_code=400,
            )

        password_hash = _hash_password(password)
        created_at = datetime.now(timezone.utc).isoformat()

        try:
            with contextlib.closing(self._connect()) as conn:
                cursor = conn.execute(
                    "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                    (normalized_email, password_hash, created_at),
                )
                conn.commit()
                user_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise AuthError(
                code="email_already_registered",
                message="An account with this email already exists.",
                status_code=409,
            ) from exc

        user = UserResponse(id=user_id, email=normalized_email)
        return AuthSessionResponse(token=self._issue_token(user), user=user)

    def authenticate_user(self, email: str, password: str) -> AuthSessionResponse:
        normalized_email = email.strip().lower()
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, email, password_hash FROM users WHERE email = ?",
                (normalized_email,),
            ).fetchone()

        if row is None or not _verify_password(password, row["password_hash"]):
            raise AuthError(
                code="invalid_credentials",
                message="Invalid email or password.",
                status_code=401,
            )

        user = UserResponse(id=int(row["id"]), email=str(row["email"]))
        return AuthSessionResponse(token=self._issue_token(user), user=user)

    def verify_token(self, token: str) -> UserResponse:
        try:
            payload_b64, sig_b64 = token.split(".", 1)
            expected_sig = hmac.new(
                self.secret_key.encode("utf-8"),
                payload_b64.encode("ascii"),
                hashlib.sha256,
            ).digest()
            actual_sig = _b64url_decode(sig_b64)
            if not hmac.compare_digest(expected_sig, actual_sig):
                raise ValueError("Signature mismatch")
            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
            user_id = int(payload["sub"])
            exp = int(payload["exp"])
        except Exception as exc:
            raise AuthError(
                code="authentication_required",
                message="Authentication is required. Please sign in.",
                status_code=401,
            ) from exc

        if exp <= int(time.time()):
            raise AuthError(
                code="authentication_required",
                message="Your session has expired. Please sign in again.",
                status_code=401,
            )

        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, email FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

        if row is None:
            raise AuthError(
                code="authentication_required",
                message="Authentication is required. Please sign in.",
                status_code=401,
            )

        return UserResponse(id=int(row["id"]), email=str(row["email"]))
