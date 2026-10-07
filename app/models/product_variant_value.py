from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProductVariantValue(Base):
    __tablename__ = "product_variant_values"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    variant_id = Column(
        Integer,
        ForeignKey(
            "product_variants.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    option_value_id = Column(
        Integer,
        ForeignKey(
            "product_option_values.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    variant = relationship(
        "ProductVariant",
        back_populates="option_values",
    )

    option_value = relationship(
        "ProductOptionValue",
        back_populates="variant_values",
    )

    __table_args__ = (
        UniqueConstraint(
            "variant_id",
            "option_value_id",
            name="uq_variant_option_value",
        ),
    )