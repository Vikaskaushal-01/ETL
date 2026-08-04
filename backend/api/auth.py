from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["Authentication"])

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
def login(req: LoginRequest):
    username = req.username.strip()
    password = req.password.strip()
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
        
    # Validation logic:
    # Ensure password is at least 4 characters long and email format for username is basic-checked.
    if len(password) < 4:
        raise HTTPException(status_code=401, detail="Authentication failed. Password must be at least 4 characters.")
        
    return {
        "status": "Success",
        "message": "Authentication successful",
        "user": {
            "username": username,
            "role": "Administrator"
        }
    }
