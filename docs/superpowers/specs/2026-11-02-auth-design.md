# Authentication (Login & Register) Design

Date: 2026-11-02

## Purpose

Add an email and password authentication system (Register, Login, Session Check, Logout) to the Contract Risk Review application so that only authenticated users can upload and analyze contracts.

## Scope & Goals

- **Access Control Gate**: Unauthenticated users cannot access the contract upload/analysis flow (`POST /api/v1/contracts/analyze`).
- **Email + Password Registration & Login**: Users register and sign in using only an email address and password (minimum 8 characters).
- **Zero External Infrastructure**: Use Python's built-in `sqlite3`, `hashlib.scrypt`, `hmac`, and `secrets` modules so `start.cmd` / `start.ps1` works out of the box without external databases or third-party auth libraries.

## Non-Goals

- Saving or listing per-user contract analysis history
- Password reset / email verification via SMTP
- Role-based access control (RBAC) or multi-tenant organizations
- OAuth / social login providers

---

## Architecture & Components

### 1. Configuration (`src/law_rag/config.py`)

Add authentication settings to `Settings`:
- `auth_db_path: Path = Field(default=Path("data/users.db"), validation_alias="AUTH_DB_PATH")`
- `auth_secret_key: str = Field(default="dev-local-auth-secret-change-in-prod", validation_alias="AUTH_SECRET_KEY")`
- `auth_token_ttl_seconds: int = Field(default=86400, validation_alias="AUTH_TOKEN_TTL_SECONDS")`

Update `.gitignore` to ignore `data/` and `*.db`.

### 2. Backend Auth Module (`src/law_rag/auth.py`)

#### Database Schema (`users` table)
```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

#### Password Hashing
- Normalize email via `email.strip().lower()`.
- Validate email format (must contain `@` and a domain part) and password length (`len(password) >= 8`).
- Hash passwords using `hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)` with a 16-byte random salt (`secrets.token_hex(16)`), stored as `<salt_hex>$<hash_hex>`.
- Verify passwords using `hmac.compare_digest`.

#### Stateless Signed Bearer Token
- Format: `<payload_b64url>.<signature_b64url>`
- Payload JSON: `{"sub": user_id, "email": email, "exp": int(time.time()) + ttl_seconds}`
- Signature: `hmac.new(secret.encode("utf-8"), payload_b64url.encode("ascii"), hashlib.sha256).digest()`
- Verification checks signature integrity with `hmac.compare_digest`, decodes payload, checks `exp > time.time()`, and confirms the user exists in SQLite.

### 3. API Endpoints (`src/law_rag/api.py`)

`create_app` signature updated to:
```python
def create_app(
    use_fake_clients: bool = False,
    frontend_dist: Path = FRONTEND_DIST,
    auth_db_path: Path | None = None,
) -> FastAPI:
```

#### Request & Response Models (`src/law_rag/models.py`)
- `AuthCredentialsRequest(BaseModel)`: `email: str`, `password: str`
- `UserResponse(BaseModel)`: `id: int`, `email: str`
- `AuthSessionResponse(BaseModel)`: `token: str`, `user: UserResponse`

#### Routes
1. `POST /api/v1/auth/register` (`status_code=201`, `response_model=AuthSessionResponse`)
   - Validates email format (`400`, `code="invalid_email"`) and password length >= 8 (`400`, `code="weak_password"`).
   - Inserts user into SQLite; if email exists, raises `409` (`code="email_already_registered"`).
   - Returns signed Bearer token and user object.
2. `POST /api/v1/auth/login` (`status_code=200`, `response_model=AuthSessionResponse`)
   - Verifies email and password against SQLite; on failure raises `401` (`code="invalid_credentials"`).
   - Returns signed Bearer token and user object.
3. `GET /api/v1/auth/me` (`status_code=200`, `response_model=UserResponse`)
   - Extracts `Authorization: Bearer <token>` header.
   - If missing, invalid, expired, or user not found, raises `401` (`code="authentication_required"`).
   - Returns `UserResponse`.
4. `POST /api/v1/contracts/analyze` (`response_model=ContractReport`)
   - Protected by `Depends(require_current_user)`.
   - Returns `401` (`code="authentication_required"`) if no valid Bearer token is provided.

---

### 4. Frontend Architecture

#### API Client & Token Storage (`frontend/src/api.ts` & `frontend/src/types.ts`)
- Types added to `frontend/src/types.ts`:
  - `AuthUser`: `{ id: number; email: string }`
  - `AuthSession`: `{ token: string; user: AuthUser }`
- Token storage helpers in `frontend/src/api.ts`:
  - `TOKEN_STORAGE_KEY = "law_rag_auth_token"`
  - `getStoredToken()`, `setStoredToken(token)`, `clearStoredToken()`
- Auth API functions:
  - `registerUser(email: string, password: string): Promise<AuthSession>`
  - `loginUser(email: string, password: string): Promise<AuthSession>`
  - `fetchCurrentUser(): Promise<AuthUser>`
- `analyzeContract` reads `getStoredToken()` and attaches `Authorization: Bearer <token>`. If the server responds with `401`, it calls `clearStoredToken()` and throws an `AuthenticationError` (subclass of `AnalysisError`) so `App.tsx` resets the session state.

#### UI Components (`frontend/src/components/AuthPanel.tsx` & `frontend/src/App.tsx`)
- `AuthPanel.tsx`:
  - Mode toggle between `"login"` ("Sign in") and `"register"` ("Create account").
  - Controlled inputs for Email and Password, displaying validation or server errors via `<p className="alert" role="alert">`.
  - Calls `onAuthenticated(session: AuthSession)` upon success.
- `App.tsx`:
  - Tracks `user: AuthUser | null` and `authChecking: boolean` (initial check when a stored token exists on mount).
  - When `user === null`, renders `<AuthPanel onAuthenticated={...} />` and `<SourcePlate />` inside `.landing`.
  - When `user !== null`, shows the user's email and a `Sign out` button in `.top-nav-actions`, and renders the contract upload/analysis workflow.

---

## Testing Strategy

1. **Backend Unit & API Tests (`tests/test_auth.py` and `tests/test_api.py`)**:
   - `tests/test_auth.py`: Tests registration (`201`), duplicate email (`409`), invalid email (`400`), short password (`400`), login success (`200`), wrong password (`401`), `/api/v1/auth/me` with valid/invalid/missing token (`200`/`401`), and `/api/v1/contracts/analyze` rejecting unauthenticated requests (`401`).
   - `tests/test_api.py`: Updated helper `post_contract` uses `tmp_path` SQLite DB and registers a test user token so existing contract analysis API tests continue to pass in isolation.
2. **Frontend Unit Tests (`frontend/src/api.test.ts` and `frontend/src/components/AuthPanel.test.tsx`)**:
   - `api.test.ts`: Tests `loginUser`, `registerUser`, `Authorization` header injection in `analyzeContract`, and token clearing on `401`.
   - `AuthPanel.test.tsx`: Tests mode switching between Sign in and Create account, form submission, and error alert rendering.
