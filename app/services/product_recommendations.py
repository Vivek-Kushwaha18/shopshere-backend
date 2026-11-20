
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.product import Product
from app.models.user import User
from app.models.user_product_view import UserProductView

MAX_VIEW_HISTORY = 50
DEFAULT_RECOMMENDATIONS = 12


def available_product_filter():
    return (
        Product.is_active.is_(True),
        Product.is_deleted.is_(False),
        Product.stock > 0,
    )


async def record_product_view(
    db: AsyncSession,
    user_id: int,
    product_id: int,
) -> dict:
    try:
        # Serialize history updates for this user.
        await db.execute(
            select(User.id)
            .where(User.id == user_id)
            .with_for_update()
        )

        result = await db.execute(
            select(Product.id).where(
                Product.id == product_id,
                Product.is_active.is_(True),
                Product.is_deleted.is_(False),
            )
        )

        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )

        result = await db.execute(
            select(UserProductView).where(
                UserProductView.user_id == user_id,
                UserProductView.product_id == product_id,
            )
        )

        existing_view = result.scalar_one_or_none()

        if existing_view is None:
            existing_view = UserProductView(
                user_id=user_id,
                product_id=product_id,
            )
            db.add(existing_view)

        existing_view.viewed_at = datetime.now(
            timezone.utc
        )

        await db.flush()

        result = await db.execute(
            select(UserProductView.id)
            .where(UserProductView.user_id == user_id)
            .order_by(
                UserProductView.viewed_at.desc(),
                UserProductView.id.desc(),
            )
        )

        view_ids = list(result.scalars().all())

        expired_ids = view_ids[MAX_VIEW_HISTORY:]

        if expired_ids:
            await db.execute(
                delete(UserProductView).where(
                    UserProductView.id.in_(expired_ids)
                )
            )

        await db.commit()

        return {
            "message": "Product view recorded",
            "product_id": product_id,
            "history_count": min(
                len(view_ids),
                MAX_VIEW_HISTORY,
            ),
            "history_limit": MAX_VIEW_HISTORY,
        }

    except Exception:
        await db.rollback()
        raise


async def get_recent_product_ids(
    db: AsyncSession,
    user_id: int,
    limit: int = MAX_VIEW_HISTORY,
) -> list[int]:
    result = await db.execute(
        select(UserProductView.product_id)
        .where(UserProductView.user_id == user_id)
        .order_by(
            UserProductView.viewed_at.desc(),
            UserProductView.id.desc(),
        )
        .limit(limit)
    )

    return list(result.scalars().all())


async def get_recently_viewed_products(
    db: AsyncSession,
    user_id: int,
):
    from app.api.product import product_load_options

    product_ids = await get_recent_product_ids(
        db,
        user_id,
    )

    if not product_ids:
        return []

    result = await db.execute(
        select(Product)
        .options(*product_load_options())
        .where(
            Product.id.in_(product_ids),
            Product.is_active.is_(True),
            Product.is_deleted.is_(False),
        )
    )

    products = {
        product.id: product
        for product in result.scalars().all()
    }

    return [
        products[product_id]
        for product_id in product_ids
        if product_id in products
    ]


async def get_category_relationships(
    db: AsyncSession,
):
    result = await db.execute(
        select(Category).where(
            Category.is_active.is_(True)
        )
    )

    categories = result.scalars().all()

    return {
        category.id: category.parent_id
        for category in categories
    }


def get_category_family(
    category_id: int,
    parents: dict[int, int | None],
) -> set[int]:
    if category_id not in parents:
        return set()

    root = category_id
    visited = set()

    while (
        root in parents
        and parents[root] is not None
        and root not in visited
    ):
        visited.add(root)
        root = parents[root]

    family = {root}
    changed = True

    while changed:
        changed = False

        for child_id, parent_id in parents.items():
            if (
                parent_id in family
                and child_id not in family
            ):
                family.add(child_id)
                changed = True

    return family


async def get_recommended_products(
    db: AsyncSession,
    user_id: int | None = None,
    product_id: int | None = None,
    limit: int = DEFAULT_RECOMMENDATIONS,
):
    from app.api.product import product_load_options

    current_product = None

    if product_id is not None:
        result = await db.execute(
            select(Product).where(
                Product.id == product_id,
                Product.is_active.is_(True),
                Product.is_deleted.is_(False),
            )
        )

        current_product = result.scalar_one_or_none()

        if current_product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )

    history_ids = []

    if user_id is not None:
        history_ids = await get_recent_product_ids(
            db,
            user_id,
        )

    history_categories = []

    if history_ids:
        result = await db.execute(
            select(Product.id, Product.category_id)
            .where(Product.id.in_(history_ids))
        )

        category_by_product = {
            row.id: row.category_id
            for row in result.all()
        }

        history_categories = [
            category_by_product[viewed_id]
            for viewed_id in history_ids
            if viewed_id in category_by_product
        ]

    parents = await get_category_relationships(db)

    related_categories = set()

    if current_product is not None:
        related_categories = get_category_family(
            current_product.category_id,
            parents,
        )

    # Retrieve actual available products.
    query = (
        select(Product)
        .options(*product_load_options())
        .where(*available_product_filter())
    )

    if product_id is not None:
        query = query.where(
            Product.id != product_id
        )

    result = await db.execute(query)

    candidates = result.scalars().all()

    # Recent interests receive more weight.
    interest_scores: dict[int, float] = {}

    for index, category_id in enumerate(
        history_categories
    ):
        interest_scores[category_id] = (
            interest_scores.get(category_id, 0)
            + max(1.0, 5.0 - index * 0.1)
        )

    def recommendation_score(product: Product):
        score = 0.0

        if current_product is not None:
            if (
                product.category_id
                == current_product.category_id
            ):
                score += 100

                if current_product.price > 0:
                    price_difference = abs(
                        product.price
                        - current_product.price
                    ) / current_product.price

                    score += max(
                        0,
                        20 - price_difference * 20,
                    )

            elif product.category_id in related_categories:
                score += 45

        score += interest_scores.get(
            product.category_id,
            0,
        ) * 5

        score += min(
            float(product.rating or 0),
            5.0,
        ) * 3

        score += min(
            int(product.reviews_count or 0),
            100,
        ) * 0.05

        return score

    candidates.sort(
        key=lambda product: (
            recommendation_score(product),
            product.created_at,
            product.id,
        ),
        reverse=True,
    )

    return candidates[:limit]
