from sqlalchemy import Column, Integer, ForeignKey, Float, String, Boolean
from app.models.base import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    quantity = Column(Integer, nullable=False)

    total_price = Column(Float, nullable=False)

    status = Column(String, default="pending")

    is_deleted = Column(
        Boolean,
        default=False,
        nullable=False
    )