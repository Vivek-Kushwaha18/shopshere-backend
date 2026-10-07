import json
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
from app.models.product_option_group import ProductOptionGroup
from app.models.product_option_value import ProductOptionValue
from app.models.product_variant import ProductVariant
from app.models.product_variant_value import ProductVariantValue
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
# PRODUCT RESPONSE LOAD OPTIONS
# =========================================================

def product_load_options():
    return (
        selectinload(Product.images),
        selectinload(Product.option_groups)
        .selectinload(ProductOptionGroup.values),
        selectinload(Product.variants)
        .selectinload(ProductVariant.option_values),
        selectinload(Product.variants)
        .selectinload(ProductVariant.images),
    )


# =========================================================
# IMAGE VALIDATION
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
            detail="At least one product image is required.",
        )

    if len(files) > MAX_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"You can upload a maximum of "
                f"{MAX_IMAGES} images."
            ),
        )

    validated_images = []

    for uploaded_file in files:
        if uploaded_file.content_type not in ALLOWED_IMAGE_TYPES:
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
                uploaded_file.filename or "image",
            )
        )

    return validated_images


# =========================================================
# PRODUCT SLUG
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

        existing_product = result.scalar_one_or_none()

        if existing_product is None:
            return slug

        slug = f"{base_slug}-{counter}"
        counter += 1


# =========================================================
# PRODUCT PERMISSION
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
            *product_load_options()
        )
        .where(
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    if search:
        search_value = f"%{search}%"

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
            Product.category_id == category_id
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
            *product_load_options()
        )
        .where(
            Product.seller_id == current_user.id,
            Product.is_deleted.is_(False),
        )
    )

    return result.scalars().all()


