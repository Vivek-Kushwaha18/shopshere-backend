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

from app.utils.slug import slugify

from app.utils.storage import (
    delete_product_image,
    upload_product_image,
)


router = APIRouter(
    prefix="/api/products",
    tags=["Products"],
)


# =========================================================
# IMAGE CONFIG
# =========================================================

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

MAX_IMAGE_SIZE = 5 * 1024 * 1024

MAX_IMAGES = 10


# =========================================================
# IMAGE VALIDATION HELPER
# =========================================================

async def read_and_validate_images(
    files: list[UploadFile],
) -> list[
    tuple[
        bytes,
        str,
        str,
        str,
    ]
]:

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "At least one product image "
                "is required."
            ),
        )

    if len(files) > MAX_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"You can upload a maximum "
                f"of {MAX_IMAGES} images."
            ),
        )

    validated_images = []

    for uploaded_file in files:

        if uploaded_file.content_type not in (
            ALLOWED_IMAGE_TYPES
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid image type for "
                    f"{uploaded_file.filename}. "
                    f"Only JPG, PNG, WEBP, and GIF "
                    f"images are allowed."
                ),
            )

        contents = await uploaded_file.read()

        if len(contents) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{uploaded_file.filename} "
                    f"is larger than 5 MB."
                ),
            )

        extension = ALLOWED_IMAGE_TYPES[
            uploaded_file.content_type
        ]

        validated_images.append(
            (
                contents,
                extension,
                uploaded_file.content_type,
                uploaded_file.filename
                or "image",
            )
        )

    return validated_images


# =========================================================
# PRODUCT SLUG HELPER
# =========================================================

async def generate_product_slug(
    db: AsyncSession,
    name: str,
) -> str:

    base_slug = slugify(name)

    if not base_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Product name cannot generate "
                "a valid slug."
            ),
        )

    slug = base_slug
    counter = 2

    while True:

        result = await db.execute(
            select(Product).where(
                Product.slug == slug
            )
        )

        existing_product = (
            result.scalar_one_or_none()
        )

        if existing_product is None:
            return slug

        slug = f"{base_slug}-{counter}"

        # IMPORTANT:
        # Move to the next slug number.
        counter += 1


# =========================================================
# PRODUCT PERMISSION HELPER
# =========================================================

def check_product_owner(
    product: Product,
    current_user: User,
) -> None:

    if current_user.role not in (
        "seller",
        "admin",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only sellers and admins "
                "can manage products."
            ),
        )

    if (
        current_user.role == "seller"
        and product.seller_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can only manage "
                "your own products."
            ),
        )


# =========================================================
# PUBLIC: GET ALL PRODUCTS
# =========================================================

@router.get(
    "/",
    response_model=list[ProductResponse],
)
async def get_products(
    search: Optional[str] = Query(
        default=None
    ),
    category_id: Optional[int] = Query(
        default=None
    ),
    min_price: Optional[float] = Query(
        default=None,
        ge=0,
    ),
    max_price: Optional[float] = Query(
        default=None,
        ge=0,
    ),
    db: AsyncSession = Depends(get_db),
):

    query = (
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    if search:

        search_value = (
            f"%{search}%"
        )

        query = query.where(
            or_(
                Product.name.ilike(
                    search_value
                ),
                Product.description.ilike(
                    search_value
                ),
            )
        )

    if category_id is not None:

        query = query.where(
            Product.category_id
            == category_id
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
    current_user: User = Depends(
        get_current_seller
    ),
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.seller_id
            == current_user.id,
            Product.is_deleted.is_(False),
        )
    )

    return result.scalars().all()


# =========================================================
# PUBLIC: GET PRODUCTS BY CATEGORY SLUG
# =========================================================

