
import logging
import os
import secrets
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

from google.auth.exceptions import TransportError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from pwdlib import PasswordHash

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
    GoogleLoginRequest,
    LoginRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    SendVerificationCodeRequest,
    SignupRequest,
    VerifyEmailChangeRequest,
    VerifyEmailRequest,
)

from app.services.email import send_email


# =========================================================
# LOGGER
# =========================================================

logger = logging.getLogger(__name__)


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
# SHARED AUTH RESPONSE
# =========================================================

def build_auth_response(
    user: User,
    access_token: str,
    refresh_token: str,
):
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "gender": user.gender,
            "role": user.role,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
        },
    }


# =========================================================
# SHARED EMAIL VERIFICATION HELPERS
# =========================================================

def set_verification_code(user: User) -> str:
    code = create_verification_code()

    user.verification_code = code
    user.verification_code_expires = (
        datetime.now(timezone.utc) + timedelta(minutes=10)
    )

    return code


def build_verification_email(
    full_name: str,
    code: str,
) -> str:
    return f"""
Hello {full_name},

Your ShopSphere email verification code is:

{code}

This verification code will expire in 10 minutes.

If you did not request this verification code,
you can safely ignore this email.

Regards,
ShopSphere Team
"""


def queue_verification_email(
    background_tasks: BackgroundTasks,
    email: str,
    full_name: str,
    code: str,
):
    background_tasks.add_task(
        send_email,
        email,
        "ShopSphere - Email Verification Code",
        build_verification_email(full_name, code),
    )


def verification_expired(expires_at) -> bool:
    if expires_at is None:
        return True

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return expires_at < datetime.now(timezone.utc)


# =========================================================
# GET CURRENT USER
# =========================================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)

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
        select(User).where(User.id == user_id)
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
# SIGNUP WITH EMAIL AND PASSWORD
# =========================================================

@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    user_data: SignupRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = str(user_data.email).strip().lower()

    result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        if existing_user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Email already registered and verified. "
                    "Please login."
                ),
            )

        password_is_correct = password_hash.verify(
            user_data.password,
            existing_user.password_hash,
        )

        if not password_is_correct:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "An unverified account already exists with "
                    "this email."
                ),
            )

        existing_user.full_name = user_data.full_name.strip()
        existing_user.phone = (
            user_data.phone.strip() if user_data.phone else None
        )
        existing_user.role = user_data.role

        code = set_verification_code(existing_user)

        await db.commit()
        await db.refresh(existing_user)

        queue_verification_email(
            background_tasks,
            existing_user.email,
            existing_user.full_name,
            code,
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

    user = User(
        full_name=user_data.full_name.strip(),
        email=email,
        phone=user_data.phone.strip() if user_data.phone else None,
        password_hash=password_hash.hash(user_data.password),
        role=user_data.role,
        is_active=True,
        is_verified=False,
    )

    code = set_verification_code(user)

    db.add(user)

    try:
        await db.commit()
        await db.refresh(user)

    except IntegrityError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An account with this email already exists. "
                "Please try logging in."
            ),
        )

    queue_verification_email(
        background_tasks,
        user.email,
        user.full_name,
        code,
    )

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
# SEND VERIFICATION CODE FOR NORMAL SIGNUP
# =========================================================

@router.post("/send-verification-code")
async def send_verification_code(
    request: SendVerificationCodeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = str(request.email).strip().lower()

    result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    user = result.scalar_one_or_none()

    if user is None:
        return {
            "message": (
                "If the email is registered, "
                "a verification code has been sent."
            )
        }

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

    code = set_verification_code(user)

    await db.commit()

    queue_verification_email(
        background_tasks,
        user.email,
        user.full_name,
        code,
    )

    return {
        "message": "Verification code sent",
        "is_verified": False,
    }


# =========================================================
# VERIFY EMAIL FOR NORMAL SIGNUP
# =========================================================

@router.post("/verify-email")
async def verify_email(
    request: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    email = str(request.email).strip().lower()

    result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or verification code",
        )

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

    if user.verification_code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code has been requested",
        )

    if user.verification_code != request.code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    if verification_expired(user.verification_code_expires):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired",
        )

    user.is_verified = True
    user.verification_code = None
    user.verification_code_expires = None

    await db.commit()
    await db.refresh(user)

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
# LOGIN WITH EMAIL AND PASSWORD
# =========================================================

@router.post("/login")
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    email = str(login_data.email).strip().lower()

    result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not password_hash.verify(
        login_data.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    if user.is_verified is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )

    if user.role not in {"customer", "seller", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user role",
        )

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id, user.role)

    user.refresh_token = refresh_token

    await db.commit()
    await db.refresh(user)

    return build_auth_response(user, access_token, refresh_token)


# =========================================================
# GOOGLE LOGIN / SIGNUP
# POST /auth/google
# =========================================================

