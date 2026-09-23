import os
import re
import secrets
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.database.mysql import get_db
from backend.database.models import User
from backend.core.security import (
    DEFAULT_ADMIN_EMAIL, create_token, hash_password, is_password_hashed,
    is_production, verify_password, verify_token
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 4
RESET_CODE_TTL_SECONDS = 15 * 60
MAX_RESET_ATTEMPTS = 5
# Social accounts are created with this marker instead of a password hash, so they can never
# be signed into with a password and a social login can never take over a password account.
SOCIAL_PASSWORD_MARKER = "!social:"


class LoginRequest(BaseModel):
    username: str
    password: str

class SignupRequest(BaseModel):
    email: str
    password: str

class SocialLoginRequest(BaseModel):
    provider: str
    email: str
    name: str

class ForgotPasswordRequest(BaseModel):
    email: str

class VerifyResetCodeRequest(BaseModel):
    email: str
    code: str

class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str


def seed_default_admin(db: Session):
    """Creates the default administrator account when the users table is empty."""
    if db.query(User).count() == 0:
        admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD") or "admin"
        db.add(User(email=DEFAULT_ADMIN_EMAIL, password=hash_password(admin_password)))
        db.commit()


def _session_payload(email: str, display_name: str = None) -> dict:
    return {
        "status": "Success",
        "message": "Authentication successful",
        "token": create_token(email),
        "user": {
            "username": email,
            "email": email,
            "display_name": display_name or email.split("@")[0],
            "role": "Administrator" if email == DEFAULT_ADMIN_EMAIL else "Data Engineer"
        }
    }


def _check_reset_code(db: Session, user: User, code: str) -> bool:
    """
    Reset codes are stored as '<code>:<expiry epoch>:<failed attempts>'. A code is invalidated
    after MAX_RESET_ATTEMPTS wrong guesses so the 6-digit space cannot be brute forced.
    """
    parts = (user.reset_code or "").split(":")
    if len(parts) != 3:
        return False
    stored_code, expiry, attempts = parts
    try:
        expired = time.time() > float(expiry)
        attempts = int(attempts)
    except ValueError:
        return False
    if expired or attempts >= MAX_RESET_ATTEMPTS:
        return False
    if secrets.compare_digest(stored_code, code):
        return True
    user.reset_code = f"{stored_code}:{expiry}:{attempts + 1}"
    db.commit()
    return False


@router.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    password = req.password.strip()

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required.")

    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    db.add(User(email=email, password=hash_password(password)))
    db.commit()

    return {
        "status": "Success",
        "message": "User registered successfully"
    }


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    email = req.username.strip().lower()
    password = req.password.strip()

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required.")

    seed_default_admin(db)

    user = db.query(User).filter(User.email == email).first()
    if not user or user.password.startswith(SOCIAL_PASSWORD_MARKER) or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Authentication failed. Invalid email or password.")

    # Transparently upgrade legacy plaintext passwords to salted hashes
    if not is_password_hashed(user.password):
        user.password = hash_password(password)
        db.commit()

    return _session_payload(user.email)


@router.post("/social-login")
def social_login(req: SocialLoginRequest, db: Session = Depends(get_db)):
    """
    Demo social sign-in. There is no real OAuth provider behind the UI, so this is disabled in
    production (ENV=production) unless ENABLE_DEMO_SOCIAL_LOGIN=true is set explicitly.
    """
    demo_enabled = (os.getenv("ENABLE_DEMO_SOCIAL_LOGIN") or ("false" if is_production() else "true")).lower() == "true"
    if not demo_enabled:
        raise HTTPException(status_code=403, detail="Social login is not enabled on this server.")

    email = req.email.strip().lower()
    provider = req.provider.strip().lower()
    name = req.name.strip()

    if not email or not provider or not name:
        raise HTTPException(status_code=400, detail="Email, provider, and name are required.")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, password=f"{SOCIAL_PASSWORD_MARKER}{provider}")
        db.add(user)
        db.commit()
    elif not is_password_hashed(user.password) and re.fullmatch(r"[0-9a-f]{12}", user.password or ""):
        # Legacy social accounts were stored with a random 12-hex plaintext password; migrate them.
        user.password = f"{SOCIAL_PASSWORD_MARKER}{provider}"
        db.commit()
    elif not user.password.startswith(SOCIAL_PASSWORD_MARKER):
        raise HTTPException(status_code=409, detail="An account with this email uses password sign-in. Please sign in with your password.")

    payload = _session_payload(email, display_name=name)
    payload["message"] = f"Successfully authenticated via {provider}"
    payload["user"]["username"] = name
    return payload


