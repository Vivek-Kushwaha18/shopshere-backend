from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import (
    get_current_seller,
    get_current_user,
)

from app.database.database import get_db

from app.models.category import Category
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.user import User

from app.schemas.product import (
    ProductResponse,
    ProductUpdate,
    StockUpdate,
)


router = APIRouter(
    prefix="/api/products",
    tags=["Products"],
)


# =========================================================
# PUBLIC: GET ALL PRODUCTS
# =========================================================

@router.get(
    "/",
    response_model=list[ProductResponse],
)
async def get_products(
    search: Optional[str] = Query(default=None),
    category_id: Optional[int] = Query(default=None),
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.is_deleted == False
        )
    )

    if search:
        search_value = f"%{search}%"

        query = query.where(
            or_(
                Product.name.ilike(search_value),
                Product.description.ilike(search_value),
            )
        )

    if category_id is not None:
        query = query.where(
            Product.category_id == category_id
        )

    if min_price is not None:
        query = query.where(
            Product.price >= min_price
        )

    if max_price is not None:
        query = query.where(
            Product.price <= max_price
        )

    result = await db.execute(query)

    return result.scalars().all()


# =========================================================
# SELLER: GET OWN PRODUCTS
# =========================================================

@router.get(
    "/seller/my-products",
    response_model=list[ProductResponse],
)
async def get_my_products(
    current_user: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.seller_id == current_user.id,
            Product.is_deleted == False,
        )
    )

    return result.scalars().all()


# =========================================================
# PUBLIC: GET PRODUCTS BY CATEGORY
# =========================================================

@router.get(
    "/category/{category_id}",
    response_model=list[ProductResponse],
)
async def get_products_by_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
):
    category_result = await db.execute(
        select(Category).where(
            Category.id == category_id,
        )
    )

    category = category_result.scalar_one_or_none()

    if not category:
        raise HTTPException(
            status_code=404,
            detail="Category not found",
        )

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.category_id == category_id,
            Product.is_deleted == False,
        )
    )

    return result.scalars().all()


# =========================================================
# SELLER / ADMIN: CREATE PRODUCT
# ONE API ONLY
# POST /api/products/
# =========================================================

@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": [
                            "name",
                            "price",
                            "category_id",
                            "file",
                        ],
                        "properties": {
                            "name": {
                                "type": "string",
                            },
                            "description": {
                                "type": "string",
                            },
                            "price": {
                                "type": "number",
                            },
                            "original_price": {
                                "type": "number",
                            },
                            "stock": {
                                "type": "integer",
                            },
                            "category_id": {
                                "type": "integer",
                            },
                            "file": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "format": "binary",
                                },
                            },
                            "primary_image_index": {
                                "type": "integer",
                                "default": 0,
                            },
                        },
                    },
                },
            },
        },
    },
)
async def create_product(
    request: Request,

    name: str = Form(...),

    description: Optional[str] = Form(
        default=None
    ),

    price: float = Form(...),

    original_price: Optional[float] = Form(
        default=None
    ),

    stock: int = Form(default=0),

    category_id: int = Form(...),

    # One OR multiple images
    file: list[UploadFile] = File(...),

    # 0 = first image
    # 1 = second image
    # 2 = third image
    primary_image_index: int = Form(
        default=0
    ),

    current_user: User = Depends(
        get_current_user
    ),

    db: AsyncSession = Depends(
        get_db
    ),
):
    # -----------------------------------------------------
    # Seller / Admin permission
    # -----------------------------------------------------

    if current_user.role not in (
        "seller",
        "admin",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only sellers and admins "
                "can create products"
            ),
        )

    # -----------------------------------------------------
    # Validate images
    # -----------------------------------------------------

    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one product image is required.",
        )

    if len(file) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can upload a maximum of 10 images.",
        )

    # -----------------------------------------------------
    # Validate primary image
    # -----------------------------------------------------

    if (
        primary_image_index < 0
        or primary_image_index >= len(file)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid primary image selection.",
        )

    # -----------------------------------------------------
    # Validate category
    # -----------------------------------------------------

    category_result = await db.execute(
        select(Category).where(
            Category.id == category_id,
        )
    )

    category = (
        category_result.scalar_one_or_none()
    )

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # -----------------------------------------------------
    # Allowed image types
    # -----------------------------------------------------

    allowed_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }

    # -----------------------------------------------------
    # Upload directory
    # -----------------------------------------------------

    upload_dir = Path(
        "uploads/products"
    )

    upload_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Keep track of uploaded files
    saved_files: list[Path] = []

    try:
        # -------------------------------------------------
        # Create product
        # -------------------------------------------------

        product = Product(
            seller_id=current_user.id,
            category_id=category_id,
            name=name.strip(),
            description=(
                description.strip()
                if description
                else None
            ),
            price=price,
            original_price=original_price,
            stock=stock,

            # Main image will be set below
            image_url=None,

            # Required database values
            rating=0.0,
            reviews_count=0,
            is_deleted=False,
            is_active=True,
        )

        db.add(product)

        # Get product ID
        await db.flush()

        # -------------------------------------------------
        # Save one or multiple images
        # -------------------------------------------------

        for index, uploaded_file in enumerate(file):

            # ---------------------------------------------
            # Validate image type
            # ---------------------------------------------

            if uploaded_file.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Invalid image type for "
                        f"{uploaded_file.filename}. "
                        f"Only JPG, PNG, WEBP, and GIF "
                        f"images are allowed."
                    ),
                )

            # ---------------------------------------------
            # Read image
            # ---------------------------------------------

            contents = await uploaded_file.read()

            # ---------------------------------------------
            # Maximum 5 MB per image
            # ---------------------------------------------

            max_size = 5 * 1024 * 1024

            if len(contents) > max_size:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"{uploaded_file.filename} "
                        f"is larger than 5 MB."
                    ),
                )

            # ---------------------------------------------
            # Generate unique filename
            # ---------------------------------------------

            extension = allowed_types[
                uploaded_file.content_type
            ]

            filename = (
                f"{uuid4().hex}{extension}"
            )

            file_path = (
                upload_dir / filename
            )

            # ---------------------------------------------
            # Save image
            # ---------------------------------------------

            file_path.write_bytes(
                contents
            )

            saved_files.append(
                file_path
            )

            # ---------------------------------------------
            # Public image URL
            # ---------------------------------------------

            image_url = (
                f"{str(request.base_url).rstrip('/')}"
                f"/uploads/products/{filename}"
            )

            # ---------------------------------------------
            # Is this the main image?
            # ---------------------------------------------

            is_primary = (
                index == primary_image_index
            )

            # ---------------------------------------------
            # Save main image in products.image_url
            # ---------------------------------------------

            if is_primary:
                product.image_url = image_url

            # ---------------------------------------------
            # Save image in product_images
            # ---------------------------------------------

            product_image = ProductImage(
                product_id=product.id,
                image_url=image_url,
                is_primary=is_primary,
            )

            db.add(product_image)

        # -------------------------------------------------
        # Commit
        # -------------------------------------------------

        await db.commit()

        # -------------------------------------------------
        # Reload product + images
        # -------------------------------------------------

        result = await db.execute(
            select(Product)
            .options(
                selectinload(Product.images)
            )
            .where(
                Product.id == product.id
            )
        )

        created_product = (
            result.scalar_one()
        )

        return created_product

    except HTTPException:
        await db.rollback()

        for file_path in saved_files:
            if file_path.exists():
                file_path.unlink()

        raise

    except Exception:
        await db.rollback()

        for file_path in saved_files:
            if file_path.exists():
                file_path.unlink()

        raise


