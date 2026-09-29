from datetime import datetime, timedelta, timezone
import os

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from pwdlib import PasswordHash

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_reset_token,
    create_verification_code,
    decode_access_token,
    decode_refresh_token,
)

from app.database.database import get_db

from app.models.user import User

from app.schemas.auth import (
    AdminUserResponse,
    AdminUserUpdateRequest,
    ChangeEmailRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    SendVerificationCodeRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailChangeRequest,
    VerifyEmailRequest,
)

from app.services.email import send_email


# =========================================================
# ROUTER
# =========================================================

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# =========================================================
# PASSWORD SECURITY
# =========================================================

password_hash = PasswordHash.recommended()

security = HTTPBearer()


# =========================================================
# GET CURRENT USER
# =========================================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(
        security
    ),
    db: AsyncSession = Depends(get_db),
) -> User:

    token = credentials.credentials

    try:
        payload = decode_access_token(token)

        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token",
            )

        user_id = payload.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )

        user_id = int(user_id)

    except HTTPException:
        raise

    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    result = await db.execute(
        select(User).where(
            User.id == user_id
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return user


# =========================================================
# SIGNUP
# =========================================================

@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
)
async def signup(
    user_data: SignupRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):

    email = str(
        user_data.email
    ).strip().lower()

    # =====================================================
    # CHECK EXISTING USER
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.email == email
        )
    )

    existing_user = result.scalar_one_or_none()

    # =====================================================
    # EXISTING USER
    # =====================================================

    if existing_user:

        # -------------------------------------------------
        # ALREADY VERIFIED
        # -------------------------------------------------

        if existing_user.is_verified:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Email already registered and verified. "
                    "Please login."
                ),
            )

        # -------------------------------------------------
        # UNVERIFIED ACCOUNT
        # -------------------------------------------------

        password_is_correct = (
            password_hash.verify(
                user_data.password,
                existing_user.password_hash,
            )
        )

        if not password_is_correct:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "An unverified account already exists "
                    "with this email."
                ),
            )

        # -------------------------------------------------
        # UPDATE USER DATA
        # -------------------------------------------------

        existing_user.full_name = (
            user_data.full_name.strip()
        )

        existing_user.phone = (
            user_data.phone.strip()
            if user_data.phone
            else None
        )

        existing_user.role = user_data.role

        # -------------------------------------------------
        # GENERATE NEW OTP
        # -------------------------------------------------

        code = create_verification_code()

        code_expires = (
            datetime.now(timezone.utc)
            + timedelta(minutes=10)
        )

        existing_user.verification_code = code

        existing_user.verification_code_expires = (
            code_expires
        )

        await db.commit()
        await db.refresh(existing_user)

        # -------------------------------------------------
        # SEND OTP
        # -------------------------------------------------

        email_body = f"""
Hello {existing_user.full_name},

Your ShopSphere email verification code is:

{code}

This verification code will expire in 10 minutes.

If you did not request this verification code,
you can safely ignore this email.

Regards,
ShopSphere Team
"""

        background_tasks.add_task(
            send_email,
            existing_user.email,
            "ShopSphere - Email Verification Code",
            email_body,
        )

        return {
            "message": "Account created. Verification code sent.",
            "user": {
                "id": existing_user.id,
                "full_name": existing_user.full_name,
                "email": existing_user.email,
                "phone": existing_user.phone,
                "role": existing_user.role,
                "is_active": existing_user.is_active,
                "is_verified": existing_user.is_verified,
            },
        }

    # =====================================================
    # CREATE NEW USER
    # =====================================================

    hashed_password = password_hash.hash(
        user_data.password
    )

    user = User(
        full_name=user_data.full_name.strip(),
        email=email,
        phone=(
            user_data.phone.strip()
            if user_data.phone
            else None
        ),
        password_hash=hashed_password,
        role=user_data.role,
        is_active=True,
        is_verified=False,
    )

    db.add(user)

    await db.commit()
    await db.refresh(user)

    # =====================================================
    # GENERATE OTP
    # =====================================================

    code = create_verification_code()

    code_expires = (
        datetime.now(timezone.utc)
        + timedelta(minutes=10)
    )

    user.verification_code = code

    user.verification_code_expires = (
        code_expires
    )

    await db.commit()
    await db.refresh(user)

    # =====================================================
    # SEND OTP
    # =====================================================

    email_body = f"""
Hello {user.full_name},

Welcome to ShopSphere!

Your email verification code is:

{code}

This verification code will expire in 10 minutes.

If you did not create this ShopSphere account,
you can safely ignore this email.

Regards,
ShopSphere Team
"""

    background_tasks.add_task(
        send_email,
        user.email,
        "ShopSphere - Email Verification Code",
        email_body,
    )

    # =====================================================
    # SIGNUP RESPONSE
    # =====================================================

    return {
        "message": "Account created. Verification code sent.",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
        },
    }


