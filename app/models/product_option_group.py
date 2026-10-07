from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class ProductOptionGroup(Base):
    __tablename__ = "product_option_groups"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    product_id = Column(
        Integer,
        ForeignKey(
            "products.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    name = Column(
        String(100),
        nullable=False,
    )

    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
    )

    product = relationship(
        "Product",
        back_populates="option_groups",
    )

    values = relationship(
        "ProductOptionValue",
        back_populates="option_group",
        cascade="all, delete-orphan",
        lazy="selectin",
    )