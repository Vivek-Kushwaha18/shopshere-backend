from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProductOptionValue(Base):
    __tablename__ = "product_option_values"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    option_group_id = Column(
        Integer,
        ForeignKey(
            "product_option_groups.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    value = Column(
        String(100),
        nullable=False,
    )

    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
    )

    option_group = relationship(
        "ProductOptionGroup",
        back_populates="values",
    )

    variant_values = relationship(
        "ProductVariantValue",
        back_populates="option_value",
        cascade="all, delete-orphan",
    )