# =========================================================
# SEND VERIFICATION CODE
# =========================================================

@router.post(
    "/send-verification-code",
)
async def send_verification_code(
    request: SendVerificationCodeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):

    email = str(
        request.email
    ).strip().lower()

    result = await db.execute(
        select(User).where(
            User.email == email
        )
    )

    user = result.scalar_one_or_none()

    # =====================================================
    # EMAIL NOT FOUND
    # =====================================================

    if user is None:

        return {
            "message": (
                "If the email is registered, "
                "a verification code has been sent."
            )
        }

    # =====================================================
    # ALREADY VERIFIED
    # =====================================================

    if user.is_verified:

        return {
            "message": "Email is already verified",
            "is_verified": True,
            "user": {
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "role": user.role,
                "is_active": user.is_active,
                "is_verified": user.is_verified,
            },
        }

    # =====================================================
    # GENERATE NEW OTP
    # =====================================================

    code = create_verification_code()

    code_expires = (
        datetime.now(timezone.utc)
        + timedelta(minutes=10)
    )

    user.verification_code = code

    user.verification_code_expires = (
        code_expires
    )

    await db.commit()

    # =====================================================
    # SEND OTP
    # =====================================================

    email_body = f"""
Hello {user.full_name},

Your ShopSphere email verification code is:

{code}

This verification code will expire in 10 minutes.

If you did not request this verification code,
you can safely ignore this email.

Regards,
ShopSphere Team
"""

    background_tasks.add_task(
        send_email,
        user.email,
        "ShopSphere - Email Verification Code",
        email_body,
    )

    return {
        "message": "Verification code sent",
        "is_verified": False,
    }


# =========================================================
# VERIFY EMAIL
# =========================================================

@router.post(
    "/verify-email",
)
async def verify_email(
    request: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):

    email = str(
        request.email
    ).strip().lower()

    # =====================================================
    # FIND USER
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.email == email
        )
    )

    user = result.scalar_one_or_none()

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid email or verification code"
            ),
        )

    # =====================================================
    # ALREADY VERIFIED
    # =====================================================

    if user.is_verified:

        return {
            "message": "Email is already verified",
            "is_verified": True,
            "user": {
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "role": user.role,
                "is_active": user.is_active,
                "is_verified": user.is_verified,
            },
        }

    # =====================================================
    # CHECK OTP EXISTS
    # =====================================================

    if user.verification_code is None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No verification code has been requested"
            ),
        )

    # =====================================================
    # CHECK OTP
    # =====================================================

    if (
        user.verification_code
        != request.code.strip()
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    # =====================================================
    # CHECK OTP EXPIRY
    # =====================================================

    expires_at = (
        user.verification_code_expires
    )

    if expires_at is None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired",
        )

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    now = datetime.now(timezone.utc)

    if expires_at < now:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired",
        )

    # =====================================================
    # VERIFY EMAIL
    # =====================================================

    user.is_verified = True

    user.verification_code = None

    user.verification_code_expires = None

    await db.commit()
    await db.refresh(user)

    # =====================================================
    # IMPORTANT
    #
    # Verification does NOT create tokens.
    #
    # User must login after verification.
    # =====================================================

    return {
        "message": "Email verified successfully",
        "is_verified": True,
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
        },
    }


