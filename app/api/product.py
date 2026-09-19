from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import get_db
from app.models.category import Category
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductResponse


router = APIRouter(
    prefix="/products",
    tags=["Products"],
)


@router.post(
    "/",
    response_model=ProductResponse,
)
async def create_product(
    product_data: ProductCreate,
    db: AsyncSession = Depends(get_db),
):
    # Check whether category exists
    result = await db.execute(
        select(Category).where(
            Category.id == product_data.category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=404,
            detail="Category not found",
        )

    product = Product(
        name=product_data.name,
        description=product_data.description,
        price=product_data.price,
        original_price=product_data.original_price,
        stock=product_data.stock,
        image=product_data.image,
        category_id=product_data.category_id,
    )

    db.add(product)

    await db.commit()
    await db.refresh(product)

    return product


@router.get(
    "/",
    response_model=list[ProductResponse],
)
async def get_products(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
    )

    products = result.scalars().all()

    return products


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(
            Product.id == product_id
        )
    )

    product = result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    return product


@router.put(
    "/{product_id}",
    response_model=ProductResponse,
)
async def update_product(
    product_id: int,
    product_data: ProductCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(
            Product.id == product_id
        )
    )

    product = result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    # Check category
    category_result = await db.execute(
        select(Category).where(
            Category.id == product_data.category_id
        )
    )

    category = category_result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=404,
            detail="Category not found",
        )

    product.name = product_data.name
    product.description = product_data.description
    product.price = product_data.price
    product.original_price = product_data.original_price
    product.stock = product_data.stock
    product.image = product_data.image
    product.category_id = product_data.category_id

    await db.commit()
    await db.refresh(product)

    return product


@router.delete(
    "/{product_id}",
)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(
            Product.id == product_id
        )
    )

    product = result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    await db.delete(product)
    await db.commit()

    return {
        "message": "Product deleted successfully"
    }