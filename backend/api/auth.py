import random
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.database.mysql import get_db
from backend.database.models import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

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

@router.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    password = req.password.strip()

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required.")

    if len(password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")

    # Check if user exists
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    # Create new user
    new_user = User(email=email, password=password)
    db.add(new_user)
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

    # Auto seed default admin if no users exist
    user_count = db.query(User).count()
    if user_count == 0:
        default_admin = User(email="admin@controlai.net", password="admin")
        db.add(default_admin)
        db.commit()

    user = db.query(User).filter(User.email == email).first()
    if not user or user.password != password:
        raise HTTPException(status_code=401, detail="Authentication failed. Invalid email or password.")

    return {
        "status": "Success",
        "message": "Authentication successful",
        "user": {
            "username": user.email,
            "role": "Administrator"
        }
    }

@router.post("/social-login")
def social_login(req: SocialLoginRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    provider = req.provider.strip()
    name = req.name.strip()

    if not email or not provider or not name:
        raise HTTPException(status_code=400, detail="Email, provider, and name are required.")

    # Check if user exists, if not, create one with random password
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # Create user with a dummy random password
        random_pass = "".join(random.choice("0123456789abcdef") for _ in range(12))
        user = User(email=email, password=random_pass)
        db.add(user)
        db.commit()

    return {
        "status": "Success",
        "message": f"Successfully authenticated via {provider}",
        "user": {
            "username": name,
            "email": email,
            "role": "Administrator"
        }
    }

@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()

    # If db is empty, make sure we seed admin so it can be tested
    user_count = db.query(User).count()
    if user_count == 0:
        default_admin = User(email="admin@controlai.net", password="admin")
        db.add(default_admin)
        db.commit()

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email address.")

    # Generate 6-digit random code
    code = "".join(random.choice("0123456789") for _ in range(6))
    user.reset_code = code
    db.commit()

    return {
        "status": "Success",
        "message": f"Verification code sent to {email}",
        "demo_code": code  # Developer helper code for testing
    }

@router.post("/verify-reset-code")
def verify_reset_code(req: VerifyResetCodeRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    code = req.code.strip()

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if not user.reset_code or user.reset_code != code:
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    return {
        "status": "Success",
        "message": "Verification code is valid"
    }

@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    code = req.code.strip()
    new_password = req.new_password.strip()

    if len(new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if not user.reset_code or user.reset_code != code:
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    # Update password and clear reset code
    user.password = new_password
    user.reset_code = None
    db.commit()

    return {
        "status": "Success",
        "message": "Password updated successfully"
    }