# =========================================================
# PUBLIC: GET PRODUCTS BY CATEGORY
#
# Returns products from:
#
# Selected category
# + children
# + grandchildren
# + deeper descendants
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

    category = category_result.scalar_one_or_none()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    categories_result = await db.execute(
        select(Category).where(
            Category.is_active.is_(True),
        )
    )

    categories = categories_result.scalars().all()

    category_ids = {category.id}

    changed = True

    while changed:
        changed = False

        for item in categories:
            if (
                item.parent_id in category_ids
                and item.id not in category_ids
            ):
                category_ids.add(item.id)
                changed = True

    result = await db.execute(
        select(Product)
        .options(
            *product_load_options()
        )
        .where(
            Product.category_id.in_(category_ids),
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

    configuration: Optional[str] = Form(
        default=None
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
    # Basic validation
    # -----------------------------------------------------

    clean_name = name.strip()

    if not clean_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product name cannot be empty.",
        )

    if price < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product price cannot be negative.",
        )

    if (
        original_price is not None
        and original_price < 0
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Original price cannot be negative."
            ),
        )

    if stock < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock cannot be negative.",
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
            detail="Invalid primary image selection.",
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

    category = category_result.scalar_one_or_none()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found.",
        )

    # -----------------------------------------------------
    # Parse configuration
    # -----------------------------------------------------

    option_groups_data = []
    variants_data = []

    if configuration:
        try:
            configuration_data = json.loads(
                configuration
            )
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Invalid product configuration JSON."
                ),
            )

        if not isinstance(
            configuration_data,
            dict,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Product configuration "
                    "must be a JSON object."
                ),
            )

        option_groups_data = (
            configuration_data.get(
                "option_groups",
                [],
            )
        )

        variants_data = (
            configuration_data.get(
                "variants",
                [],
            )
        )

        if not isinstance(
            option_groups_data,
            list,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "option_groups must be an array."
                ),
            )

        if not isinstance(
            variants_data,
            list,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "variants must be an array."
                ),
            )

    # -----------------------------------------------------
    # Normalize option groups
    # -----------------------------------------------------

    normalized_groups = []

    group_names = set()

    for group_index, group_data in enumerate(
        option_groups_data
    ):
        if not isinstance(
            group_data,
            dict,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid option group "
                    f"at index {group_index}."
                ),
            )

        group_name = str(
            group_data.get(
                "name",
                "",
            )
        ).strip()

        if not group_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Option group "
                    f"{group_index + 1} "
                    f"must have a name."
                ),
            )

        group_name_key = group_name.lower()

        if group_name_key in group_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Duplicate option group: "
                    f"{group_name}."
                ),
            )

        group_names.add(group_name_key)

        values_data = group_data.get(
            "values",
            [],
        )

        if not isinstance(
            values_data,
            list,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Values for option group "
                    f"{group_name} must be an array."
                ),
            )

        if not values_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Option group "
                    f"{group_name} must have "
                    f"at least one value."
                ),
            )

        normalized_values = []

        value_names = set()

        for value_index, value_data in enumerate(
            values_data
        ):
            if not isinstance(
                value_data,
                dict,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Invalid value in "
                        f"option group "
                        f"{group_name}."
                    ),
                )

            value_name = str(
                value_data.get(
                    "value",
                    "",
                )
            ).strip()

            if not value_name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Option value "
                        f"{value_index + 1} "
                        f"in {group_name} "
                        f"cannot be empty."
                    ),
                )

            value_key = value_name.lower()

            if value_key in value_names:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Duplicate value "
                        f"{value_name} in "
                        f"{group_name}."
                    ),
                )

            value_names.add(value_key)

            normalized_values.append(
                {
                    "value": value_name,
                    "sort_order": value_data.get(
                        "sort_order",
                        value_index,
                    ),
                }
            )

        normalized_groups.append(
            {
                "name": group_name,
                "sort_order": group_data.get(
                    "sort_order",
                    group_index,
                ),
                "values": normalized_values,
            }
        )

    # -----------------------------------------------------
    # Variants cannot exist without option groups
    # -----------------------------------------------------

    if variants_data and not normalized_groups:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Variants cannot be created "
                "without option groups."
            ),
        )

    # -----------------------------------------------------
    # Normalize variants
    # -----------------------------------------------------

    normalized_variants = []

    variant_combinations = set()

    expected_group_count = len(
        normalized_groups
    )

    for variant_index, variant_data in enumerate(
        variants_data
    ):
        if not isinstance(
            variant_data,
            dict,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid variant "
                    f"at index {variant_index}."
                ),
            )

        variant_price = variant_data.get(
            "price"
        )

        if variant_price is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Variant "
                    f"{variant_index + 1} "
                    f"must have a price."
                ),
            )

        try:
            variant_price = float(
                variant_price
            )
        except (
            TypeError,
            ValueError,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid price for "
                    f"variant "
                    f"{variant_index + 1}."
                ),
            )

        if variant_price < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Price for variant "
                    f"{variant_index + 1} "
                    f"cannot be negative."
                ),
            )

        variant_original_price = (
            variant_data.get(
                "original_price"
            )
        )

        if variant_original_price is not None:
            try:
                variant_original_price = float(
                    variant_original_price
                )
            except (
                TypeError,
                ValueError,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Invalid original price "
                        f"for variant "
                        f"{variant_index + 1}."
                    ),
                )

            if variant_original_price < 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Original price for "
                        f"variant "
                        f"{variant_index + 1} "
                        f"cannot be negative."
                    ),
                )

        variant_stock = variant_data.get(
            "stock",
            0,
        )

        try:
            variant_stock = int(
                variant_stock
            )
        except (
            TypeError,
            ValueError,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid stock for "
                    f"variant "
                    f"{variant_index + 1}."
                ),
            )

        if variant_stock < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Stock for variant "
                    f"{variant_index + 1} "
                    f"cannot be negative."
                ),
            )

        option_value_ids = variant_data.get(
            "option_value_ids",
            [],
        )

        if not isinstance(
            option_value_ids,
            list,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"option_value_ids for "
                    f"variant "
                    f"{variant_index + 1} "
                    f"must be an array."
                ),
            )

        try:
            option_value_ids = [
                int(value_id)
                for value_id in option_value_ids
            ]
        except (
            TypeError,
            ValueError,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid option value ID "
                    f"in variant "
                    f"{variant_index + 1}."
                ),
            )

        if len(option_value_ids) != expected_group_count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Variant "
                    f"{variant_index + 1} must "
                    f"contain exactly "
                    f"{expected_group_count} "
                    f"option values."
                ),
            )

        if len(set(option_value_ids)) != len(
            option_value_ids
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Variant "
                    f"{variant_index + 1} "
                    f"contains duplicate "
                    f"option values."
                ),
            )

        combination = tuple(
            sorted(option_value_ids)
        )

        if combination in variant_combinations:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Duplicate variant "
                    f"combination at variant "
                    f"{variant_index + 1}."
                ),
            )

        variant_combinations.add(
            combination
        )

        sku = variant_data.get("sku")

        if sku is not None:
            sku = str(sku).strip()

            if not sku:
                sku = None

        normalized_variants.append(
            {
                "sku": sku,
                "price": variant_price,
                "original_price": (
                    variant_original_price
                ),
                "stock": variant_stock,
                "is_active": bool(
                    variant_data.get(
                        "is_active",
                        True,
                    )
                ),
                "option_value_ids": (
                    option_value_ids
                ),
            }
        )

    # -----------------------------------------------------
    # Validate images
    # -----------------------------------------------------

    validated_images = (
        await read_and_validate_images(file)
    )

    # -----------------------------------------------------
    # Generate product slug
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
        # Create option groups
        # -------------------------------------------------

        option_value_map = {}

        for group_data in normalized_groups:
            option_group = ProductOptionGroup(
                product_id=product.id,
                name=group_data["name"],
                sort_order=group_data[
                    "sort_order"
                ],
            )

            db.add(option_group)

            await db.flush()

            for value_data in group_data[
                "values"
            ]:
                option_value = ProductOptionValue(
                    option_group_id=option_group.id,
                    value=value_data["value"],
                    sort_order=value_data[
                        "sort_order"
                    ],
                )

                db.add(option_value)

                await db.flush()

                option_value_map[
                    option_value.id
                ] = option_group.id

        # -------------------------------------------------
        # Create variants
        # -------------------------------------------------

        for variant_data in normalized_variants:
            option_value_ids = (
                variant_data[
                    "option_value_ids"
                ]
            )

            selected_group_ids = set()

            for option_value_id in option_value_ids:
                option_group_id = (
                    option_value_map.get(
                        option_value_id
                    )
                )

                if option_group_id is None:
                    raise HTTPException(
                        status_code=(
                            status.HTTP_400_BAD_REQUEST
                        ),
                        detail=(
                            "Variant contains "
                            "an invalid option value."
                        ),
                    )

                if option_group_id in selected_group_ids:
                    raise HTTPException(
                        status_code=(
                            status.HTTP_400_BAD_REQUEST
                        ),
                        detail=(
                            "A variant cannot "
                            "contain multiple "
                            "values from the "
                            "same option group."
                        ),
                    )

                selected_group_ids.add(
                    option_group_id
                )

            if len(selected_group_ids) != expected_group_count:
                raise HTTPException(
                    status_code=(
                        status.HTTP_400_BAD_REQUEST
                    ),
                    detail=(
                        "Every variant must "
                        "contain one value "
                        "from every option group."
                    ),
                )

            variant = ProductVariant(
                product_id=product.id,
                sku=variant_data["sku"],
                price=variant_data["price"],
                original_price=variant_data[
                    "original_price"
                ],
                stock=variant_data["stock"],
                is_active=variant_data[
                    "is_active"
                ],
            )

            db.add(variant)

            await db.flush()

            for option_value_id in option_value_ids:
                variant_value = ProductVariantValue(
                    variant_id=variant.id,
                    option_value_id=option_value_id,
                )

                db.add(variant_value)

        # -------------------------------------------------
        # Upload product images
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
                index == primary_image_index
            )

            if is_primary:
                product.image_url = image_url

            product_image = ProductImage(
                product_id=product.id,
                variant_id=None,
                image_url=image_url,
                view_type=None,
                sort_order=index,
                is_primary=is_primary,
            )

            db.add(product_image)

        # -------------------------------------------------
        # Commit
        # -------------------------------------------------

        await db.commit()

        # -------------------------------------------------
        # Reload product
        # -------------------------------------------------

        result = await db.execute(
            select(Product)
            .options(
                *product_load_options()
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
# PUBLIC: GET PRODUCT BY SLUG
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
            *product_load_options()
        )
        .where(
            Product.slug == slug,
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return product


# =========================================================
# PUBLIC: GET PRODUCT BY ID
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
            *product_load_options()
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return product


# =========================================================
# SELLER / ADMIN: UPDATE PRODUCT
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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
        .options(
            *product_load_options()
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
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
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found",
            )

    # -----------------------------------------------------
    # Validate numeric values
    # -----------------------------------------------------

    if (
        product_data.price is not None
        and product_data.price < 0
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product price cannot be negative.",
        )

    if (
        product_data.original_price is not None
        and product_data.original_price < 0
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Original price cannot be negative."
            ),
        )

    if (
        product_data.stock is not None
        and product_data.stock < 0
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock cannot be negative.",
        )

    # -----------------------------------------------------
    # Update fields
    # -----------------------------------------------------

    update_data = product_data.model_dump(
        exclude_unset=True
    )

    # Slug is intentionally unchanged.
    update_data.pop(
        "slug",
        None,
    )

    for field, value in update_data.items():
        if field == "name" and value is not None:
            value = value.strip()

            if not value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
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
            *product_load_options()
        )
        .where(
            Product.id == product.id
        )
    )

    return result.scalar_one()


