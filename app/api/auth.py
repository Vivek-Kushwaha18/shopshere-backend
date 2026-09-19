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

from sqlalchemy import select
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
    ForgotPasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    SendVerificationCodeRequest,
    SignupRequest,
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
                "full_name": existing_user.full_name,
                "email": existing_user.email,
                "role": existing_user.role,
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
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
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
                "full_name": user.full_name,
                "email": user.email,
                "role": user.role,
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
                "full_name": user.full_name,
                "email": user.email,
                "role": user.role,
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

    if (
        user.verification_code_expires is None
        or user.verification_code_expires
        < datetime.now(timezone.utc)
    ):

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
    # NO ACCESS TOKEN
    # NO REFRESH TOKEN
    #
    # RETURN ONLY:
    # full_name
    # email
    # role
    # =====================================================

    return {
        "message": "Email verified successfully",
        "is_verified": True,
        "user": {
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
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
    #
    # LOGIN = REAL AUTHENTICATION
    #
    # TOKENS + USER INFO
    # =====================================================

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
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

        payload = decode_refresh_token(token)

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
    # CHECK EMAIL VERIFIED
    # =====================================================

    if user.is_verified is not True:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email is not verified",
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

    user.refresh_token = new_refresh_token

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
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
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
    # GET FRONTEND URL
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

    if (
        user.reset_token_expires is None
        or user.reset_token_expires
        < datetime.now(timezone.utc)
    ):

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