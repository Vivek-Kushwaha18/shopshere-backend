from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user
from app.database.database import get_db
from app.models.cart import Cart
from app.models.cart_item import CartItem
from app.models.product import Product
from app.models.user import User


router = APIRouter(
    prefix="/api/cart",
    tags=["Cart"],
)


# =========================================================
# GET CURRENT USER CART
# =========================================================

@router.get("/")
async def get_cart(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Cart)
        .options(
            selectinload(Cart.items)
            .selectinload(CartItem.product)
        )
        .where(
            Cart.user_id == current_user.id
        )
    )

    cart = result.scalar_one_or_none()

    if cart is None:
        cart = Cart(
            user_id=current_user.id
        )

        db.add(cart)

        await db.commit()
        await db.refresh(cart)

        cart.items = []

    items = []

    total = 0.0
    total_items = 0

    for item in cart.items:

        product = item.product

        if product is None:
            continue

        item_total = float(product.price) * item.quantity

        total += item_total
        total_items += item.quantity

        items.append(
            {
                "id": item.id,
                "product_id": product.id,
                "quantity": item.quantity,
                "product": {
                    "id": product.id,
                    "name": product.name,
                    "description": product.description,
                    "price": float(product.price),
                    "original_price": (
                        float(product.original_price)
                        if product.original_price is not None
                        else None
                    ),
                    "stock": product.stock,
                    "image_url": product.image_url,
                    "rating": product.rating,
                    "reviews_count": product.reviews_count,
                },
                "item_total": item_total,
            }
        )

    return {
        "success": True,
        "data": {
            "cart_id": cart.id,
            "items": items,
            "total_items": total_items,
            "total": total,
        },
    }


# =========================================================
# ADD PRODUCT TO CART
# =========================================================

@router.post(
    "/items",
    status_code=status.HTTP_201_CREATED,
)
async def add_to_cart(
    product_id: int,
    quantity: int = 1,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if quantity < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity must be at least 1",
        )

    # -----------------------------------------------------
    # Get product
    # -----------------------------------------------------

    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    product = result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if product.stock <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product is out of stock",
        )

    # -----------------------------------------------------
    # Get or create cart
    # -----------------------------------------------------

    result = await db.execute(
        select(Cart).where(
            Cart.user_id == current_user.id
        )
    )

    cart = result.scalar_one_or_none()

    if cart is None:

        cart = Cart(
            user_id=current_user.id
        )

        db.add(cart)

        await db.flush()

    # -----------------------------------------------------
    # Check existing cart item
    # -----------------------------------------------------

    result = await db.execute(
        select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.product_id == product.id,
        )
    )

    cart_item = result.scalar_one_or_none()

    if cart_item is not None:

        new_quantity = cart_item.quantity + quantity

        if new_quantity > product.stock:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Only {product.stock} items are available"
                ),
            )

        cart_item.quantity = new_quantity

    else:

        if quantity > product.stock:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Only {product.stock} items are available"
                ),
            )

        cart_item = CartItem(
            cart_id=cart.id,
            product_id=product.id,
            quantity=quantity,
        )

        db.add(cart_item)

    await db.commit()

    return {
        "success": True,
        "message": "Product added to cart successfully",
        "data": {
            "product_id": product.id,
            "quantity": cart_item.quantity,
        },
    }


# =========================================================
# UPDATE CART ITEM QUANTITY
# =========================================================

@router.patch("/items/{item_id}")
async def update_cart_item(
    item_id: int,
    quantity: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if quantity < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity must be at least 1",
        )

    # -----------------------------------------------------
    # Get cart
    # -----------------------------------------------------

    result = await db.execute(
        select(Cart).where(
            Cart.user_id == current_user.id
        )
    )

    cart = result.scalar_one_or_none()

    if cart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart not found",
        )

    # -----------------------------------------------------
    # Get cart item
    # -----------------------------------------------------

    result = await db.execute(
        select(CartItem)
        .options(
            selectinload(CartItem.product)
        )
        .where(
            CartItem.id == item_id,
            CartItem.cart_id == cart.id,
        )
    )

    cart_item = result.scalar_one_or_none()

    if cart_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart item not found",
        )

    product = cart_item.product

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if product.is_deleted or not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This product is no longer available",
        )

    if quantity > product.stock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Only {product.stock} items are available"
            ),
        )

    cart_item.quantity = quantity

    await db.commit()

    return {
        "success": True,
        "message": "Cart item updated successfully",
        "data": {
            "item_id": cart_item.id,
            "product_id": product.id,
            "quantity": cart_item.quantity,
        },
    }


# =========================================================
# REMOVE ITEM FROM CART
# =========================================================

@router.delete("/items/{item_id}")
async def remove_cart_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # -----------------------------------------------------
    # Get user's cart
    # -----------------------------------------------------

    result = await db.execute(
        select(Cart).where(
            Cart.user_id == current_user.id
        )
    )

    cart = result.scalar_one_or_none()

    if cart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart not found",
        )

    # -----------------------------------------------------
    # Get cart item belonging to this cart
    # -----------------------------------------------------

    result = await db.execute(
        select(CartItem).where(
            CartItem.id == item_id,
            CartItem.cart_id == cart.id,
        )
    )

    cart_item = result.scalar_one_or_none()

    if cart_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart item not found",
        )

    await db.delete(cart_item)

    await db.commit()

    return {
        "success": True,
        "message": "Product removed from cart successfully",
    }


# =========================================================
# CLEAR CART
# =========================================================

@router.delete("/")
async def clear_cart(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Cart)
        .options(
            selectinload(Cart.items)
        )
        .where(
            Cart.user_id == current_user.id
        )
    )

    cart = result.scalar_one_or_none()

    if cart is None:
        return {
            "success": True,
            "message": "Cart is already empty",
        }

    for item in cart.items:
        await db.delete(item)

    await db.commit()

    return {
        "success": True,
        "message": "Cart cleared successfully",
    }