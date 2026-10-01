import asyncio

from sqlalchemy import select

from app.database.database import AsyncSessionLocal
from app.models.category import Category
from app.models.product import Product
from app.utils.slug import slugify


async def generate_unique_slug(
    session,
    model,
    name: str,
    current_id: int,
) -> str:
    base_slug = slugify(name)

    if not base_slug:
        base_slug = f"item-{current_id}"

    slug = base_slug
    counter = 2

    while True:
        result = await session.execute(
            select(model).where(
                model.slug == slug,
                model.id != current_id,
            )
        )

        existing = result.scalar_one_or_none()

        if existing is None:
            return slug

        slug = f"{base_slug}-{counter}"
        counter += 1


async def generate_category_slugs(session) -> None:
    result = await session.execute(
        select(Category).order_by(Category.id)
    )

    categories = result.scalars().all()

    for category in categories:
        if category.slug:
            continue

        category.slug = await generate_unique_slug(
            session,
            Category,
            category.name,
            category.id,
        )

        print(
            f"Category {category.id}: "
            f"{category.name} -> {category.slug}"
        )


async def generate_product_slugs(session) -> None:
    result = await session.execute(
        select(Product).order_by(Product.id)
    )

    products = result.scalars().all()

    for product in products:
        if product.slug:
            continue

        product.slug = await generate_unique_slug(
            session,
            Product,
            product.name,
            product.id,
        )

        print(
            f"Product {product.id}: "
            f"{product.name} -> {product.slug}"
        )


async def main():
    async with AsyncSessionLocal() as session:
        try:
            await generate_category_slugs(session)
            await generate_product_slugs(session)

            await session.commit()

            print("\nSlugs generated successfully.")

        except Exception:
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())