@router.get(
    "/category/{category_slug}",
    response_model=list[ProductResponse],
)
async def get_products_by_category(
    category_slug: str,
    db: AsyncSession = Depends(get_db),
):

    category_result = await db.execute(
        select(Category).where(
            Category.slug == category_slug,
            Category.is_active.is_(True),
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

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.category_id == category.id,
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    return result.scalars().all()


# =========================================================
# SELLER / ADMIN: CREATE PRODUCT
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

    stock: int = Form(
        default=0
    ),

    category_id: int = Form(...),

    file: list[UploadFile] = File(...),

    primary_image_index: int = Form(
        default=0
    ),

    current_user: User = Depends(
        get_current_user
    ),

    db: AsyncSession = Depends(get_db),
):

    # -----------------------------------------------------
    # Permission
    # -----------------------------------------------------

    if current_user.role not in (
        "seller",
        "admin",
    ):

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only sellers and admins "
                "can create products."
            ),
        )

    # -----------------------------------------------------
    # Clean product name
    # -----------------------------------------------------

    clean_name = name.strip()

    if not clean_name:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product name cannot be empty.",
        )

    # -----------------------------------------------------
    # Primary image validation
    # -----------------------------------------------------

    if (
        primary_image_index < 0
        or primary_image_index >= len(file)
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid primary image selection."
            ),
        )

    # -----------------------------------------------------
    # Validate category
    # -----------------------------------------------------

    category_result = await db.execute(
        select(Category).where(
            Category.id == category_id,
            Category.is_active.is_(True),
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

    # -----------------------------------------------------
    # Validate all files before database changes
    # -----------------------------------------------------

    validated_images = (
        await read_and_validate_images(file)
    )

    # -----------------------------------------------------
    # Generate unique slug
    # -----------------------------------------------------

    slug = await generate_product_slug(
        db,
        clean_name,
    )

    uploaded_urls: list[str] = []

    try:

        # -------------------------------------------------
        # Create product
        # -------------------------------------------------

        product = Product(
            seller_id=current_user.id,
            category_id=category_id,
            name=clean_name,
            slug=slug,
            description=(
                description.strip()
                if description
                else None
            ),
            price=price,
            original_price=original_price,
            stock=stock,
            image_url=None,
            rating=0.0,
            reviews_count=0,
            is_deleted=False,
            is_active=True,
        )

        db.add(product)

        await db.flush()

        # -------------------------------------------------
        # Upload all images
        # -------------------------------------------------

        for index, image_data in enumerate(
            validated_images
        ):

            (
                contents,
                extension,
                content_type,
                original_filename,
            ) = image_data

            unique_filename = uuid4().hex

            image_url = upload_product_image(
                contents=contents,
                filename=unique_filename,
                extension=extension,
                content_type=content_type,
                base_url=str(
                    request.base_url
                ),
            )

            uploaded_urls.append(
                image_url
            )

            is_primary = (
                index
                == primary_image_index
            )

            if is_primary:

                product.image_url = (
                    image_url
                )

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
        # Reload
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

        return result.scalar_one()

    except HTTPException:

        await db.rollback()

        for image_url in uploaded_urls:

            delete_product_image(
                image_url
            )

        raise

    except Exception:

        await db.rollback()

        for image_url in uploaded_urls:

            delete_product_image(
                image_url
            )

        raise


# =========================================================
# PUBLIC: GET SINGLE PRODUCT BY SLUG
# =========================================================

@router.get(
    "/slug/{slug}",
    response_model=ProductResponse,
)
async def get_product_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.slug == slug,
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    product = (
        result.scalar_one_or_none()
    )

    if not product:

        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    return product


# =========================================================
# PUBLIC: GET SINGLE PRODUCT BY ID
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
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    product = (
        result.scalar_one_or_none()
    )

    if not product:

        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    return product


# =========================================================
# SELLER / ADMIN: UPDATE PRODUCT
#
# IMPORTANT:
# Product slug is NOT changed when product name changes.
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

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = (
        result.scalar_one_or_none()
    )

    if not product:

        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    check_product_owner(
        product,
        current_user,
    )

    # -----------------------------------------------------
    # Validate category
    # -----------------------------------------------------

    if product_data.category_id is not None:

        category_result = await db.execute(
            select(Category).where(
                Category.id
                == product_data.category_id,
                Category.is_active.is_(True),
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

    # -----------------------------------------------------
    # Update fields
    # -----------------------------------------------------

    update_data = (
        product_data.model_dump(
            exclude_unset=True
        )
    )

    # -----------------------------------------------------
    # Keep slug unchanged
    # -----------------------------------------------------

    update_data.pop(
        "slug",
        None,
    )

    for field, value in update_data.items():

        if field == "name" and value is not None:

            value = value.strip()

            if not value:

                raise HTTPException(
                    status_code=(
                        status.HTTP_400_BAD_REQUEST
                    ),
                    detail=(
                        "Product name "
                        "cannot be empty."
                    ),
                )

        setattr(
            product,
            field,
            value,
        )

    await db.commit()

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product.id
        )
    )

    return result.scalar_one()


# =========================================================
# SELLER / ADMIN: REPLACE PRODUCT IMAGES
#
# PUT /api/products/{product_id}/images
#
# This replaces the complete image gallery.
# =========================================================

@router.put(
    "/{product_id}/images",
    response_model=ProductResponse,
)
async def replace_product_images(
    product_id: int,

    request: Request,

    file: list[UploadFile] = File(...),

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

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = (
        result.scalar_one_or_none()
    )

    if not product:

        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    check_product_owner(
        product,
        current_user,
    )

    if (
        primary_image_index < 0
        or primary_image_index >= len(file)
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid primary image selection."
            ),
        )

    validated_images = (
        await read_and_validate_images(file)
    )

    old_image_urls = [
        image.image_url
        for image in product.images
    ]

    uploaded_urls: list[str] = []

    try:

        # -------------------------------------------------
        # Upload new images
        # -------------------------------------------------

        new_images = []

        for index, image_data in enumerate(
            validated_images
        ):

            (
                contents,
                extension,
                content_type,
                original_filename,
            ) = image_data

            unique_filename = uuid4().hex

            image_url = upload_product_image(
                contents=contents,
                filename=unique_filename,
                extension=extension,
                content_type=content_type,
                base_url=str(
                    request.base_url
                ),
            )

            uploaded_urls.append(
                image_url
            )

            is_primary = (
                index
                == primary_image_index
            )

            new_images.append(
                ProductImage(
                    product_id=product.id,
                    image_url=image_url,
                    is_primary=is_primary,
                )
            )

            if is_primary:

                product.image_url = (
                    image_url
                )

        # -------------------------------------------------
        # Delete old database image records
        # -------------------------------------------------

        for old_image in product.images:

            await db.delete(
                old_image
            )

        # -------------------------------------------------
        # Add new image records
        # -------------------------------------------------

        for new_image in new_images:

            db.add(new_image)

        await db.commit()

        # -------------------------------------------------
        # Remove old physical files after successful
        # DB commit
        # -------------------------------------------------

        for old_url in old_image_urls:

            delete_product_image(
                old_url
            )

        # -------------------------------------------------
        # Reload product
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

        return result.scalar_one()

    except HTTPException:

        await db.rollback()

        for image_url in uploaded_urls:

            delete_product_image(
                image_url
            )

        raise

    except Exception:

        await db.rollback()

        for image_url in uploaded_urls:

            delete_product_image(
                image_url
            )

        raise


# =========================================================
# SELLER / ADMIN: SET PRIMARY IMAGE
# =========================================================

@router.patch(
    "/{product_id}/images/{image_id}/primary",
    response_model=ProductResponse,
)
async def set_primary_image(
    product_id: int,

    image_id: int,

    current_user: User = Depends(
        get_current_user
    ),

    db: AsyncSession = Depends(
        get_db
    ),
):

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = (
        result.scalar_one_or_none()
    )

    if not product:

        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    check_product_owner(
        product,
        current_user,
    )

    image_result = await db.execute(
        select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.product_id
            == product_id,
        )
    )

    image = (
        image_result.scalar_one_or_none()
    )

    if not image:

        raise HTTPException(
            status_code=404,
            detail="Product image not found",
        )

    # -----------------------------------------------------
    # Remove primary from all images
    # -----------------------------------------------------

    for product_image in product.images:

        product_image.is_primary = False

    # -----------------------------------------------------
    # Set selected image primary
    # -----------------------------------------------------

    image.is_primary = True

    product.image_url = (
        image.image_url
    )

    await db.commit()

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product.id
        )
    )

    return result.scalar_one()