# =========================================================
# LOGIN
# =========================================================

@router.post(
    "/login",
)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):

    email = str(
        login_data.email
    ).strip().lower()

    # =====================================================
    # FIND USER
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.email == email
        )
    )

    user = result.scalar_one_or_none()

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # =====================================================
    # CHECK PASSWORD
    # =====================================================

    password_is_correct = (
        password_hash.verify(
            login_data.password,
            user.password_hash,
        )
    )

    if not password_is_correct:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # =====================================================
    # CHECK ACTIVE
    # =====================================================

    if not user.is_active:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # =====================================================
    # CHECK EMAIL VERIFIED
    # =====================================================

    if user.is_verified is not True:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Please verify your email "
                "before logging in."
            ),
        )

    # =====================================================
    # CHECK ROLE
    # =====================================================

    if user.role not in {
        "customer",
        "seller",
        "admin",
    }:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user role",
        )

    # =====================================================
    # CREATE ACCESS TOKEN
    # =====================================================

    access_token = create_access_token(
        user.id,
        user.role,
    )

    # =====================================================
    # CREATE REFRESH TOKEN
    # =====================================================

    refresh_token = create_refresh_token(
        user.id,
        user.role,
    )

    # =====================================================
    # STORE REFRESH TOKEN
    # =====================================================

    user.refresh_token = refresh_token

    await db.commit()
    await db.refresh(user)

    # =====================================================
    # LOGIN RESPONSE
    # =====================================================

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
        },
    }


# =========================================================
# REFRESH TOKEN
# =========================================================

@router.post(
    "/refresh",
)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):

    token = request.refresh_token

    # =====================================================
    # DECODE REFRESH TOKEN
    # =====================================================

    try:

        payload = decode_refresh_token(
            token
        )

        user_id = payload.get("sub")

        if user_id is None:

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        user_id = int(user_id)

    except HTTPException:
        raise

    except (ValueError, TypeError):

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    except Exception:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid or expired refresh token"
            ),
        )

    # =====================================================
    # FIND USER
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.id == user_id
        )
    )

    user = result.scalar_one_or_none()

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # =====================================================
    # CHECK STORED REFRESH TOKEN
    # =====================================================

    if user.refresh_token != token:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid",
        )

    # =====================================================
    # CHECK ACTIVE
    # =====================================================

    if not user.is_active:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # =====================================================
    # CHECK VERIFIED
    # =====================================================

    if user.is_verified is not True:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email is not verified",
        )

    # =====================================================
    # CHECK ROLE
    # =====================================================

    if user.role not in {
        "customer",
        "seller",
        "admin",
    }:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user role",
        )

    # =====================================================
    # CREATE NEW ACCESS TOKEN
    # =====================================================

    new_access_token = create_access_token(
        user.id,
        user.role,
    )

    # =====================================================
    # CREATE NEW REFRESH TOKEN
    # =====================================================

    new_refresh_token = create_refresh_token(
        user.id,
        user.role,
    )

    # =====================================================
    # ROTATE REFRESH TOKEN
    # =====================================================

    user.refresh_token = (
        new_refresh_token
    )

    await db.commit()
    await db.refresh(user)

    # =====================================================
    # RESPONSE
    # =====================================================

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
        },
    }


# =========================================================
# FORGOT PASSWORD
# =========================================================

