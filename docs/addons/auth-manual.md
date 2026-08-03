# auth-manual

> **Template:** `fastapi` only  
> **Requires:** `sqlalchemy` addon

The `auth-manual` addon adds complete JWT-based authentication to a FastAPI project: registration, login, token refresh, logout, and a current-user endpoint. It is designed for projects that need authentication without relying on external identity providers.

---

## When to use it

Choose `auth-manual` when your FastAPI project needs:

- User registration and login with email/password
- JWT access tokens with configurable expiry
- Refresh token rotation for session management
- Protected routes with a reusable `CurrentUser` dependency
- SQLAlchemy models for users and refresh tokens

This addon is **only compatible with the `fastapi` template** because it depends on the database layer, settings injection points, and router registration system that the template provides.

---

## What it adds

### Files

| File | Purpose |
|---|---|
| `src/{{pkg_name}}/core/security.py` | Password hashing (bcrypt), JWT encode/decode, refresh token generation |
| `src/{{pkg_name}}/core/dependencies.py` | `get_current_user()` dependency and `CurrentUser` type alias |
| `src/{{pkg_name}}/models/user.py` | `User` model with email, hashed_password, is_active |
| `src/{{pkg_name}}/models/refresh_token.py` | `RefreshToken` model with token, expires_at, is_revoked |
| `src/{{pkg_name}}/schemas/auth.py` | Pydantic schemas: `UserRegister`, `UserLogin`, `TokenResponse`, `RefreshRequest`, `UserResponse` |
| `src/{{pkg_name}}/api/routes/auth.py` | Route handlers: `/register`, `/login`, `/refresh`, `/logout`, `/me` |
| `tests/integration/test_auth.py` | Integration tests for all auth endpoints |

### Database models

The `User` model includes:
- `id` - UUID primary key
- `email` - unique, indexed
- `hashed_password` - bcrypt hash
- `is_active` - boolean flag
- `refresh_tokens` - relationship to `RefreshToken` (cascade delete)

The `RefreshToken` model includes:
- `id` - UUID primary key
- `token` - unique string, indexed
- `expires_at` - datetime with timezone
- `is_revoked` - boolean flag
- `user_id` - foreign key to `users.id`

### Routes

| Method | Path | Description | Auth required |
|---|---|---|---|
| POST | `/auth/register` | Create a new user | No |
| POST | `/auth/login` | Login, receive access + refresh tokens | No |
| POST | `/auth/refresh` | Exchange refresh token for new pair | No |
| POST | `/auth/logout` | Revoke refresh token | Yes |
| GET | `/auth/me` | Get current user info | Yes |

### Settings fields

Injects into `settings_fields`:

```python
secret_key: str = "change-me-in-production"
algorithm: str = "HS256"
access_token_expire_minutes: int = 30
refresh_token_expire_days: int = 30
```

### Environment variables

| Key | Default | Description |
|---|---|---|
| `SECRET_KEY` | `change-me-run-openssl-rand-hex-32` | JWT signing key |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token lifetime |

### Dependencies

- `bcrypt` - password hashing
- `pyjwt[cryptography]` - JWT encoding/decoding
- `email-validator` - email validation
- `python-multipart` - form data parsing
- `python-dotenv` - `.env` file loading

### Requirements

- `sqlalchemy` addon - provides the database layer for user and refresh token models

### Just recipes

- `just gen-secret` - Generate a cryptographically secure secret key

### Router registration

Injects import and `include_router` call into `api/router.py`:

```python
from .routes.auth import router as auth_router
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
```

### Test fixtures

Injects into `tests/conftest.py`:

- `test_user` - creates a verified user in the test database
- `auth_client` - an `AsyncClient` pre-authenticated as `test_user`

### Exception classes

Injects `UnauthorizedError` (401) and `ForbiddenError` (403) into `exceptions.py`.

---

## Security considerations

- **Secret key:** The default `SECRET_KEY` is a placeholder. Run `just gen-secret` to generate a secure key and add it to `.env` before deploying.
- **Password hashing:** Uses bcrypt with a generated salt. Never store plaintext passwords.
- **Token rotation:** Refresh tokens are single-use. Each `/refresh` call revokes the old token and issues a new one.
- **Token expiry:** Access tokens expire quickly (30 minutes by default). Refresh tokens last longer (30 days).

---

## Post-installation steps

After adding the addon:

```bash
just migrate "add users"    # Create the users and refresh_tokens tables
just upgrade                # Apply the migration
just gen-secret             # Generate a SECRET_KEY and add it to .env
```

---

## Removing the addon

`zenit remove auth-manual` will:

- Delete all auth files (security.py, dependencies.py, models, schemas, routes, tests)
- Remove injected settings fields, router imports/includes, test fixtures, and exception classes
- Remove `bcrypt`, `pyjwt[cryptography]`, `email-validator`, `python-multipart`, and `python-dotenv` from `pyproject.toml`
- Remove env vars from `.env.example`
- Remove the `gen-secret` recipe from the justfile

The `users` and `refresh_tokens` tables will remain in your database. Drop them manually if no longer needed:

```bash
just migrate "drop auth tables"   # Or use a manual Alembic revision
```