@router.post("/google")
async def google_login(
    request: GoogleLoginRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()

    if not client_id:
        logger.error(
            "Google login failed: GOOGLE_CLIENT_ID is not configured."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google authentication is not configured on the server.",
        )

    credential = request.credential.strip()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google credential is missing.",
        )

    try:
        claims = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience=client_id,
        )

    except TransportError:
        logger.exception(
            "Google token verification service is unavailable."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Google authentication is temporarily unavailable. "
                "Please try again."
            ),
        )

    except ValueError as exc:
        logger.warning(
            "Google ID token verification failed: %s",
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Google rejected the login credential. Check that the "
                "frontend and backend use the same Google Web Client ID "
                "and that the credential has not expired."
            ),
        )

    except Exception:
        logger.exception(
            "Unexpected error while verifying Google credential."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed. Please try again.",
        )

    google_email = claims.get("email")

    if (
        not isinstance(google_email, str)
        or claims.get("email_verified") is not True
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google must provide a verified email address.",
        )

    email = google_email.strip().lower()

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google did not provide a valid email address.",
        )

    result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    user = result.scalar_one_or_none()

    # Existing verified users can log in directly.
    if user is not None and user.is_verified:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        if user.role not in {"customer", "seller", "admin"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid user role.",
            )

        access_token = create_access_token(user.id, user.role)
        refresh_token = create_refresh_token(user.id, user.role)

        user.refresh_token = refresh_token

        await db.commit()
        await db.refresh(user)

        return build_auth_response(
            user,
            access_token,
            refresh_token,
        )

    # Create a new Google account as an unverified customer.
    if user is None:
        full_name = claims.get("name")

        if not isinstance(full_name, str) or not full_name.strip():
            full_name = email.split("@", 1)[0]

        user = User(
            full_name=full_name.strip()[:100],
            email=email,
            phone=None,
            password_hash=password_hash.hash(
                secrets.token_urlsafe(48)
            ),
            role="customer",
            is_active=True,
            is_verified=False,
        )

        db.add(user)

        try:
            await db.flush()

        except IntegrityError:
            await db.rollback()

            # Handle a concurrent registration for the same email.
            result = await db.execute(
                select(User).where(func.lower(User.email) == email)
            )
            user = result.scalar_one_or_none()

            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Unable to create your account. "
                        "Please try again."
                    ),
                )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    if user.role not in {"customer", "seller", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user role.",
        )

    # Do not issue tokens to an unverified account.
    if not user.is_verified:
        code = set_verification_code(user)

        try:
            await db.commit()
            await db.refresh(user)

        except Exception:
            await db.rollback()
            logger.exception(
                "Failed to save Google signup verification code."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Unable to start Google email verification. "
                    "Please try again."
                ),
            )

        queue_verification_email(
            background_tasks,
            user.email,
            user.full_name,
            code,
        )

        return {
            "success": True,
            "requires_otp": True,
            "email": user.email,
            "message": (
                "A verification code has been sent to your email. "
                "Verify it to complete Google signup."
            ),
        }

    # This branch handles an account verified during a concurrent request.
    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id, user.role)

    user.refresh_token = refresh_token

    await db.commit()
    await db.refresh(user)

    return build_auth_response(
        user,
        access_token,
        refresh_token,
    )


# =========================================================
# VERIFY GOOGLE SIGNUP OTP
# POST /auth/google/verify-otp
# =========================================================

@router.post("/google/verify-otp")
async def verify_google_otp(
    request: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    email = str(request.email).strip().lower()

    result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or verification code.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    if user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already verified. Please log in.",
        )

    if user.verification_code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code has been requested.",
        )

    if user.verification_code != request.code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code.",
        )

    if verification_expired(user.verification_code_expires):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired. Please request a new one.",
        )

    if user.role not in {"customer", "seller", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user role.",
        )

    user.is_verified = True
    user.verification_code = None
    user.verification_code_expires = None

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id, user.role)

    user.refresh_token = refresh_token

    try:
        await db.commit()
        await db.refresh(user)

    except Exception:
        await db.rollback()
        logger.exception(
            "Failed to complete Google OTP verification."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to complete verification. Please try again.",
        )

    response = build_auth_response(
        user,
        access_token,
        refresh_token,
    )
    response["message"] = "Google signup verified successfully."

    return response


# =========================================================
# RESEND GOOGLE SIGNUP OTP
# POST /auth/google/resend-otp
# =========================================================

