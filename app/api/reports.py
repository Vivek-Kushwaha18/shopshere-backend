
import csv
import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin
from app.database.database import get_db

from app.models.category import Category
from app.models.order import Order, OrderItem
from app.models.payment import Payment
from app.models.product import Product
from app.models.shipment import Shipment
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
    # TOTAL CUSTOMERS

    customers_result = await db.execute(
        select(func.count(User.id)).where(
            User.role == "customer"
        )
    )
    total_customers = customers_result.scalar_one()

    # TOTAL SELLERS

    sellers_result = await db.execute(
        select(func.count(User.id)).where(
            User.role == "seller"
        )
    )
    total_sellers = sellers_result.scalar_one()

    # TOTAL PRODUCTS

    products_result = await db.execute(
        select(func.count(Product.id)).where(
            Product.is_deleted.is_(False)
        )
    )
    total_products = products_result.scalar_one()

    # TOTAL CATEGORIES

    categories_result = await db.execute(
        select(func.count(Category.id)).where(
            Category.is_active.is_(True)
        )
    )
    total_categories = categories_result.scalar_one()

    # ORDER STATUS COUNTS

    status_result = await db.execute(
        select(
            Order.status,
            func.count(Order.id),
        ).group_by(Order.status)
    )

    orders_by_status = {
        "pending": 0,
        "processing": 0,
        "shipped": 0,
        "delivered": 0,
        "cancelled": 0,
    }

    for order_status, count in status_result.all():
        if order_status in orders_by_status:
            orders_by_status[order_status] = int(count)

    # TOTAL ORDERS

    total_orders_result = await db.execute(
        select(func.count(Order.id))
    )
    total_orders = total_orders_result.scalar_one()

    # PAID ORDERS

    paid_orders_result = await db.execute(
        select(func.count(Order.id)).where(
            Order.payment_status == "paid"
        )
    )
    paid_orders = paid_orders_result.scalar_one()

    # TOTAL SALES FROM PAID ORDERS

    sales_result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total_amount), 0)
        ).where(
            Order.payment_status == "paid"
        )
    )
    total_sales = sales_result.scalar_one()

    # UNITS SOLD IN PAID ORDERS

    units_result = await db.execute(
        select(
            func.coalesce(func.sum(OrderItem.quantity), 0)
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.payment_status == "paid")
    )
    total_units_sold = units_result.scalar_one()

    # SALES BY DATE

    sales_by_date_result = await db.execute(
        select(
            func.date(Order.created_at).label("date"),
            func.count(Order.id).label("orders"),
            func.coalesce(
                func.sum(Order.total_amount), 0
            ).label("sales"),
        )
        .where(Order.payment_status == "paid")
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at))
    )

    sales_by_date = [
        {
            "date": str(date),
            "orders": int(orders or 0),
            "sales": float(sales or 0),
        }
        for date, orders, sales in sales_by_date_result.all()
    ]

    # TOP SELLING PRODUCTS

    top_products_result = await db.execute(
        select(
            OrderItem.product_id,
            Product.name,
            func.sum(OrderItem.quantity).label("units_sold"),
            func.sum(OrderItem.total).label("sales"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Order.payment_status == "paid")
        .group_by(OrderItem.product_id, Product.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(10)
    )

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
        ) in top_products_result.all()
    ]

    return {
        "success": True,
        "message": "Admin reports fetched successfully.",
        "data": {
            "summary": {
                "total_sales": float(total_sales or 0),
                "total_orders": int(total_orders or 0),
                "paid_orders": int(paid_orders or 0),
                "total_units_sold": int(total_units_sold or 0),
                "total_customers": int(total_customers or 0),
                "total_sellers": int(total_sellers or 0),
                "total_products": int(total_products or 0),
                "total_categories": int(total_categories or 0),
            },
            "orders_by_status": orders_by_status,
            "sales_by_date": sales_by_date,
            "top_products": top_products,
        },
    }


# =========================================================
# ADMIN - EXPORT COMPLETE REPORT HISTORY AS ZIP
# =========================================================

