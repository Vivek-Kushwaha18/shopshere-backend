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


router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


# =========================================================
# GET ALL ACTIVE CATEGORIES
#
# Public
# Customer
# Seller
# Admin
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
# GET ONE ACTIVE CATEGORY
#
# Public
# Customer
# Seller
# Admin
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
#
# ADMIN ONLY
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
    # -----------------------------------------------------
    # ADMIN CHECK
    # -----------------------------------------------------

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can create categories",
        )

    # -----------------------------------------------------
    # CLEAN DATA
    # -----------------------------------------------------

    name = category_data.name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name cannot be empty",
        )

    # -----------------------------------------------------
    # CHECK DUPLICATE
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # CREATE
    # -----------------------------------------------------

    category = Category(
        name=name,
        description=(
            category_data.description.strip()
            if category_data.description
            else None
        ),
        is_active=True,
    )

    db.add(category)

    await db.commit()
    await db.refresh(category)

    return category


# =========================================================
# UPDATE CATEGORY
#
# ADMIN ONLY
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
    # -----------------------------------------------------
    # ADMIN CHECK
    # -----------------------------------------------------

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can update categories",
        )

    # -----------------------------------------------------
    # FIND CATEGORY
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # UPDATE NAME
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # UPDATE DESCRIPTION
    # -----------------------------------------------------

    if category_data.description is not None:
        category.description = (
            category_data.description.strip()
            or None
        )

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

    await db.commit()
    await db.refresh(category)

    return category


# =========================================================
# ACTIVATE CATEGORY
#
# ADMIN ONLY
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
#
# ADMIN ONLY
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
#
# ADMIN ONLY
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

    await db.delete(category)

    await db.commit()

    return {
        "success": True,
        "message": "Category deleted successfully",
    }