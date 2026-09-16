from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import get_db
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate


router = APIRouter(
    prefix="/products",
    tags=["Products"]
)


# CREATE PRODUCT
@router.post("/")
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db)
):

    product = Product(
        name=data.name,
        description=data.description,
        price=data.price,
        quantity=data.quantity,
        category=data.category,
        image_url=data.image_url
    )

    db.add(product)

    await db.commit()
    await db.refresh(product)

    return {
        "message": "Product created successfully",
        "product": {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "price": product.price,
            "quantity": product.quantity,
            "category": product.category,
            "image_url": product.image_url
        }
    }


# GET ALL PRODUCTS
@router.get("/")
async def get_products(
    db: AsyncSession = Depends(get_db)
):

    result = await db.execute(
        select(Product)
        .where(Product.is_deleted == False)
        .order_by(Product.id.desc())
    )

    products = result.scalars().all()

    return products


# GET SINGLE PRODUCT
@router.get("/{product_id}")
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db)
):

    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted == False
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    return product


# UPDATE PRODUCT
@router.put("/{product_id}")
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db)
):

    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted == False
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    if data.name is not None:
        product.name = data.name

    if data.description is not None:
        product.description = data.description

    if data.price is not None:
        product.price = data.price

    if data.quantity is not None:
        product.quantity = data.quantity

    if data.category is not None:
        product.category = data.category

    if data.image_url is not None:
        product.image_url = data.image_url

    await db.commit()
    await db.refresh(product)

    return {
        "message": "Product updated successfully",
        "product": product
    }


# DELETE PRODUCT
@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db)
):

    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted == False
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    product.is_deleted = True

    await db.commit()
    await db.refresh(product)

    return {
        "message": "Product deleted successfully",
        "product_id": product_id
    }