@router.get("/me")
def get_current_user(authorization: Optional[str] = Header(None)):
    token = authorization.split(" ", 1)[1] if authorization and authorization.lower().startswith("bearer ") else None
    email = verify_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return {"email": email, "role": "Administrator" if email == DEFAULT_ADMIN_EMAIL else "Data Engineer"}


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()

    seed_default_admin(db)

    user = db.query(User).filter(User.email == email).first()
    if not user or user.password.startswith(SOCIAL_PASSWORD_MARKER):
        raise HTTPException(status_code=404, detail="No account found with this email address.")

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    user.reset_code = f"{code}:{time.time() + RESET_CODE_TTL_SECONDS}:0"
    db.commit()

    response = {
        "status": "Success",
        "message": f"Verification code sent to {email}"
    }
    # No mail server is wired up, so the code is echoed back for local demos only.
    if not is_production():
        response["demo_code"] = code
    return response


@router.post("/verify-reset-code")
def verify_reset_code(req: VerifyResetCodeRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    code = req.code.strip()

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if not _check_reset_code(db, user, code):
        raise HTTPException(status_code=400, detail="Invalid or expired verification code.")

    return {
        "status": "Success",
        "message": "Verification code is valid"
    }


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    code = req.code.strip()
    new_password = req.new_password.strip()

    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if not _check_reset_code(db, user, code):
        raise HTTPException(status_code=400, detail="Invalid or expired verification code.")

    user.password = hash_password(new_password)
    user.reset_code = None
    db.commit()

    return {
        "status": "Success",
        "message": "Password updated successfully"
    }


# --- Account self-service (require a valid session token) ---

def require_session_email(authorization: Optional[str] = Header(None)) -> str:
    token = authorization.split(" ", 1)[1] if authorization and authorization.lower().startswith("bearer ") else None
    email = verify_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return email


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    date_of_birth: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ApiKeyCreateRequest(BaseModel):
    name: str
    environment: str = "Production"


def _get_user(db: Session, email: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.get("/profile")
def get_profile(email: str = Depends(require_session_email), db: Session = Depends(get_db)):
    user = _get_user(db, email)
    return {
        "email": user.email,
        "display_name": user.display_name or email.split("@")[0],
        "date_of_birth": user.date_of_birth,
        "role": "Administrator" if email == DEFAULT_ADMIN_EMAIL else "Data Engineer",
        "sign_in_method": "social" if user.password.startswith(SOCIAL_PASSWORD_MARKER) else "password",
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.put("/profile")
def update_profile(req: ProfileUpdateRequest, email: str = Depends(require_session_email), db: Session = Depends(get_db)):
    user = _get_user(db, email)
    if req.display_name is not None:
        name = req.display_name.strip()
        if not name or len(name) > 100:
            raise HTTPException(status_code=400, detail="Display name must be 1-100 characters.")
        user.display_name = name
    if req.date_of_birth is not None:
        dob = req.date_of_birth.strip()
        if dob and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob):
            raise HTTPException(status_code=400, detail="Date of birth must be YYYY-MM-DD.")
        user.date_of_birth = dob or None
    db.commit()
    return get_profile(email, db)


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, email: str = Depends(require_session_email), db: Session = Depends(get_db)):
    user = _get_user(db, email)
    if user.password.startswith(SOCIAL_PASSWORD_MARKER):
        raise HTTPException(status_code=400, detail="This account signs in through a social provider and has no password.")
    if not verify_password(req.current_password.strip(), user.password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    new_password = req.new_password.strip()
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    user.password = hash_password(new_password)
    db.commit()
    return {"status": "Success", "message": "Password updated successfully"}


def _serialize_key(key) -> dict:
    return {
        "id": key.id,
        "name": key.name,
        "environment": key.environment,
        "key_preview": f"{key.key_prefix}…",
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "request_count": key.request_count or 0,
    }


@router.get("/api-keys")
def list_api_keys(email: str = Depends(require_session_email), db: Session = Depends(get_db)):
    from backend.database.models import ApiKey
    keys = db.query(ApiKey).filter(ApiKey.user_email == email, ApiKey.revoked == False).order_by(ApiKey.created_at.desc()).all()  # noqa: E712
    return [_serialize_key(k) for k in keys]


@router.post("/api-keys")
def create_api_key(req: ApiKeyCreateRequest, email: str = Depends(require_session_email), db: Session = Depends(get_db)):
    """Creates a key. The full secret is returned only in this response; only its hash is stored."""
    from backend.database.models import ApiKey
    from backend.core.security import generate_api_key, hash_api_key
    name = req.name.strip()
    if not name or len(name) > 100:
        raise HTTPException(status_code=400, detail="Key name must be 1-100 characters.")
    if req.environment not in ("Production", "Staging", "Development"):
        raise HTTPException(status_code=400, detail="Environment must be Production, Staging or Development.")
    secret = generate_api_key()
    key = ApiKey(user_email=email, name=name, environment=req.environment, key_prefix=secret[:12], key_hash=hash_api_key(secret), request_count=0)
    db.add(key)
    db.commit()
    db.refresh(key)
    return {**_serialize_key(key), "secret": secret}


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, email: str = Depends(require_session_email), db: Session = Depends(get_db)):
    from backend.database.models import ApiKey
    key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.user_email == email).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found.")
    key.revoked = True
    db.commit()
    return {"status": "Success", "message": f"API key '{key.name}' revoked"}
