import os
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import get_db
from app.models.product import Product
from app.models.product_image import ProductImage


router = APIRouter(
    prefix="/products",
    tags=["Products"]
)


# Upload folder
UPLOAD_DIR = "uploads/products"

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True
)


# CREATE PRODUCT
@router.post("/")
async def create_product(
    name: str = Form(...),
    description: str = Form(""),
    price: int = Form(...),
    quantity: int = Form(...),
    category: str = Form(...),
    images: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db)
):

    # Create product
    product = Product(
        name=name,
        description=description,
        price=price,
        quantity=quantity,
        category=category
    )

    db.add(product)

    await db.flush()

    # Save multiple images
    saved_images = []

    for image in images:

        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(
                status_code=400,
                detail=f"{image.filename} is not a valid image"
            )

        file_extension = os.path.splitext(
            image.filename
        )[1]

        file_name = f"{uuid.uuid4()}{file_extension}"

        file_path = os.path.join(
            UPLOAD_DIR,
            file_name
        )

        with open(file_path, "wb") as buffer:
            content = await image.read()
            buffer.write(content)

        image_url = f"/uploads/products/{file_name}"

        product_image = ProductImage(
            product_id=product.id,
            image_url=image_url
        )

        db.add(product_image)

        saved_images.append(image_url)

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
            "images": saved_images
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

    response = []

    for product in products:

        image_result = await db.execute(
            select(ProductImage)
            .where(
                ProductImage.product_id == product.id
            )
        )

        images = image_result.scalars().all()

        response.append({
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "price": product.price,
            "quantity": product.quantity,
            "category": product.category,
            "images": [
                image.image_url
                for image in images
            ]
        })

    return response


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

    image_result = await db.execute(
        select(ProductImage)
        .where(
            ProductImage.product_id == product.id
        )
    )

    images = image_result.scalars().all()

    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price": product.price,
        "quantity": product.quantity,
        "category": product.category,
        "images": [
            image.image_url
            for image in images
        ]
    }


# UPDATE PRODUCT
@router.put("/{product_id}")
async def update_product(
    product_id: int,
    name: str | None = Form(None),
    description: str | None = Form(None),
    price: int | None = Form(None),
    quantity: int | None = Form(None),
    category: str | None = Form(None),
    images: list[UploadFile] | None = File(None),
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

    # Update product fields
    if name is not None:
        product.name = name

    if description is not None:
        product.description = description

    if price is not None:
        product.price = price

    if quantity is not None:
        product.quantity = quantity

    if category is not None:
        product.category = category

    new_images = []

    # Upload new images if provided
    if images:

        for image in images:

            if not image.content_type or not image.content_type.startswith("image/"):
                raise HTTPException(
                    status_code=400,
                    detail=f"{image.filename} is not a valid image"
                )

            file_extension = os.path.splitext(
                image.filename
            )[1]

            file_name = f"{uuid.uuid4()}{file_extension}"

            file_path = os.path.join(
                UPLOAD_DIR,
                file_name
            )

            with open(file_path, "wb") as buffer:
                content = await image.read()
                buffer.write(content)

            image_url = f"/uploads/products/{file_name}"

            product_image = ProductImage(
                product_id=product.id,
                image_url=image_url
            )

            db.add(product_image)

            new_images.append(image_url)

    await db.commit()
    await db.refresh(product)

    return {
        "message": "Product updated successfully",
        "product": {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "price": product.price,
            "quantity": product.quantity,
            "category": product.category,
            "new_images": new_images
        }
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

    # Soft delete
    product.is_deleted = True

    await db.commit()
    await db.refresh(product)

    return {
        "message": "Product deleted successfully",
        "product_id": product_id
    }