@router.post("/google/resend-otp")
async def resend_google_otp(
    request: SendVerificationCodeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = str(request.email).strip().lower()

    result = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    user = result.scalar_one_or_none()

    if user is None:
        return {
            "message": (
                "If the email has an unverified account, "
                "a verification code has been sent."
            )
        }

    if user.is_verified:
        return {
            "message": "Email is already verified.",
            "is_verified": True,
        }

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    code = set_verification_code(user)

    await db.commit()

    queue_verification_email(
        background_tasks,
        user.email,
        user.full_name,
        code,
    )

    return {
        "success": True,
        "message": "Verification code sent.",
        "is_verified": False,
    }


# =========================================================
# REFRESH TOKEN
# =========================================================

@router.post("/refresh")
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
        select(User).where(User.id == user_id)
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

    if user.is_verified is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email is not verified",
        )

    if user.role not in {"customer", "seller", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user role",
        )

    new_access_token = create_access_token(user.id, user.role)
    new_refresh_token = create_refresh_token(user.id, user.role)

    user.refresh_token = new_refresh_token

    await db.commit()
    await db.refresh(user)

    return build_auth_response(
        user,
        new_access_token,
        new_refresh_token,
    )


# =========================================================
# FORGOT PASSWORD
# =========================================================

@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = str(request.email).strip().lower()

    result = await db.execute(
        select(User).where(func.lower(User.email) == email)
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
    user.reset_token = reset_token
    user.reset_token_expires = (
        datetime.now(timezone.utc) + timedelta(minutes=15)
    )

    await db.commit()

    frontend_url = os.getenv("FRONTEND_URL")

    if not frontend_url:
        logger.error("FRONTEND_URL is not configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FRONTEND_URL is not configured.",
        )

    frontend_url = frontend_url.strip().rstrip("/")
    reset_link = f"{frontend_url}/reset-password?token={reset_token}"

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

    return {
        "message": (
            "If the email exists, "
            "a password reset link has been sent."
        )
    }


# =========================================================
# RESET PASSWORD
# =========================================================

@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    reset_token = request.token.strip()

    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token is missing",
        )

    result = await db.execute(
        select(User).where(User.reset_token == reset_token)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token",
        )

    expires_at = user.reset_token_expires

    if expires_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired",
        )

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        user.reset_token = None
        user.reset_token_expires = None
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired",
        )

    user.password_hash = password_hash.hash(request.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    user.refresh_token = None

    await db.commit()

    return {"message": "Password reset successfully"}


# =========================================================
# GET MY PROFILE
# =========================================================

@router.get("/me", response_model=ProfileResponse)
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
# =========================================================

@router.put("/update-profile", response_model=ProfileResponse)
async def update_profile(
    profile_data: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user.full_name = profile_data.full_name.strip()
    current_user.phone = (
        profile_data.phone.strip() if profile_data.phone else None
    )
    current_user.gender = profile_data.gender

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
# =========================================================

@router.post("/change-email")
async def change_email(
    request: ChangeEmailRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    new_email = str(request.new_email).strip().lower()

    if new_email == current_user.email.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New email is the same as your current email",
        )

    result = await db.execute(
        select(User).where(func.lower(User.email) == new_email)
    )
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    code = create_verification_code()
    current_user.pending_email = new_email
    current_user.email_change_code = code
    current_user.email_change_code_expires = (
        datetime.now(timezone.utc) + timedelta(minutes=10)
    )

    await db.commit()

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
        "message": "Verification code sent to your new email address",
        "pending_email": new_email,
    }


# =========================================================
# VERIFY EMAIL CHANGE
# =========================================================

@router.post("/verify-email-change")
async def verify_email_change(
    request: VerifyEmailChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.pending_email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No email change request found",
        )

    if current_user.email_change_code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No email change verification code found",
        )

    if current_user.email_change_code != request.code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    expires_at = current_user.email_change_code_expires

    if expires_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired",
        )

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        current_user.pending_email = None
        current_user.email_change_code = None
        current_user.email_change_code_expires = None

        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired",
        )

    result = await db.execute(
        select(User).where(
            func.lower(User.email) == current_user.pending_email.lower(),
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

    current_user.email = current_user.pending_email
    current_user.pending_email = None
    current_user.email_change_code = None
    current_user.email_change_code_expires = None

    await db.commit()
    await db.refresh(current_user)

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

@router.get("/admin/users", response_model=list[AdminUserResponse])
async def admin_get_users(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).order_by(User.id.asc())
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
        select(User).where(User.id == user_id)
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
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if (
        user.id == current_user.id
        and user_data.role is not None
        and user_data.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own admin role",
        )

    if user.id == current_user.id and user_data.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )

    if user_data.full_name is not None:
        user.full_name = user_data.full_name.strip()

    if user_data.phone is not None:
        user.phone = user_data.phone.strip() if user_data.phone else None

    if user_data.gender is not None:
        user.gender = user_data.gender

    if user_data.role is not None:
        user.role = user_data.role

    if user_data.is_active is not None:
        user.is_active = user_data.is_active

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

@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own admin account",
        )

    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.role == "admin":
        admin_count_result = await db.execute(
            select(func.count(User.id)).where(
                User.role == "admin",
                User.is_active.is_(True),
            )
        )
        admin_count = admin_count_result.scalar_one()

        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last active admin",
            )

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

    return {
        "message": "User deleted successfully",
        "user_id": user_id,
    }