@router.post(
    "/forgot-password",
)
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):

    email = str(
        request.email
    ).strip().lower()

    # =====================================================
    # FIND USER
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.email == email
        )
    )

    user = result.scalar_one_or_none()

    # =====================================================
    # DO NOT REVEAL EMAIL EXISTENCE
    # =====================================================

    if user is None:

        return {
            "message": (
                "If the email exists, "
                "a password reset link has been sent."
            )
        }

    # =====================================================
    # CREATE RESET TOKEN
    # =====================================================

    reset_token = create_reset_token()

    reset_token_expires = (
        datetime.now(timezone.utc)
        + timedelta(minutes=15)
    )

    # =====================================================
    # STORE RESET TOKEN
    # =====================================================

    user.reset_token = reset_token

    user.reset_token_expires = (
        reset_token_expires
    )

    await db.commit()

    # =====================================================
    # FRONTEND URL
    # =====================================================

    frontend_url = os.getenv(
        "FRONTEND_URL"
    )

    if not frontend_url:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "FRONTEND_URL is not configured."
            ),
        )

    frontend_url = (
        frontend_url
        .strip()
        .rstrip("/")
    )

    # =====================================================
    # CREATE RESET LINK
    # =====================================================

    reset_link = (
        f"{frontend_url}"
        f"/reset-password"
        f"?token={reset_token}"
    )

    # =====================================================
    # SEND RESET EMAIL
    # =====================================================

    email_body = f"""
Hello {user.full_name},

We received a request to reset your ShopSphere password.

Click the link below to reset your password:

{reset_link}

This password reset link will expire in 15 minutes.

If you did not request a password reset,
you can safely ignore this email.

Regards,
ShopSphere Team
"""

    background_tasks.add_task(
        send_email,
        user.email,
        "ShopSphere - Password Reset",
        email_body,
    )

    # =====================================================
    # RESPONSE
    # =====================================================

    return {
        "message": (
            "If the email exists, "
            "a password reset link has been sent."
        )
    }


# =========================================================
# RESET PASSWORD
# =========================================================

@router.post(
    "/reset-password",
)
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):

    # =====================================================
    # CLEAN TOKEN
    # =====================================================

    reset_token = request.token.strip()

    if not reset_token:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token is missing",
        )

    # =====================================================
    # FIND USER
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.reset_token == reset_token
        )
    )

    user = result.scalar_one_or_none()

    # =====================================================
    # INVALID TOKEN
    # =====================================================

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token",
        )

    # =====================================================
    # CHECK TOKEN EXPIRY
    # =====================================================

    expires_at = (
        user.reset_token_expires
    )

    if expires_at is None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired",
        )

    # =====================================================
    # FIX TIMEZONE DIFFERENCE
    # =====================================================

    if expires_at.tzinfo is None:

        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    now = datetime.now(timezone.utc)

    # =====================================================
    # TOKEN EXPIRED
    # =====================================================

    if expires_at < now:

        user.reset_token = None

        user.reset_token_expires = None

        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired",
        )

    # =====================================================
    # UPDATE PASSWORD
    # =====================================================

    user.password_hash = password_hash.hash(
        request.new_password
    )

    # =====================================================
    # CLEAR RESET TOKEN
    # =====================================================

    user.reset_token = None

    user.reset_token_expires = None

    # =====================================================
    # INVALIDATE OLD REFRESH TOKEN
    # =====================================================

    user.refresh_token = None

    # =====================================================
    # SAVE CHANGES
    # =====================================================

    await db.commit()

    # =====================================================
    # RESPONSE
    # =====================================================

    return {
        "message": "Password reset successfully"
    }


# =========================================================
# GET MY PROFILE
# =========================================================

@router.get(
    "/me",
    response_model=ProfileResponse,
)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return {
        "full_name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone,
        "gender": current_user.gender,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "is_verified": current_user.is_verified,
    }


# =========================================================
# UPDATE MY PROFILE
#
# EMAIL IS NOT UPDATED HERE.
# PASSWORD IS NOT UPDATED HERE.
# =========================================================