# =========================================================
# SELLER / ADMIN: DELETE ONE IMAGE
# =========================================================

@router.delete(
    "/{product_id}/images/{image_id}",
)
async def delete_product_image_endpoint(
    product_id: int,

    image_id: int,

    current_user: User = Depends(
        get_current_user
    ),

    db: AsyncSession = Depends(
        get_db
    ),
):

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = (
        result.scalar_one_or_none()
    )

    if not product:

        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    check_product_owner(
        product,
        current_user,
    )

    image_result = await db.execute(
        select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.product_id
            == product_id,
        )
    )

    image = (
        image_result.scalar_one_or_none()
    )

    if not image:

        raise HTTPException(
            status_code=404,
            detail="Product image not found",
        )

    # -----------------------------------------------------
    # Prevent deleting the only image
    # -----------------------------------------------------

    if len(product.images) <= 1:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A product must have at least "
                "one image."
            ),
        )

    deleted_url = image.image_url

    was_primary = image.is_primary

    await db.delete(image)

    # -----------------------------------------------------
    # If primary image was deleted,
    # select another image as primary.
    # -----------------------------------------------------

    if was_primary:

        remaining_images = [
            item
            for item in product.images
            if item.id != image.id
        ]

        if remaining_images:

            new_primary = (
                remaining_images[0]
            )

            new_primary.is_primary = True

            product.image_url = (
                new_primary.image_url
            )

    await db.commit()

    # -----------------------------------------------------
    # Delete physical file / S3 object
    # -----------------------------------------------------

    delete_product_image(
        deleted_url
    )

    return {
        "message": (
            "Product image deleted successfully"
        )
    }


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

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = (
        result.scalar_one_or_none()
    )

    if not product:

        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    check_product_owner(
        product,
        current_user,
    )

    product.stock = stock_data.stock

    await db.commit()

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images)
        )
        .where(
            Product.id == product.id
        )
    )

    return result.scalar_one()


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

    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = (
        result.scalar_one_or_none()
    )

    if not product:

        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    check_product_owner(
        product,
        current_user,
    )

    product.is_deleted = True

    await db.commit()

    return {
        "message": (
            "Product deleted successfully"
        )
    }