# =========================================================
# SELLER / ADMIN: REPLACE PRODUCT IMAGES
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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
        .options(
            *product_load_options()
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
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
            detail="Invalid primary image selection.",
        )

    validated_images = (
        await read_and_validate_images(file)
    )

    old_product_images = [
        image
        for image in product.images
        if image.variant_id is None
    ]

    old_image_urls = [
        image.image_url
        for image in old_product_images
    ]

    uploaded_urls: list[str] = []

    try:
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
                index == primary_image_index
            )

            new_images.append(
                ProductImage(
                    product_id=product.id,
                    variant_id=None,
                    image_url=image_url,
                    view_type=None,
                    sort_order=index,
                    is_primary=is_primary,
                )
            )

            if is_primary:
                product.image_url = image_url

        for old_image in old_product_images:
            await db.delete(old_image)

        for new_image in new_images:
            db.add(new_image)

        await db.commit()

        for old_url in old_image_urls:
            delete_product_image(
                old_url
            )

        result = await db.execute(
            select(Product)
            .options(
                *product_load_options()
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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
        .options(
            *product_load_options()
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    check_product_owner(
        product,
        current_user,
    )

    image_result = await db.execute(
        select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.product_id == product_id,
            ProductImage.variant_id.is_(None),
        )
    )

    image = image_result.scalar_one_or_none()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product image not found",
        )

    for product_image in product.images:
        if product_image.variant_id is None:
            product_image.is_primary = False

    image.is_primary = True

    product.image_url = image.image_url

    await db.commit()

    result = await db.execute(
        select(Product)
        .options(
            *product_load_options()
        )
        .where(
            Product.id == product.id
        )
    )

    return result.scalar_one()


# =========================================================
# SELLER / ADMIN: DELETE PRODUCT IMAGE
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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
        .options(
            *product_load_options()
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    check_product_owner(
        product,
        current_user,
    )

    image_result = await db.execute(
        select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.product_id == product_id,
            ProductImage.variant_id.is_(None),
        )
    )

    image = image_result.scalar_one_or_none()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product image not found",
        )

    product_level_images = [
        item
        for item in product.images
        if item.variant_id is None
    ]

    if len(product_level_images) <= 1:
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

    if was_primary:
        remaining_images = [
            item
            for item in product_level_images
            if item.id != image.id
        ]

        if remaining_images:
            new_primary = remaining_images[0]

            new_primary.is_primary = True

            product.image_url = (
                new_primary.image_url
            )

    await db.commit()

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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
        .options(
            *product_load_options()
        )
        .where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
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
            *product_load_options()
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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
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