@router.put(
    "/update-profile",
    response_model=ProfileResponse,
)
async def update_profile(
    profile_data: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    current_user.full_name = (
        profile_data.full_name.strip()
    )

    current_user.phone = (
        profile_data.phone.strip()
        if profile_data.phone
        else None
    )

    current_user.gender = (
        profile_data.gender
    )

    await db.commit()
    await db.refresh(current_user)

    return {
        "full_name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone,
        "gender": current_user.gender,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "is_verified": current_user.is_verified,
    }


# =========================================================
# REQUEST EMAIL CHANGE
#
# OTP IS SENT TO THE NEW EMAIL.
# =========================================================

@router.post(
    "/change-email",
)
async def change_email(
    request: ChangeEmailRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    new_email = str(
        request.new_email
    ).strip().lower()

    # =====================================================
    # SAME EMAIL
    # =====================================================

    if new_email == current_user.email.lower():

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New email is the same as your current email",
        )

    # =====================================================
    # CHECK EMAIL ALREADY EXISTS
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.email == new_email
        )
    )

    existing_user = result.scalar_one_or_none()

    if existing_user is not None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    # =====================================================
    # GENERATE EMAIL CHANGE OTP
    # =====================================================

    code = create_verification_code()

    code_expires = (
        datetime.now(timezone.utc)
        + timedelta(minutes=10)
    )

    current_user.pending_email = new_email

    current_user.email_change_code = code

    current_user.email_change_code_expires = (
        code_expires
    )

    await db.commit()

    # =====================================================
    # SEND OTP TO NEW EMAIL
    # =====================================================

    email_body = f"""
Hello {current_user.full_name},

You requested to change your ShopSphere account email.

Your email change verification code is:

{code}

This verification code will expire in 10 minutes.

If you did not request this email change,
you can safely ignore this email.

Regards,
ShopSphere Team
"""

    background_tasks.add_task(
        send_email,
        new_email,
        "ShopSphere - Email Change Verification Code",
        email_body,
    )

    return {
        "message": (
            "Verification code sent to your new email address"
        ),
        "pending_email": new_email,
    }


# =========================================================
# VERIFY EMAIL CHANGE
# =========================================================

@router.post(
    "/verify-email-change",
)
async def verify_email_change(
    request: VerifyEmailChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    # =====================================================
    # CHECK PENDING EMAIL
    # =====================================================

    if current_user.pending_email is None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No email change request found",
        )

    # =====================================================
    # CHECK OTP EXISTS
    # =====================================================

    if current_user.email_change_code is None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No email change verification code found",
        )

    # =====================================================
    # CHECK OTP
    # =====================================================

    if (
        current_user.email_change_code
        != request.code.strip()
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    # =====================================================
    # CHECK EXPIRY
    # =====================================================

    expires_at = (
        current_user.email_change_code_expires
    )

    if expires_at is None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired",
        )

    if expires_at.tzinfo is None:

        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    now = datetime.now(timezone.utc)

    if expires_at < now:

        current_user.pending_email = None

        current_user.email_change_code = None

        current_user.email_change_code_expires = None

        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired",
        )

    # =====================================================
    # CHECK THAT PENDING EMAIL IS STILL AVAILABLE
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.email == current_user.pending_email,
            User.id != current_user.id,
        )
    )

    existing_user = result.scalar_one_or_none()

    if existing_user is not None:

        current_user.pending_email = None

        current_user.email_change_code = None

        current_user.email_change_code_expires = None

        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    # =====================================================
    # CHANGE EMAIL
    # =====================================================

    current_user.email = current_user.pending_email

    current_user.pending_email = None

    current_user.email_change_code = None

    current_user.email_change_code_expires = None

    await db.commit()
    await db.refresh(current_user)

    # =====================================================
    # RESPONSE
    # =====================================================

    return {
        "message": "Email changed successfully",
        "email": current_user.email,
    }


# =========================================================
# ADMIN CHECK
# =========================================================

async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:

    if current_user.role != "admin":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return current_user


