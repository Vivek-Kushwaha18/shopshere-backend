
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    # User ID
    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # User information
    full_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    email: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        nullable=False,
        index=True
    )

    phone: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True
    )

    # Authentication
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    is_email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    role: Mapped[str] = mapped_column(
        String(20),
        default="customer",
        nullable=False
    )

    auth_provider: Mapped[str] = mapped_column(
        String(20),
        default="email",
        nullable=False
    )

    # Forgot Password
    reset_token: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    reset_token_expires: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )
