
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from pwdlib import PasswordHash

from app.database.database import get_db
from app.models.user import User

from app.schemas.auth import (
    SignupRequest,
    LoginRequest,
    ForgotPasswordRequest,
    UpdatePasswordRequest,
    ChangePasswordRequest,
)

from app.services.email import send_reset_password_email


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
    # Check role
    if data.role not in ["customer", "seller"]:
        return {
            "status": 400,
            "success": False,
            "data": None,
            "message": "Role is invalid"
        }

    # Check if email already exists
    # Role is NOT checked here.
    # Therefore one email can have only one account.
    result = await db.execute(
        select(User).where(User.email == data.email)
    )

    existing_user = result.scalar_one_or_none()

    if existing_user:
        return {
            "status": 400,
            "success": False,
            "data": None,
            "message": "You are already registered with this email."
        }

    # Hash password
    hashed_password = password_hash.hash(
        data.password
    )

    # Create user
    user = User(
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        password_hash=hashed_password,
        role=data.role
    )

    try:
        # Add user
        db.add(user)

        # Save user
        await db.commit()

        # Get generated ID
        await db.refresh(user)

    except IntegrityError:
        # Cancel failed transaction
        await db.rollback()

        # Database also protects the email with UNIQUE constraint
        return {
            "status": 400,
            "success": False,
            "data": None,
            "message": "You are already registered with this email."
        }

    return {
        "status": 201,
        "success": True,
        "data": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role
        },
        "message": "Signup successfully"
    }


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

    return {
        "status": 201,
        "success": True,
        "data": user,
        "message": "Login successfully"
    }


# =========================================================
# GET CURRENT USER
# =========================================================

@router.get("/me")
async def get_me(
    user_id: int,
    db: AsyncSession = Depends(get_db)
):
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
    }

    return {
        "status": 201,
        "success": True,
        "data": user,
        "message": "Me successfully"
    }


# =========================================================
# FORGOT PASSWORD
# =========================================================

@router.post("/forget")
async def create_forget(
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    # Find user by email
    result = await db.execute(
        select(User).where(
            User.email == data.email
        )
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # Generate secure token
    update_token = secrets.token_urlsafe(32)

    # Save token
    user.reset_token = update_token

    user.reset_token_expires = (
        datetime.utcnow() + timedelta(minutes=15)
    )

    await db.commit()

    # Send email
    await send_reset_password_email(
        recipient_email=user.email,
        reset_token=update_token
    )

    return {
        "status": 201,
        "success": True,
        "data": user,
        "message": "Forget successfully"
    }


# =========================================================
# UPDATE PASSWORD USING EMAIL TOKEN
# =========================================================

@router.post("/update-password")
async def update_password(
    data: UpdatePasswordRequest,
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
            detail="Invalid password update token"
        )

    # Check token expiration
    if not user.reset_token_expires:
        raise HTTPException(
            status_code=400,
            detail="Password update token has expired"
        )

    if user.reset_token_expires < datetime.utcnow():
        raise HTTPException(
            status_code=400,
            detail="Password update token has expired"
        )

    # Hash new password
    hashed_password = password_hash.hash(
        data.new_password
    )

    # Update password
    user.password_hash = hashed_password

    # Remove token after successful update
    user.reset_token = None
    user.reset_token_expires = None

    await db.commit()

    return {
        "status": 201,
        "success": True,
        "data": user,
        "message": "Update-password successfully"
    }


# =========================================================
# CHANGE PASSWORD AFTER LOGIN
# =========================================================

@router.post("/change-password")
async def change_password(
    user_id: int,
    data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    # Find logged-in user
    result = await db.execute(
        select(User).where(
            User.id == user_id
        )
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # Check current password
    password_is_correct = password_hash.verify(
        data.current_password,
        user.password_hash
    )

    if not password_is_correct:
        raise HTTPException(
            status_code=400,
            detail="Current password is incorrect"
        )

    # Check new password and confirm password
    if data.new_password != data.confirm_password:
        raise HTTPException(
            status_code=400,
            detail="New passwords do not match"
        )

    # Make sure new password is different
    if data.current_password == data.new_password:
        raise HTTPException(
            status_code=400,
            detail="New password must be different from current password"
        )

    # Hash new password
    user.password_hash = password_hash.hash(
        data.new_password
    )

    await db.commit()

    return {
        "status": 201,
        "success": True,
        "data": user,
        "message": "Change-password successfully"
    }