# =========================================================
# PUBLIC: GET SINGLE PRODUCT
# =========================================================

@router.get(
    "/{product_id}",
    response_model=ProductResponse,
)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product_id,
            Product.is_deleted == False,
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    return product


# =========================================================
# SELLER / ADMIN: UPDATE PRODUCT
# =========================================================

@router.put(
    "/{product_id}",
    response_model=ProductResponse,
)
async def update_product(
    product_id: int,
    product_data: ProductUpdate,
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(
        get_db
    ),
):
    if current_user.role not in (
        "seller",
        "admin",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only sellers and admins "
                "can update products"
            ),
        )

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product_id,
            Product.is_deleted == False,
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    if (
        current_user.role == "seller"
        and product.seller_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can only update "
                "your own products"
            ),
        )

    if product_data.category_id is not None:
        category_result = await db.execute(
            select(Category).where(
                Category.id
                == product_data.category_id,
            )
        )

        category = (
            category_result.scalar_one_or_none()
        )

        if not category:
            raise HTTPException(
                status_code=404,
                detail="Category not found",
            )

    update_data = product_data.model_dump(
        exclude_unset=True
    )

    for field, value in update_data.items():
        setattr(
            product,
            field,
            value,
        )

    await db.commit()

    await db.refresh(product)

    return product


# =========================================================
# SELLER / ADMIN: UPDATE STOCK
# =========================================================

@router.patch(
    "/{product_id}/stock",
    response_model=ProductResponse,
)
async def update_stock(
    product_id: int,
    stock_data: StockUpdate,
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(
        get_db
    ),
):
    if current_user.role not in (
        "seller",
        "admin",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only sellers and admins "
                "can update inventory"
            ),
        )

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product_id,
            Product.is_deleted == False,
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    if (
        current_user.role == "seller"
        and product.seller_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can only manage "
                "your own inventory"
            ),
        )

    product.stock = stock_data.stock

    await db.commit()

    await db.refresh(product)

    return product


# =========================================================
# SELLER / ADMIN: SOFT DELETE PRODUCT
# =========================================================

@router.delete(
    "/{product_id}",
)
async def delete_product(
    product_id: int,
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(
        get_db
    ),
):
    if current_user.role not in (
        "seller",
        "admin",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only sellers and admins "
                "can delete products"
            ),
        )

    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted == False,
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    if (
        current_user.role == "seller"
        and product.seller_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can only delete "
                "your own products"
            ),
        )

    product.is_deleted = True

    await db.commit()

    return {
        "message": "Product deleted successfully"
    }