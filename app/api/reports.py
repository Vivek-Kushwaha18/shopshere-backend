from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin
from app.database.database import get_db

from app.models.category import Category
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User


router = APIRouter(
    prefix="/admin/reports",
    tags=["Admin Reports"],
)


# =========================================================
# ADMIN - REPORTS
# =========================================================

@router.get("/")
async def get_admin_reports(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    # -----------------------------------------------------
    # TOTAL USERS
    # -----------------------------------------------------

    customers_result = await db.execute(
        select(func.count(User.id)).where(
            User.role == "customer"
        )
    )

    total_customers = customers_result.scalar_one()

    sellers_result = await db.execute(
        select(func.count(User.id)).where(
            User.role == "seller"
        )
    )

    total_sellers = sellers_result.scalar_one()

    # -----------------------------------------------------
    # TOTAL PRODUCTS
    # -----------------------------------------------------

    products_result = await db.execute(
        select(func.count(Product.id)).where(
            Product.is_deleted.is_(False)
        )
    )

    total_products = products_result.scalar_one()

    # -----------------------------------------------------
    # TOTAL CATEGORIES
    # -----------------------------------------------------

    categories_result = await db.execute(
        select(func.count(Category.id)).where(
            Category.is_active.is_(True)
        )
    )

    total_categories = categories_result.scalar_one()

    # -----------------------------------------------------
    # ORDER STATUS COUNTS
    # -----------------------------------------------------

    status_result = await db.execute(
        select(
            Order.status,
            func.count(Order.id),
        )
        .group_by(Order.status)
    )

    status_rows = status_result.all()

    orders_by_status = {
        "pending": 0,
        "processing": 0,
        "shipped": 0,
        "delivered": 0,
        "cancelled": 0,
    }

    for order_status, count in status_rows:
        if order_status in orders_by_status:
            orders_by_status[order_status] = int(count)

    # -----------------------------------------------------
    # TOTAL ORDERS
    # -----------------------------------------------------

    total_orders_result = await db.execute(
        select(func.count(Order.id))
    )

    total_orders = total_orders_result.scalar_one()

    # -----------------------------------------------------
    # PAID ORDERS
    # -----------------------------------------------------

    paid_orders_result = await db.execute(
        select(func.count(Order.id)).where(
            Order.payment_status == "paid"
        )
    )

    paid_orders = paid_orders_result.scalar_one()

    # -----------------------------------------------------
    # TOTAL SALES
    #
    # Only paid orders are counted as sales.
    # -----------------------------------------------------

    sales_result = await db.execute(
        select(
            func.coalesce(
                func.sum(Order.total_amount),
                0,
            )
        ).where(
            Order.payment_status == "paid"
        )
    )

    total_sales = sales_result.scalar_one()

    # -----------------------------------------------------
    # TOTAL UNITS SOLD
    #
    # Only items belonging to paid orders are counted.
    # -----------------------------------------------------

    units_result = await db.execute(
        select(
            func.coalesce(
                func.sum(OrderItem.quantity),
                0,
            )
        )
        .join(
            Order,
            Order.id == OrderItem.order_id,
        )
        .where(
            Order.payment_status == "paid"
        )
    )

    total_units_sold = units_result.scalar_one()

    # -----------------------------------------------------
    # SALES BY DATE
    # -----------------------------------------------------

    sales_by_date_result = await db.execute(
        select(
            func.date(Order.created_at).label("date"),
            func.count(Order.id).label("orders"),
            func.coalesce(
                func.sum(Order.total_amount),
                0,
            ).label("sales"),
        )
        .where(
            Order.payment_status == "paid"
        )
        .group_by(
            func.date(Order.created_at)
        )
        .order_by(
            func.date(Order.created_at)
        )
    )

    sales_by_date_rows = sales_by_date_result.all()

    sales_by_date = [
        {
            "date": str(date),
            "orders": int(orders or 0),
            "sales": float(sales or 0),
        }
        for date, orders, sales in sales_by_date_rows
    ]

    # -----------------------------------------------------
    # TOP SELLING PRODUCTS
    # -----------------------------------------------------

    top_products_result = await db.execute(
        select(
            OrderItem.product_id,
            Product.name,
            func.sum(
                OrderItem.quantity
            ).label("units_sold"),
            func.sum(
                OrderItem.total
            ).label("sales"),
        )
        .join(
            Order,
            Order.id == OrderItem.order_id,
        )
        .join(
            Product,
            Product.id == OrderItem.product_id,
        )
        .where(
            Order.payment_status == "paid"
        )
        .group_by(
            OrderItem.product_id,
            Product.name,
        )
        .order_by(
            func.sum(
                OrderItem.quantity
            ).desc()
        )
        .limit(10)
    )

    top_products_rows = top_products_result.all()

    top_products = [
        {
            "product_id": product_id,
            "product_name": product_name,
            "units_sold": int(units_sold or 0),
            "sales": float(sales or 0),
        }
        for (
            product_id,
            product_name,
            units_sold,
            sales,
        ) in top_products_rows
    ]

    # -----------------------------------------------------
    # RESPONSE
    # -----------------------------------------------------

    return {
        "success": True,
        "message": "Admin reports fetched successfully.",
        "data": {
            "summary": {
                "total_sales": float(total_sales or 0),
                "total_orders": int(total_orders or 0),
                "paid_orders": int(paid_orders or 0),
                "total_units_sold": int(
                    total_units_sold or 0
                ),
                "total_customers": int(
                    total_customers or 0
                ),
                "total_sellers": int(
                    total_sellers or 0
                ),
                "total_products": int(
                    total_products or 0
                ),
                "total_categories": int(
                    total_categories or 0
                ),
            },
            "orders_by_status": orders_by_status,
            "sales_by_date": sales_by_date,
            "top_products": top_products,
        },
    }