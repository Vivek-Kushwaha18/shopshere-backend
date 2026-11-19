
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

from app.api.auth import get_current_user
from app.database.database import get_db
from app.models.category import Category
from app.models.user import User
from app.schemas.category import (
    CategoryResponse,
    CategoryUpdate,
)
from app.utils.slug import slugify
from app.utils.storage import (
    upload_category_icon,
    delete_category_icon,
)


router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


# =========================================================
# IMAGE SETTINGS
# =========================================================

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

MAX_ICON_SIZE = 2 * 1024 * 1024


# =========================================================
# ADMIN PERMISSION
# =========================================================

def require_admin(user: User) -> None:

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can manage categories",
        )


# =========================================================
# VALIDATE CATEGORY ICON
# =========================================================

async def validate_icon(
    file: UploadFile,
) -> tuple[bytes, str, str]:

    content_type = file.content_type or ""

    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only JPG, PNG and WEBP images are allowed",
        )

    contents = await file.read(MAX_ICON_SIZE + 1)

    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category icon cannot be empty",
        )

    if len(contents) > MAX_ICON_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category icon must not exceed 2 MB",
        )

    if content_type == "image/jpeg":
        valid = contents.startswith(b"\xff\xd8\xff")

    elif content_type == "image/png":
        valid = contents.startswith(
            b"\x89PNG\r\n\x1a\n"
        )

    else:
        valid = (
            contents.startswith(b"RIFF")
            and contents[8:12] == b"WEBP"
        )

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file",
        )

    return (
        contents,
        ALLOWED_IMAGE_TYPES[content_type],
        content_type,
    )


# =========================================================
# SAVE ICON
# =========================================================

def save_icon(
    contents: bytes,
    extension: str,
    content_type: str,
    category_id: int,
    request: Request,
) -> str:

    filename = (
        f"category-{category_id}-{uuid4().hex}"
    )

    try:
        return upload_category_icon(
            contents=contents,
            filename=filename,
            extension=extension,
            content_type=content_type,
            base_url=str(request.base_url).rstrip("/"),
        )

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload category icon",
        ) from error


# =========================================================
# GENERATE UNIQUE CATEGORY SLUG
# =========================================================

async def generate_category_slug(
    db: AsyncSession,
    name: str,
) -> str:

    base_slug = slugify(name)

    if not base_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name cannot generate a valid slug",
        )

    slug = base_slug
    counter = 2

    while True:
        result = await db.execute(
            select(Category).where(
                Category.slug == slug
            )
        )

        existing_category = result.scalar_one_or_none()

        if existing_category is None:
            return slug

        slug = f"{base_slug}-{counter}"
        counter += 1


# =========================================================
# VALIDATE PARENT CATEGORY
# =========================================================

async def validate_parent_category(
    db: AsyncSession,
    parent_id: int | None,
    category_id: int | None = None,
) -> None:

    if parent_id is None:
        return

    if category_id is not None and parent_id == category_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A category cannot be its own parent",
        )

    result = await db.execute(
        select(Category).where(
            Category.id == parent_id
        )
    )

    parent = result.scalar_one_or_none()

    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent category not found",
        )

    if not parent.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot use an inactive category as parent",
        )

    if category_id is not None:

        current_parent_id = parent.parent_id

        while current_parent_id is not None:

            if current_parent_id == category_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot create a circular category structure",
                )

            result = await db.execute(
                select(Category.parent_id).where(
                    Category.id == current_parent_id
                )
            )

            current_parent_id = result.scalar_one_or_none()


# =========================================================
# GET ALL ACTIVE CATEGORIES
# =========================================================

@router.get(
    "/",
    response_model=list[CategoryResponse],
)
async def get_categories(
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.name)
    )

    return result.scalars().all()


# =========================================================
# GET CATEGORY BY SLUG
# =========================================================

@router.get(
    "/slug/{slug}",
    response_model=CategoryResponse,
)
async def get_category_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        select(Category).where(
            Category.slug == slug,
            Category.is_active.is_(True),
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    return category


# =========================================================
# GET CATEGORY BY ID
# =========================================================

@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
)
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        select(Category).where(
            Category.id == category_id,
            Category.is_active.is_(True),
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    return category


# =========================================================
# CREATE CATEGORY
# MAIN CATEGORY ICON REQUIRED
# SUBCATEGORY ICON OPTIONAL
# =========================================================

@router.post(
    "/",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    request: Request,
    name: str = Form(...),
    description: str | None = Form(default=None),
    parent_id: int | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    require_admin(current_user)

    name = name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name cannot be empty",
        )

    if len(name) < 2 or len(name) > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Category name must contain 2 to 100 characters",
        )

    # Main category requires an icon
    if parent_id is None and file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Main category icon is required",
        )

    validated_icon = None

    if file is not None:
        validated_icon = await validate_icon(file)

    # Check duplicate name
    result = await db.execute(
        select(Category).where(
            Category.name.ilike(name)
        )
    )

    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category already exists",
        )

    # Validate parent
    await validate_parent_category(
        db=db,
        parent_id=parent_id,
    )

    # Generate slug
    slug = await generate_category_slug(
        db,
        name,
    )

    category = Category(
        name=name,
        slug=slug,
        description=(
            description.strip()
            if description
            else None
        ),
        parent_id=parent_id,
        icon_url=None,
        is_active=True,
    )

    db.add(category)

    uploaded_icon_url = None

    try:
        await db.flush()

        if validated_icon is not None:

            contents, extension, content_type = validated_icon

            uploaded_icon_url = save_icon(
                contents=contents,
                extension=extension,
                content_type=content_type,
                category_id=category.id,
                request=request,
            )

            category.icon_url = uploaded_icon_url

        await db.commit()
        await db.refresh(category)

    except Exception:
        await db.rollback()

        if uploaded_icon_url:
            delete_category_icon(uploaded_icon_url)

        raise

    return category


