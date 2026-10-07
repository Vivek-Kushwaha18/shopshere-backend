from typing import Optional
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user
from app.database.database import get_db

from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_variant import ProductVariant
from app.models.user import User

from app.utils.storage import (
    delete_product_image,
    upload_product_image,
)


router = APIRouter(
    prefix="/api/products",
    tags=["Product Variant Images"],
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
# GET VARIANT FOR OWNER
# =========================================================

async def get_variant_for_owner(
    variant_id: int,
    current_user: User,
    db: AsyncSession,
) -> ProductVariant:

    result = await db.execute(
        select(ProductVariant)
        .options(
            selectinload(ProductVariant.product)
        )
        .where(
            ProductVariant.id == variant_id,
        )
    )

    variant = result.scalar_one_or_none()

    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant not found",
        )

    product = variant.product

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if product.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if (
        current_user.role != "admin"
        and product.seller_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You do not have permission "
                "to manage this variant"
            ),
        )

    return variant


# =========================================================
# VALIDATE IMAGES
# =========================================================

async def read_and_validate_images(
    files: list[UploadFile],
) -> list[
    tuple[
        bytes,
        str,
        str,
    ]
]:

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one image is required.",
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
            )
        )

    return validated_images


# =========================================================
# GET VARIANT IMAGES
# =========================================================

@router.get(
    "/variants/{variant_id}/images",
)
async def get_variant_images(
    variant_id: int,
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        select(ProductVariant)
        .options(
            selectinload(ProductVariant.images)
        )
        .where(
            ProductVariant.id == variant_id,
            ProductVariant.is_active.is_(True),
        )
    )

    variant = result.scalar_one_or_none()

    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant not found",
        )

    images = sorted(
        variant.images,
        key=lambda image: (
            image.sort_order,
            image.id,
        ),
    )

    return [
        {
            "id": image.id,
            "variant_id": image.variant_id,
            "image_url": image.image_url,
            "view_type": image.view_type,
            "sort_order": image.sort_order,
            "is_primary": image.is_primary,
        }
        for image in images
    ]


# =========================================================
# UPLOAD VARIANT IMAGES
# =========================================================

@router.post(
    "/variants/{variant_id}/images",
)
async def upload_variant_images(
    variant_id: int,

    request: Request,

    file: list[UploadFile] = File(...),

    primary_image_index: int = Form(
        default=0
    ),

    view_type: Optional[list[str]] = Form(
        default=None
    ),

    current_user: User = Depends(
        get_current_user
    ),

    db: AsyncSession = Depends(get_db),
):

    variant = await get_variant_for_owner(
        variant_id,
        current_user,
        db,
    )

    if (
        primary_image_index < 0
        or primary_image_index >= len(file)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid primary image selection.",
        )

    if (
        view_type is not None
        and len(view_type) != len(file)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "view_type must contain one value "
                "for each image."
            ),
        )

    validated_images = (
        await read_and_validate_images(file)
    )

    existing_images_result = await db.execute(
        select(ProductImage).where(
            ProductImage.variant_id == variant.id
        )
    )

    existing_images = (
        existing_images_result.scalars().all()
    )

    if len(existing_images) + len(file) > MAX_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A variant can have a maximum "
                f"of {MAX_IMAGES} images."
            ),
        )

    uploaded_urls: list[str] = []

    try:

        has_existing_primary = any(
            image.is_primary
            for image in existing_images
        )

        for index, image_data in enumerate(
            validated_images
        ):

            (
                contents,
                extension,
                content_type,
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

            if has_existing_primary:
                is_primary = False

            if is_primary:
                for existing_image in existing_images:
                    existing_image.is_primary = False

            image_view_type = None

            if view_type is not None:
                image_view_type = (
                    view_type[index].strip()
                    or None
                )

            next_sort_order = (
                len(existing_images)
                + index
            )

            product_image = ProductImage(
                product_id=variant.product_id,
                variant_id=variant.id,
                image_url=image_url,
                view_type=image_view_type,
                sort_order=next_sort_order,
                is_primary=is_primary,
            )

            db.add(product_image)

        await db.commit()

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

    return {
        "success": True,
        "message": "Variant images uploaded successfully",
    }


# =========================================================
# SET VARIANT IMAGE PRIMARY
# =========================================================

@router.patch(
    "/variants/{variant_id}/images/{image_id}/primary",
)
async def set_variant_image_primary(
    variant_id: int,

    image_id: int,

    current_user: User = Depends(
        get_current_user
    ),

    db: AsyncSession = Depends(get_db),
):

    variant = await get_variant_for_owner(
        variant_id,
        current_user,
        db,
    )

    result = await db.execute(
        select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.variant_id == variant.id,
        )
    )

    image = result.scalar_one_or_none()

    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant image not found",
        )

    result = await db.execute(
        select(ProductImage).where(
            ProductImage.variant_id == variant.id
        )
    )

    images = result.scalars().all()

    for variant_image in images:
        variant_image.is_primary = False

    image.is_primary = True

    await db.commit()

    return {
        "success": True,
        "message": "Variant primary image updated successfully",
    }


# =========================================================
# DELETE VARIANT IMAGE
# =========================================================

@router.delete(
    "/variants/{variant_id}/images/{image_id}",
)
async def delete_variant_image(
    variant_id: int,

    image_id: int,

    current_user: User = Depends(
        get_current_user
    ),

    db: AsyncSession = Depends(get_db),
):

    variant = await get_variant_for_owner(
        variant_id,
        current_user,
        db,
    )

    result = await db.execute(
        select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.variant_id == variant.id,
        )
    )

    image = result.scalar_one_or_none()

    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant image not found",
        )

    result = await db.execute(
        select(ProductImage).where(
            ProductImage.variant_id == variant.id,
            ProductImage.id != image.id,
        )
    )

    remaining_images = (
        result.scalars().all()
    )

    deleted_url = image.image_url
    was_primary = image.is_primary

    await db.delete(image)

    if was_primary and remaining_images:

        remaining_images.sort(
            key=lambda item: (
                item.sort_order,
                item.id,
            )
        )

        remaining_images[0].is_primary = True

    await db.commit()

    delete_product_image(
        deleted_url
    )

    return {
        "success": True,
        "message": "Variant image deleted successfully",
    }