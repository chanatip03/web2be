from fastapi import Response,APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from .dto import LoginRequest, Token
from .service import authenticate_admin
from app.core.security import create_access_token

router = APIRouter(prefix="/auth")

@router.post("/login/admin", response_model=Token)
def admin_login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    admin = authenticate_admin(db, data.email, data.password)
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_access_token({
        "sub": str(admin.id),
        "type": "admin"
    })

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=3600,   
        samesite="lax",
        secure=False   
    )
    return {"access_token": token}