# =========================================================
# UPDATE CATEGORY
# =========================================================

@router.put(
    "/{category_id}",
    response_model=CategoryResponse,
)
async def update_category(
    category_id: int,
    category_data: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    require_admin(current_user)

    result = await db.execute(
        select(Category).where(
            Category.id == category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Update name
    if category_data.name is not None:

        name = category_data.name.strip()

        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category name cannot be empty",
            )

        duplicate_result = await db.execute(
            select(Category).where(
                Category.name.ilike(name),
                Category.id != category_id,
            )
        )

        if duplicate_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category already exists",
            )

        category.name = name

    # Update description
    if category_data.description is not None:
        category.description = (
            category_data.description.strip()
            or None
        )

    # Update parent
    if "parent_id" in category_data.model_fields_set:

        await validate_parent_category(
            db=db,
            parent_id=category_data.parent_id,
            category_id=category_id,
        )

        if (
            category_data.parent_id is None
            and category.parent_id is not None
            and not category.icon_url
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Upload a category icon before "
                    "converting it to a main category"
                ),
            )

        category.parent_id = category_data.parent_id

    await db.commit()
    await db.refresh(category)

    return category


# =========================================================
# ADMIN: UPLOAD OR REPLACE CATEGORY ICON
# =========================================================

@router.post(
    "/{category_id}/icon",
    response_model=CategoryResponse,
)
async def upload_icon(
    category_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    require_admin(current_user)

    result = await db.execute(
        select(Category).where(
            Category.id == category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    contents, extension, content_type = (
        await validate_icon(file)
    )

    old_icon_url = category.icon_url

    new_icon_url = save_icon(
        contents=contents,
        extension=extension,
        content_type=content_type,
        category_id=category.id,
        request=request,
    )

    category.icon_url = new_icon_url

    try:
        await db.commit()
        await db.refresh(category)

    except Exception:
        await db.rollback()
        delete_category_icon(new_icon_url)
        raise

    if old_icon_url and old_icon_url != new_icon_url:
        delete_category_icon(old_icon_url)

    return category


# =========================================================
# ADMIN: DELETE CATEGORY ICON
# SUBCATEGORY ICON CAN BE DELETED
# MAIN CATEGORY ICON CANNOT BE DELETED
# =========================================================

@router.delete(
    "/{category_id}/icon",
    response_model=CategoryResponse,
)
async def delete_icon(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    require_admin(current_user)

    result = await db.execute(
        select(Category).where(
            Category.id == category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    if category.parent_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Main category icon cannot be deleted. "
                "Upload a replacement icon instead."
            ),
        )

    if not category.icon_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category does not have an icon",
        )

    old_icon_url = category.icon_url

    category.icon_url = None

    try:
        await db.commit()
        await db.refresh(category)

    except Exception:
        await db.rollback()
        raise

    delete_category_icon(old_icon_url)

    return category


# =========================================================
# ACTIVATE CATEGORY
# =========================================================

@router.patch(
    "/{category_id}/activate",
    response_model=CategoryResponse,
)
async def activate_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    require_admin(current_user)

    result = await db.execute(
        select(Category).where(
            Category.id == category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    category.is_active = True

    await db.commit()
    await db.refresh(category)

    return category


# =========================================================
# DEACTIVATE CATEGORY
# =========================================================

@router.patch(
    "/{category_id}/deactivate",
    response_model=CategoryResponse,
)
async def deactivate_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    require_admin(current_user)

    result = await db.execute(
        select(Category).where(
            Category.id == category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    category.is_active = False

    await db.commit()
    await db.refresh(category)

    return category


# =========================================================
# DELETE CATEGORY
# =========================================================

@router.delete(
    "/{category_id}",
)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    require_admin(current_user)

    result = await db.execute(
        select(Category).where(
            Category.id == category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    children_result = await db.execute(
        select(Category.id)
        .where(
            Category.parent_id == category_id
        )
        .limit(1)
    )

    if children_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot delete this category because "
                "it has child categories. "
                "Delete or move the child categories first."
            ),
        )

    old_icon_url = category.icon_url

    await db.delete(category)
    await db.commit()

    if old_icon_url:
        delete_category_icon(old_icon_url)

    return {
        "success": True,
        "message": "Category deleted successfully",
    }
