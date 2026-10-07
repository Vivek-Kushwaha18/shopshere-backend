from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user
from app.database.database import get_db
from app.models.cart import Cart
from app.models.cart_item import CartItem
from app.models.product import Product
from app.models.product_option_value import ProductOptionValue
from app.models.product_variant import ProductVariant
from app.models.product_variant_value import ProductVariantValue
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
            .selectinload(CartItem.product),
            selectinload(Cart.items)
            .selectinload(CartItem.variant)
            .selectinload(ProductVariant.option_values)
            .selectinload(ProductVariantValue.option_value)
            .selectinload(ProductOptionValue.option_group),
            selectinload(Cart.items)
            .selectinload(CartItem.variant)
            .selectinload(ProductVariant.images),
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

        variant = item.variant

        # -------------------------------------------------
        # Determine current price and stock
        # -------------------------------------------------

        if variant is not None:
            current_price = float(variant.price)

            current_original_price = (
                float(variant.original_price)
                if variant.original_price is not None
                else None
            )

            current_stock = variant.stock

        else:
            current_price = float(product.price)

            current_original_price = (
                float(product.original_price)
                if product.original_price is not None
                else None
            )

            current_stock = product.stock

        item_total = current_price * item.quantity

        total += item_total
        total_items += item.quantity

        # -------------------------------------------------
        # Build variant information
        # -------------------------------------------------

        variant_data = None

        if variant is not None:
            option_values = []

            for variant_value in variant.option_values:
                option_value = variant_value.option_value

                if option_value is None:
                    continue

                option_group = option_value.option_group

                option_values.append(
                    {
                        "id": option_value.id,
                        "option_group_id": option_value.option_group_id,
                        "option_group_name": (
                            option_group.name
                            if option_group is not None
                            else "Option"
                        ),
                        "value": option_value.value,
                    }
                )

            variant_images = [
                {
                    "id": image.id,
                    "image_url": image.image_url,
                    "view_type": image.view_type,
                    "sort_order": image.sort_order,
                    "is_primary": image.is_primary,
                }
                for image in variant.images
            ]

            variant_data = {
                "id": variant.id,
                "sku": variant.sku,
                "price": current_price,
                "original_price": current_original_price,
                "stock": current_stock,
                "is_active": variant.is_active,
                "option_values": option_values,
                "images": variant_images,
            }

        items.append(
            {
                "id": item.id,
                "product_id": product.id,
                "variant_id": (
                    variant.id
                    if variant is not None
                    else None
                ),
                "quantity": item.quantity,
                "product": {
                    "id": product.id,
                    "slug": product.slug,
                    "name": product.name,
                    "description": product.description,
                    "price": current_price,
                    "original_price": current_original_price,
                    "stock": current_stock,
                    "image_url": product.image_url,
                    "rating": product.rating,
                    "reviews_count": product.reviews_count,
                },
                "variant": variant_data,
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
    variant_id: int | None = None,
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

    # -----------------------------------------------------
    # Get variant if selected
    # -----------------------------------------------------

    variant = None

    if variant_id is not None:
        result = await db.execute(
            select(ProductVariant).where(
                ProductVariant.id == variant_id,
                ProductVariant.product_id == product.id,
                ProductVariant.is_active.is_(True),
            )
        )

        variant = result.scalar_one_or_none()

        if variant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Selected product variant not found",
            )

    else:
        # -------------------------------------------------
        # If this product has variants, a variant must be
        # selected before adding it to the cart.
        # -------------------------------------------------

        result = await db.execute(
            select(ProductVariant.id)
            .where(
                ProductVariant.product_id == product.id,
                ProductVariant.is_active.is_(True),
            )
            .limit(1)
        )

        has_active_variant = result.scalar_one_or_none()

        if has_active_variant is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please select a product variant",
            )

    # -----------------------------------------------------
    # Determine stock
    # -----------------------------------------------------

    available_stock = (
        variant.stock
        if variant is not None
        else product.stock
    )

    if available_stock <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product is out of stock",
        )

    if quantity > available_stock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {available_stock} items are available",
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

    cart_item_query = select(CartItem).where(
        CartItem.cart_id == cart.id,
        CartItem.product_id == product.id,
    )

    if variant_id is None:
        cart_item_query = cart_item_query.where(
            CartItem.variant_id.is_(None)
        )
    else:
        cart_item_query = cart_item_query.where(
            CartItem.variant_id == variant_id
        )

    result = await db.execute(cart_item_query)

    cart_item = result.scalar_one_or_none()

    # -----------------------------------------------------
    # Existing cart item
    # -----------------------------------------------------

    if cart_item is not None:
        new_quantity = cart_item.quantity + quantity

        if new_quantity > available_stock:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only {available_stock} items are available",
            )

        cart_item.quantity = new_quantity

    # -----------------------------------------------------
    # New cart item
    # -----------------------------------------------------

    else:
        cart_item = CartItem(
            cart_id=cart.id,
            product_id=product.id,
            variant_id=variant_id,
            quantity=quantity,
        )

        db.add(cart_item)

    await db.commit()

    return {
        "success": True,
        "message": "Product added to cart successfully",
        "data": {
            "product_id": product.id,
            "variant_id": variant_id,
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
            selectinload(CartItem.product),
            selectinload(CartItem.variant),
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
    variant = cart_item.variant

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # -----------------------------------------------------
    # Check product
    # -----------------------------------------------------

    if product.is_deleted or not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This product is no longer available",
        )

    # -----------------------------------------------------
    # Check variant
    # -----------------------------------------------------

    if variant is not None:
        if not variant.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This product variant is no longer available",
            )

        available_stock = variant.stock

    else:
        available_stock = product.stock

    # -----------------------------------------------------
    # Check stock
    # -----------------------------------------------------

    if available_stock <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product is out of stock",
        )

    if quantity > available_stock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {available_stock} items are available",
        )

    cart_item.quantity = quantity

    await db.commit()

    return {
        "success": True,
        "message": "Cart item updated successfully",
        "data": {
            "item_id": cart_item.id,
            "product_id": product.id,
            "variant_id": (
                variant.id
                if variant is not None
                else None
            ),
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