# =========================================================
# ADMIN - GET ALL USERS
# =========================================================

@router.get(
    "/admin/users",
    response_model=list[AdminUserResponse],
)
async def admin_get_users(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        select(User).order_by(
            User.id.asc()
        )
    )

    users = result.scalars().all()

    return [
        {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "gender": user.gender,
            "role": user.role,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
        }
        for user in users
    ]


# =========================================================
# ADMIN - GET SINGLE USER
# =========================================================

@router.get(
    "/admin/users/{user_id}",
    response_model=AdminUserResponse,
)
async def admin_get_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        select(User).where(
            User.id == user_id
        )
    )

    user = result.scalar_one_or_none()

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "gender": user.gender,
        "role": user.role,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
    }


# =========================================================
# ADMIN - UPDATE USER
#
# EMAIL AND PASSWORD ARE NOT UPDATED HERE.
# =========================================================

@router.patch(
    "/admin/users/{user_id}",
    response_model=AdminUserResponse,
)
async def admin_update_user(
    user_id: int,
    user_data: AdminUserUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):

    # =====================================================
    # FIND USER
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.id == user_id
        )
    )

    user = result.scalar_one_or_none()

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # =====================================================
    # PREVENT ADMIN FROM REMOVING OWN ADMIN ROLE
    # =====================================================

    if (
        user.id == current_user.id
        and user_data.role is not None
        and user_data.role != "admin"
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own admin role",
        )

    # =====================================================
    # PREVENT ADMIN FROM DEACTIVATING OWN ACCOUNT
    # =====================================================

    if (
        user.id == current_user.id
        and user_data.is_active is False
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )

    # =====================================================
    # UPDATE FULL NAME
    # =====================================================

    if user_data.full_name is not None:

        user.full_name = (
            user_data.full_name.strip()
        )

    # =====================================================
    # UPDATE PHONE
    # =====================================================

    if user_data.phone is not None:

        user.phone = (
            user_data.phone.strip()
            if user_data.phone
            else None
        )

    # =====================================================
    # UPDATE GENDER
    # =====================================================

    if user_data.gender is not None:

        user.gender = user_data.gender

    # =====================================================
    # UPDATE ROLE
    # =====================================================

    if user_data.role is not None:

        user.role = user_data.role

    # =====================================================
    # UPDATE ACTIVE STATUS
    # =====================================================

    if user_data.is_active is not None:

        user.is_active = user_data.is_active

        # -------------------------------------------------
        # Invalidate refresh token when deactivated
        # -------------------------------------------------

        if user.is_active is False:

            user.refresh_token = None

    await db.commit()
    await db.refresh(user)

    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "gender": user.gender,
        "role": user.role,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
    }


# =========================================================
# ADMIN - DELETE USER
# =========================================================

@router.delete(
    "/admin/users/{user_id}",
)
async def admin_delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):

    # =====================================================
    # PREVENT SELF DELETE
    # =====================================================

    if user_id == current_user.id:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own admin account",
        )

    # =====================================================
    # FIND USER
    # =====================================================

    result = await db.execute(
        select(User).where(
            User.id == user_id
        )
    )

    user = result.scalar_one_or_none()

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # =====================================================
    # PREVENT DELETING THE LAST ADMIN
    # =====================================================

    if user.role == "admin":

        admin_count_result = await db.execute(
            select(func.count(User.id)).where(
                User.role == "admin",
                User.is_active.is_(True),
            )
        )

        admin_count = (
            admin_count_result.scalar_one()
        )

        if admin_count <= 1:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last active admin",
            )

    # =====================================================
    # DELETE USER
    # =====================================================

    await db.delete(user)

    try:

        await db.commit()

    except Exception:

        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "User cannot be deleted because "
                "other records depend on this user"
            ),
        )

    # =====================================================
    # RESPONSE
    # =====================================================

    return {
        "message": "User deleted successfully",
        "user_id": user_id,
    }