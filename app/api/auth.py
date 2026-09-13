from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pwdlib import PasswordHash

from app.database.database import get_db
from app.models.user import User
from app.schemas.auth import (
    SignupRequest,
    LoginRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


password_hash = PasswordHash.recommended()


# =========================================================
# SIGNUP
# =========================================================

@router.post("/signup")
async def create_signup(
    data: SignupRequest,
    db: AsyncSession = Depends(get_db)
):

    # Check if email already exists
    result = await db.execute(
        select(User).where(User.email == data.email)
    )

    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    # Hash password
    hashed_password = password_hash.hash(data.password)

    # Create user
    user = User(
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        password_hash=hashed_password
    )

    # Add user
    db.add(user)

    # Save to PostgreSQL
    await db.commit()

    # Get generated ID
    await db.refresh(user)


    return {"status": 201, "success": True, "data": user, "message": "Signup  successfully"} 

# =========================================================
# LOGIN
# =========================================================

@router.post("/login")
async def create_login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db)
):

    # Find user by email
    result = await db.execute(
        select(User).where(User.email == data.email)
    )

    user = result.scalar_one_or_none()

    # User not found
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # Check password
    password_is_correct = password_hash.verify(
        data.password,
        user.password_hash
    )

    if not password_is_correct:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    return {"status": 200, "success": True, "data": user, "message": "Login successfully"} 
    


# =========================================================
# GET CURRENT USER
# =========================================================

@router.get("/me")
async def get_me(
    user_id: int,
    db: AsyncSession = Depends(get_db)
):

    # Find user by ID
    result = await db.execute(
        select(User).where(User.id == user_id)
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    user_data = {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "is_email_verified": user.is_email_verified
    }
    return {"status": 200, "success": True, "data": user_data, "message": "successfully"} 

# =========================================================
# FORGOT PASSWORD
# =========================================================

@router.post("/forget")
async def create_forget(
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
):

    # Find user
    result = await db.execute(
        select(User).where(User.email == data.email)
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # return {
    #   "message": "Password reset request received",
    #   "email": user.id
    # }

    return {"status": 200, "success": True, "data": {"token" : "sdsdc 3434"}, "message": "Email successfully Send "} 



# =========================================================
# RESET PASSWORD
# =========================================================

@router.post("/reset")
async def create_reset(
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):

    # Find user using reset token
    result = await db.execute(
        select(User).where(
            User.reset_token == data.token
        )
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=400,
            detail="Invalid reset token"
        )

    # Hash new password
    new_password_hash = password_hash.hash(
        data.new_password
    )

    # Update password
    user.password_hash = new_password_hash

    # Remove used reset token
    user.reset_token = None
    user.reset_token_expires = None

    await db.commit()

    return {"status": 200, "success": True, "data": {"token" : "sdsdc 3434"}, "message": "Password reset request received"} 