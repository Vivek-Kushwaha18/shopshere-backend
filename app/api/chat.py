
import json
import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI, RateLimitError, APIError
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.database import get_db
from app.api.auth import get_current_user, require_admin
from app.models.user import User
from app.models.product import Product
from app.models.category import Category
from app.models.ai_conversation import AIConversation, AIMessage


router = APIRouter(
    prefix="/api/chat",
    tags=["AI Shopping Assistant"],
)

admin_router = APIRouter(
    prefix="/api/admin/ai-conversations",
    tags=["Admin AI Conversations"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None


class ChatProduct(BaseModel):
    id: int
    name: str
    description: str
    price: float
    stock: int
    category_id: int
    image_url: str | None = None
    slug: str | None = None


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    products: list[ChatProduct]


def require_customer(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != "customer":
        raise HTTPException(
            status_code=403,
            detail="Only customers can use the AI shopping assistant.",
        )
    return current_user


def conversation_to_dict(conversation: AIConversation) -> dict:
    return {
        "id": conversation.id,
        "user_id": conversation.user_id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in conversation.messages
        ],
    }


# ---------------------------------------------------------------------
# PRODUCT SEARCH
# ---------------------------------------------------------------------

PRICE_NUMBER = r"\d[\d,]*(?:\.\d+)?"

PRICE_WORDS = {
    "under",
    "below",
    "less",
    "than",
    "over",
    "above",
    "more",
    "greater",
    "between",
    "upto",
    "minimum",
    "maximum",
    "least",
    "most",
    "cheaper",
    "expensive",
    "price",
    "priced",
    "cost",
    "costing",
    "range",
    "budget",
}

STOP_WORDS = {
    "a",
    "an",
    "the",
    "me",
    "show",
    "find",
    "search",
    "give",
    "get",
    "list",
    "display",
    "want",
    "need",
    "looking",
    "for",
    "some",
    "any",
    "all",
    "products",
    "product",
    "items",
    "item",
    "please",
    "and",
    "with",
    "in",
    "on",
    "of",
    "to",
    "my",
    "your",
    "i",
    "am",
    "is",
    "are",
    "have",
    "has",
    "do",
    "you",
    "can",
    "recommend",
    "suggest",
    "find",
    "me",
    "rs",
    "inr",
    "rupees",
    "rupee",
    "only",
    "available",
    "shop",
    "shopsphere",
}


def parse_price_filters(message: str) -> dict:
    """
    Parse price constraints without hardcoding any particular amount.

    Examples:
      shirts under ₹500
      shoes below 1,000
      products above 100
      products between 100 and 500
      products up to ₹10,000
      products at least 50
    """
    text = message.lower()
    text = text.replace("₹", " ")
    text = re.sub(r"\brs\.?\s*", " ", text)
    text = re.sub(r"\binr\b|\brupees?\b", " ", text)

    result = {
        "min_price": None,
        "max_price": None,
        "min_inclusive": True,
        "max_inclusive": False,
        "has_price_filter": False,
    }

    between_match = re.search(
        rf"\bbetween\s+({PRICE_NUMBER})\s+"
        rf"(?:and|to|-)\s*({PRICE_NUMBER})",
        text,
    )

    if between_match:
        result["min_price"] = float(
            between_match.group(1).replace(",", "")
        )
        result["max_price"] = float(
            between_match.group(2).replace(",", "")
        )
        result["min_inclusive"] = True
        result["max_inclusive"] = True
        result["has_price_filter"] = True
        return result

    lower_match = re.search(
        rf"\b(?:under|below|less than|cheaper than|"
        rf"maximum of|up to|upto|at most|not more than)\s*"
        rf"({PRICE_NUMBER})",
        text,
    )

    upper_match = re.search(
        rf"\b(?:above|over|more than|greater than|"
        rf"minimum of|at least|not less than)\s*"
        rf"({PRICE_NUMBER})",
        text,
    )

    if lower_match:
        result["max_price"] = float(
            lower_match.group(1).replace(",", "")
        )
        result["max_inclusive"] = bool(
            re.search(
                r"\b(?:maximum of|up to|upto|at most|not more than)\b",
                lower_match.group(0),
            )
        )
        result["has_price_filter"] = True

    if upper_match:
        result["min_price"] = float(
            upper_match.group(1).replace(",", "")
        )
        result["min_inclusive"] = bool(
            re.search(
                r"\b(?:minimum of|at least|not less than)\b",
                upper_match.group(0),
            )
        )
        result["has_price_filter"] = True

    # Handle exact-price requests such as "products costing 500".
    if not result["has_price_filter"]:
        exact_match = re.search(
            rf"\b(?:costing|priced at|price is|costs?|for)\s+"
            rf"({PRICE_NUMBER})\b",
            text,
        )

        if exact_match:
            amount = float(
                exact_match.group(1).replace(",", "")
            )
            result["min_price"] = amount
            result["max_price"] = amount
            result["min_inclusive"] = True
            result["max_inclusive"] = True
            result["has_price_filter"] = True

    return result


def extract_search_keywords(message: str) -> list[str]:
    """
    Extract product-name, color, and descriptive keywords.
    Remove conversational words and price expressions.
    """
    text = message.lower().replace("₹", " ")
    text = re.sub(r"\brs\.?\s*", " ", text)
    text = re.sub(r"\binr\b|\brupees?\b", " ", text)

    text = re.sub(
        rf"\bbetween\s+{PRICE_NUMBER}\s+(?:and|to|-)\s*"
        rf"{PRICE_NUMBER}",
        " ",
        text,
    )

    text = re.sub(
        rf"\b(?:under|below|less than|cheaper than|above|over|"
        rf"more than|greater than|up to|upto|at most|at least|"
        rf"minimum of|maximum of|not more than|not less than|"
        rf"priced at|price is|costing|costs?|for)\s*"
        rf"{PRICE_NUMBER}",
        " ",
        text,
    )

    # Remove standalone amounts so they are not treated as product names.
    text = re.sub(rf"\b{PRICE_NUMBER}\b", " ", text)

    words = re.findall(r"[a-zA-Z]+", text)

    keywords = [
        word
        for word in words
        if word not in STOP_WORDS and word not in PRICE_WORDS
    ]

    # Preserve keyword order while removing duplicates.
    return list(dict.fromkeys(keywords))


async def search_database_products(
    db: AsyncSession,
    message: str,
) -> list[Product]:
    """
    Apply search filters in PostgreSQL.
    Product cards are selected from database records, never from AI text.
    """
    price_filters = parse_price_filters(message)
    keywords = extract_search_keywords(message)

    statement = (
        select(Product)
        .join(Category, Product.category_id == Category.id)
        .where(
            Product.is_active.is_(True),
            Product.is_deleted.is_(False),
            Category.is_active.is_(True),
        )
    )

    if price_filters["min_price"] is not None:
        if price_filters["min_inclusive"]:
            statement = statement.where(
                Product.price >= price_filters["min_price"]
            )
        else:
            statement = statement.where(
                Product.price > price_filters["min_price"]
            )

    if price_filters["max_price"] is not None:
        if price_filters["max_inclusive"]:
            statement = statement.where(
                Product.price <= price_filters["max_price"]
            )
        else:
            statement = statement.where(
                Product.price < price_filters["max_price"]
            )

    # Every meaningful keyword must match at least one searchable field.
    # For example, "black shirts" must match both "black" and "shirts".
    for keyword in keywords:
        pattern = f"%{keyword}%"

        statement = statement.where(
            or_(
                Product.name.ilike(pattern),
                Product.description.ilike(pattern),
                Category.name.ilike(pattern),
                Category.slug.ilike(pattern),
            )
        )

    statement = statement.order_by(
        Product.name.asc(),
        Product.id.asc(),
    )

    result = await db.execute(statement)
    return list(result.scalars().unique().all())


def product_to_dict(product: Product) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description or "",
        "price": float(product.price),
        "stock": product.stock,
        "category_id": product.category_id,
        "image_url": product.image_url,
        "slug": product.slug,
    }


# ---------------------------------------------------------------------
# AI CHAT
# ---------------------------------------------------------------------

@router.post("", response_model=ChatResponse)
async def chat_with_shopping_assistant(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_customer),
):
    message_text = request.message.strip()

    if not message_text:
        raise HTTPException(
            status_code=422,
            detail="Message cannot be empty.",
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI assistant is not configured. Set OPENAI_API_KEY.",
        )

    if request.conversation_id is not None:
        result = await db.execute(
            select(AIConversation).where(
                AIConversation.id == request.conversation_id,
                AIConversation.user_id == current_user.id,
            )
        )
        conversation = result.scalar_one_or_none()

        if conversation is None:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found.",
            )
    else:
        conversation = AIConversation(
            user_id=current_user.id,
            title=message_text[:200],
        )
        db.add(conversation)
        await db.flush()

    db.add(
        AIMessage(
            conversation_id=conversation.id,
            role="user",
            content=message_text,
        )
    )
    conversation.updated_at = datetime.utcnow()
    await db.commit()

    # Search the database first. Do not let the AI invent or select products.
    try:
        matching_records = await search_database_products(
            db,
            message_text,
        )
    except Exception as exc:
        await db.rollback()
        print(
            f"ShopSphere product search error: "
            f"{type(exc).__name__}: {exc}"
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to search products right now.",
        ) from exc

    matching_products = [
        product_to_dict(product)
        for product in matching_records
    ]

    # Load previous conversation messages for context.
    result = await db.execute(
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation.id)
        .order_by(AIMessage.created_at, AIMessage.id)
    )
    history = result.scalars().all()

    # The AI receives only actual matching records.
    # Limit catalog context sent to OpenAI, but return all matching records
    # in the response so the frontend can display the complete search result.
    catalog_for_ai = matching_products[:30]

    if not matching_products:
        system_message = (
            "You are ShopSphere's AI shopping assistant. "
            "The database search found zero matching active products for "
            "the customer's latest request. Clearly explain that no "
            "matching products were found. Do not invent products, names, "
            "prices, stock, or availability. You may suggest that the "
            "customer try another product name or price range."
        )
    else:
        system_message = (
            "You are ShopSphere's AI shopping assistant. "
            "Help customers understand the products returned by the "
            "database search. The supplied products are the only products "
            "you may discuss as search results. Never invent product names, "
            "prices, stock, discounts, or IDs. Be friendly and concise. "
            "If a product has stock 0, say it is out of stock. "
            "The database has found "
            f"{len(matching_products)} matching product(s). "
            "The following JSON contains up to 30 matching records for "
            "your response. The API separately returns all matching "
            "products to the frontend.\n\n"
            "Matching product records:\n"
            + json.dumps(catalog_for_ai, ensure_ascii=False)
        )

    messages = [{"role": "system", "content": system_message}]
    messages.extend(
        {"role": item.role, "content": item.content}
        for item in history
        if item.role in ("user", "assistant")
    )

    client = AsyncOpenAI(api_key=api_key)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=500,
        )

        reply = (
            response.choices[0].message.content
            or "Here are the matching products from ShopSphere."
        )

        # Guarantee a clear no-results response if the database returned none.
        if not matching_products:
            reply = (
                "I couldn't find any active products matching your search. "
                "Try a different product name, category, or price range."
            )

        db.add(
            AIMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=reply,
            )
        )
        conversation.updated_at = datetime.utcnow()
        await db.commit()

        return ChatResponse(
            conversation_id=conversation.id,
            reply=reply,
            products=[
                ChatProduct(**product)
                for product in matching_products
            ],
        )

    except RateLimitError as exc:
        await db.rollback()
        error_message = str(exc).lower()

        if "insufficient_quota" in error_message:
            detail = "OpenAI quota or billing limit reached."
        else:
            detail = "OpenAI rate limit reached. Please try again shortly."

        raise HTTPException(
            status_code=429,
            detail=detail,
        ) from exc

    except APIError as exc:
        await db.rollback()
        print(f"ShopSphere OpenAI error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=502,
            detail="OpenAI could not process the request.",
        ) from exc

    except Exception as exc:
        await db.rollback()
        print(f"ShopSphere chat error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred in the AI assistant.",
        ) from exc

    finally:
        await client.close()