@router.get("/export")
async def export_admin_reports(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    generated_at = datetime.now(timezone.utc).isoformat()

    # Exclude credentials and authentication secrets.
    excluded_user_fields = {
        "password_hash",
        "refresh_token",
        "reset_token",
        "reset_token_expires",
        "verification_code",
        "verification_code_expires",
        "pending_email",
        "email_change_code",
        "email_change_code_expires",
        "stripe_customer_id",
    }

    # Do not export payment signatures or gateway secrets.
    excluded_payment_fields = {
        "razorpay_signature",
    }

    datasets = [
        ("orders", Order, set()),
        ("order_items", OrderItem, set()),
        ("users", User, excluded_user_fields),
        ("products", Product, set()),
        ("categories", Category, set()),
        ("payments", Payment, excluded_payment_fields),
        ("shipments", Shipment, set()),
    ]

    record_counts = {}
    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:

        for dataset_name, model, excluded_fields in datasets:
            result = await db.scalars(
                select(model).order_by(model.id)
            )
            records = result.all()

            rows = []

            for record in records:
                row = {}

                for column in model.__table__.columns:
                    field_name = column.name

                    if field_name in excluded_fields:
                        continue

                    value = getattr(record, field_name)

                    if isinstance(value, datetime):
                        value = value.isoformat()

                    row[field_name] = value

                rows.append(row)

            # JSON export

            archive.writestr(
                f"data/{dataset_name}.json",
                json.dumps(
                    rows,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
            )

            # CSV export

            csv_buffer = io.StringIO(newline="")

            if rows:
                fieldnames = list(rows[0].keys())
                writer = csv.DictWriter(
                    csv_buffer,
                    fieldnames=fieldnames,
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(rows)
            else:
                csv_buffer.write("No records\n")

            archive.writestr(
                f"data/{dataset_name}.csv",
                csv_buffer.getvalue(),
            )

            record_counts[dataset_name] = len(rows)

        # Report summary

        paid_orders_result = await db.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
            ).where(Order.payment_status == "paid")
        )

        paid_orders_count, paid_sales = paid_orders_result.one()

        total_orders = await db.scalar(
            select(func.count(Order.id))
        )
        total_customers = await db.scalar(
            select(func.count(User.id)).where(
                User.role == "customer"
            )
        )
        total_sellers = await db.scalar(
            select(func.count(User.id)).where(
                User.role == "seller"
            )
        )
        total_products = await db.scalar(
            select(func.count(Product.id))
        )
        total_categories = await db.scalar(
            select(func.count(Category.id))
        )

        summary = {
            "generated_at": generated_at,
            "generated_by_admin_id": current_admin.id,
            "total_orders": int(total_orders or 0),
            "paid_orders": int(paid_orders_count or 0),
            "total_paid_sales": float(paid_sales or 0),
            "total_customers": int(total_customers or 0),
            "total_sellers": int(total_sellers or 0),
            "total_products": int(total_products or 0),
            "total_categories": int(total_categories or 0),
            "record_counts": record_counts,
        }

        archive.writestr(
            "report_summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2),
        )

        # README

        readme = f"""ShopSphere Admin Report Export
================================

Generated at: {generated_at}
Generated by admin ID: {current_admin.id}

Contents
--------

data/orders.csv and data/orders.json
data/order_items.csv and data/order_items.json
data/users.csv and data/users.json
data/products.csv and data/products.json
data/categories.csv and data/categories.json
data/payments.csv and data/payments.json
data/shipments.csv and data/shipments.json
report_summary.json

The data files contain records available in the database at export time.
CSV files are suitable for spreadsheet applications.
JSON files preserve structured record data.

Sensitive authentication fields and Razorpay signatures are excluded.
Payment gateway identifiers and transaction references may be included
for administrative reconciliation.

Record counts
-------------

{json.dumps(record_counts, indent=2)}
"""

        archive.writestr("README.txt", readme)

    buffer.seek(0)

    filename = (
        "shopsphere_admin_reports_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
    )

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
