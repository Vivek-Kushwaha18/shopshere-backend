from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database.database import get_db
from app.models.category import Category
from app.models.user import User
from app.schemas.category import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
)
from app.utils.slug import slugify


router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


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

    # Prevent circular category structure
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
        .where(
            Category.is_active.is_(True)
        )
        .order_by(Category.name)
    )

    return result.scalars().all()


# =========================================================
# GET ONE ACTIVE CATEGORY BY SLUG
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
# GET ONE ACTIVE CATEGORY BY ID
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
# =========================================================

@router.post(
    "/",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    category_data: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can create categories",
        )

    name = category_data.name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name cannot be empty",
        )

    # Check duplicate name
    result = await db.execute(
        select(Category).where(
            Category.name.ilike(name)
        )
    )

    existing_category = result.scalar_one_or_none()

    if existing_category is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category already exists",
        )

    # Validate parent
    await validate_parent_category(
        db=db,
        parent_id=category_data.parent_id,
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
            category_data.description.strip()
            if category_data.description
            else None
        ),
        parent_id=category_data.parent_id,
        is_active=True,
    )

    db.add(category)

    await db.commit()
    await db.refresh(category)

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
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can update categories",
        )

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

        duplicate_category = (
            duplicate_result.scalar_one_or_none()
        )

        if duplicate_category is not None:
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

        category.parent_id = category_data.parent_id

    await db.commit()
    await db.refresh(category)

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
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can activate categories",
        )

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
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can deactivate categories",
        )

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
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can delete categories",
        )

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

    # Check children
    children_result = await db.execute(
        select(Category.id)
        .where(
            Category.parent_id == category_id
        )
        .limit(1)
    )

    has_children = (
        children_result.scalar_one_or_none()
        is not None
    )

    if has_children:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot delete this category because "
                "it has child categories. "
                "Delete or move the child categories first."
            ),
        )

    await db.delete(category)
    await db.commit()

    return {
        "success": True,
        "message": "Category deleted successfully",
    }