# ---------------------------------------------------------------------
# CUSTOMER CONVERSATION HISTORY
# ---------------------------------------------------------------------

@router.get("/history")
async def get_customer_conversation_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_customer),
):
    result = await db.execute(
        select(AIConversation)
        .where(AIConversation.user_id == current_user.id)
        .order_by(AIConversation.updated_at.desc())
    )
    conversations = result.scalars().all()

    return [
        {
            "id": item.id,
            "title": item.title,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in conversations
    ]


@router.get("/history/{conversation_id}")
async def get_customer_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_customer),
):
    result = await db.execute(
        select(AIConversation)
        .options(selectinload(AIConversation.messages))
        .where(
            AIConversation.id == conversation_id,
            AIConversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return conversation_to_dict(conversation)


# ---------------------------------------------------------------------
# ADMIN CONVERSATION HISTORY
# ---------------------------------------------------------------------

@admin_router.get("")
async def admin_list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(
        select(AIConversation)
        .order_by(AIConversation.updated_at.desc())
    )
    conversations = result.scalars().all()

    return [
        {
            "id": item.id,
            "user_id": item.user_id,
            "title": item.title,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in conversations
    ]


@admin_router.get("/{conversation_id}")
async def admin_get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(
        select(AIConversation)
        .options(selectinload(AIConversation.messages))
        .where(AIConversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return conversation_to_dict(conversation)
