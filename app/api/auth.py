from datetime import datetime, timedelta, timezone

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
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
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
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(
    user_data: SignupRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):

    email = str(user_data.email).strip().lower()

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
    # EXISTING UNVERIFIED ACCOUNT
    # =====================================================

    if existing_user:

        # Already verified
        if existing_user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered and verified. Please login.",
            )

        # Check password before allowing another OTP.
        password_is_correct = password_hash.verify(
            user_data.password,
            existing_user.password_hash,
        )

        if not password_is_correct:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An unverified account already exists with this email. Please use the correct password.",
            )

        # =================================================
        # GENERATE NEW OTP
        # =================================================

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

        # =================================================
        # SEND NEW OTP
        # =================================================

        email_body = f"""
Hello {existing_user.full_name},

Your ShopSphere email verification code is:

{code}

This verification code will expire in 10 minutes.

If you did not request this verification code, you can safely ignore this email.

Regards,
ShopSphere Team
"""

        background_tasks.add_task(
            send_email,
            existing_user.email,
            "ShopSphere - Email Verification Code",
            email_body,
        )

        # =================================================
        # CREATE NEW TOKENS
        # =================================================

        access_token = create_access_token(
            existing_user.id,
            existing_user.role,
        )

        refresh_token = create_refresh_token(
            existing_user.id,
            existing_user.role,
        )

        existing_user.refresh_token = refresh_token

        await db.commit()
        await db.refresh(existing_user)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": existing_user,
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

If you did not create this ShopSphere account, you can safely ignore this email.

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
    # CREATE TOKENS
    # =====================================================

    access_token = create_access_token(
        user.id,
        user.role,
    )

    refresh_token = create_refresh_token(
        user.id,
        user.role,
    )

    user.refresh_token = refresh_token

    await db.commit()
    await db.refresh(user)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user,
    }


# =========================================================
# LOGIN
# =========================================================

@router.post(
    "/login",
    response_model=TokenResponse,
)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):

    email = str(login_data.email).strip().lower()

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

    password_is_correct = password_hash.verify(
        login_data.password,
        user.password_hash,
    )

    if not password_is_correct:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # =====================================================
    # EMAIL VERIFICATION REQUIRED
    # =====================================================

    if user.is_verified is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )

    access_token = create_access_token(
        user.id,
        user.role,
    )

    refresh_token = create_refresh_token(
        user.id,
        user.role,
    )

    user.refresh_token = refresh_token

    await db.commit()
    await db.refresh(user)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user,
    }


# =========================================================
# GET PROFILE
# =========================================================

@router.get(
    "/profile",
    response_model=UserResponse,
)
async def get_profile(
    current_user: User = Depends(
        get_current_user
    ),
):
    return current_user


# =========================================================
# UPDATE PROFILE
# =========================================================

@router.put(
    "/profile",
    response_model=UserResponse,
)
async def update_profile(
    profile_data: ProfileUpdateRequest,
    current_user: User = Depends(
        get_current_user
    ),
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

    await db.commit()
    await db.refresh(current_user)

    return current_user


# =========================================================
# CHANGE PASSWORD
# =========================================================

# @router.post(
#     "/change-password",
# )
# async def change_password(
#     password_data: ChangePasswordRequest,
#     current_user: User = Depends(
#         get_current_user
#     ),
#     db: AsyncSession = Depends(get_db),
# ):

#     password_is_correct = password_hash.verify(
#         password_data.current_password,
#         current_user.password_hash,
#     )

#     if not password_is_correct:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Current password is incorrect",
#         )

#     if (
#         password_data.current_password
#         == password_data.new_password
#     ):
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="New password must be different",
#         )

#     current_user.password_hash = (
#         password_hash.hash(
#             password_data.new_password
#         )
#     )

#     current_user.refresh_token = None

#     await db.commit()

#     return {
#         "message": "Password changed successfully"
#     }


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

    email = str(request.email).strip().lower()

    result = await db.execute(
        select(User).where(
            User.email == email
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        return {
            "message": (
                "If the email exists, "
                "a password reset link has been sent."
            )
        }

    reset_token = create_reset_token()

    reset_token_expires = (
        datetime.now(timezone.utc)
        + timedelta(minutes=15)
    )

    user.reset_token = reset_token

    user.reset_token_expires = (
        reset_token_expires
    )

    await db.commit()

    import os

    frontend_url = os.getenv(
        "FRONTEND_URL",
        "http://localhost:3000",
    ).rstrip("/")

    reset_link = (
        f"{frontend_url}/reset-password"
        f"?token={reset_token}"
    )

    email_body = f"""
Hello {user.full_name},

We received a request to reset your ShopSphere password.

Click the link below to reset your password:

{reset_link}

This password reset link will expire in 15 minutes.

If you did not request a password reset, you can safely ignore this email.

Regards,
ShopSphere Team
"""

    background_tasks.add_task(
        send_email,
        user.email,
        "ShopSphere - Password Reset",
        email_body,
    )

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

    result = await db.execute(
        select(User).where(
            User.reset_token == request.token
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token",
        )

    if (
        user.reset_token_expires is None
        or user.reset_token_expires
        < datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired",
        )

    user.password_hash = password_hash.hash(
        request.new_password
    )

    user.reset_token = None
    user.reset_token_expires = None
    user.refresh_token = None

    await db.commit()

    return {
        "message": "Password reset successfully"
    }


# =========================================================
# SEND EMAIL VERIFICATION CODE
# =========================================================

@router.post(
    "/send-verification-code",
)
async def send_verification_code(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(get_db),
):

    if current_user.is_verified:
        return {
            "message": "Email is already verified",
            "is_verified": True,
        }

    code = create_verification_code()

    code_expires = (
        datetime.now(timezone.utc)
        + timedelta(minutes=10)
    )

    current_user.verification_code = code

    current_user.verification_code_expires = (
        code_expires
    )

    await db.commit()
    await db.refresh(current_user)

    email_body = f"""
Hello {current_user.full_name},

Your ShopSphere email verification code is:

{code}

This verification code will expire in 10 minutes.

If you did not request this verification code, you can safely ignore this email.

Regards,
ShopSphere Team
"""

    background_tasks.add_task(
        send_email,
        current_user.email,
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
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(get_db),
):

    if current_user.is_verified:
        return {
            "message": "Email is already verified",
            "is_verified": True,
        }

    if current_user.verification_code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code has been requested",
        )

    if (
        current_user.verification_code
        != request.code.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    if (
        current_user.verification_code_expires
        is None
        or current_user.verification_code_expires
        < datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired",
        )

    current_user.is_verified = True

    current_user.verification_code = None

    current_user.verification_code_expires = None

    await db.commit()
    await db.refresh(current_user)

    return {
        "message": "Email verified successfully",
        "is_verified": True,
    }


# =========================================================
# REFRESH TOKEN
# =========================================================

@router.post(
    "/refresh",
    response_model=TokenResponse,
)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):

    token = request.refresh_token

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
            detail="Invalid or expired refresh token",
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

    if user.refresh_token != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    new_access_token = create_access_token(
        user.id,
        user.role,
    )

    new_refresh_token = create_refresh_token(
        user.id,
        user.role,
    )

    user.refresh_token = new_refresh_token

    await db.commit()
    await db.refresh(user)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "user": user,
    }


# =========================================================
# LOGOUT
# =========================================================

@router.post(
    "/logout",
)
async def logout(
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(get_db),
):

    current_user.refresh_token = None

    await db.commit()

    return {
        "message": "Logged out successfully"
    }