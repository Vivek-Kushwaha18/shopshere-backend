from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database.database import get_db
from app.models.address import Address
from app.models.user import User
from app.schemas.address import (
    AddressCreate,
    AddressResponse,
    AddressUpdate,
)


router = APIRouter(
    prefix="/addresses",
    tags=["Addresses"],
)


# =========================================================
# HELPER - SET DEFAULT ADDRESS
# =========================================================

async def clear_default_addresses(
    db: AsyncSession,
    user_id: int,
) -> None:
    result = await db.execute(
        select(Address).where(
            Address.user_id == user_id,
            Address.is_default.is_(True),
        )
    )

    addresses = result.scalars().all()

    for address in addresses:
        address.is_default = False


# =========================================================
# GET MY ADDRESSES
# =========================================================

@router.get(
    "/",
    response_model=list[AddressResponse],
)
async def get_my_addresses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Address)
        .where(
            Address.user_id == current_user.id
        )
        .order_by(
            Address.is_default.desc(),
            Address.created_at.desc(),
        )
    )

    return result.scalars().all()


# =========================================================
# GET SINGLE ADDRESS
# =========================================================

@router.get(
    "/{address_id}",
    response_model=AddressResponse,
)
async def get_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Address).where(
            Address.id == address_id,
            Address.user_id == current_user.id,
        )
    )

    address = result.scalar_one_or_none()

    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found.",
        )

    return address


# =========================================================
# CREATE ADDRESS
# =========================================================

@router.post(
    "/",
    response_model=AddressResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_address(
    address_data: AddressCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing_result = await db.execute(
        select(Address.id).where(
            Address.user_id == current_user.id
        )
    )

    existing_address = existing_result.first()

    if not existing_address:
        address_data.is_default = True

    if address_data.is_default:
        await clear_default_addresses(
            db,
            current_user.id,
        )

    address = Address(
        user_id=current_user.id,
        full_name=address_data.full_name,
        phone=address_data.phone,
        address_line=address_data.address_line,
        city=address_data.city,
        state=address_data.state,
        postal_code=address_data.postal_code,
        address_type=address_data.address_type,
        is_default=address_data.is_default,
    )

    db.add(address)

    await db.commit()
    await db.refresh(address)

    return address


# =========================================================
# UPDATE ADDRESS
# =========================================================

@router.put(
    "/{address_id}",
    response_model=AddressResponse,
)
async def update_address(
    address_id: int,
    address_data: AddressUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Address).where(
            Address.id == address_id,
            Address.user_id == current_user.id,
        )
    )

    address = result.scalar_one_or_none()

    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found.",
        )

    if address_data.is_default:
        await clear_default_addresses(
            db,
            current_user.id,
        )

    address.full_name = address_data.full_name
    address.phone = address_data.phone
    address.address_line = address_data.address_line
    address.city = address_data.city
    address.state = address_data.state
    address.postal_code = address_data.postal_code
    address.address_type = address_data.address_type
    address.is_default = address_data.is_default

    await db.commit()
    await db.refresh(address)

    return address


# =========================================================
# SET DEFAULT ADDRESS
# =========================================================

@router.patch(
    "/{address_id}/default",
    response_model=AddressResponse,
)
async def set_default_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Address).where(
            Address.id == address_id,
            Address.user_id == current_user.id,
        )
    )

    address = result.scalar_one_or_none()

    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found.",
        )

    await clear_default_addresses(
        db,
        current_user.id,
    )

    address.is_default = True

    await db.commit()
    await db.refresh(address)

    return address


# =========================================================
# DELETE ADDRESS
# =========================================================

@router.delete(
    "/{address_id}",
)
async def delete_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Address).where(
            Address.id == address_id,
            Address.user_id == current_user.id,
        )
    )

    address = result.scalar_one_or_none()

    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found.",
        )

    was_default = address.is_default

    await db.delete(address)

    await db.commit()

    if was_default:
        remaining_result = await db.execute(
            select(Address)
            .where(
                Address.user_id == current_user.id
            )
            .order_by(
                Address.created_at.asc()
            )
        )

        remaining_addresses = (
            remaining_result.scalars().all()
        )

        if remaining_addresses:
            remaining_addresses[0].is_default = True

            await db.commit()

    return {
        "success": True,
        "message": "Address deleted successfully.",
    }