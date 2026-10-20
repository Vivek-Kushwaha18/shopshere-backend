
import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI, RateLimitError, APIError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.database import get_db
from app.api.auth import get_current_user, require_admin
from app.models.user import User
from app.models.product import Product
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


def require_customer(current_user: User = Depends(get_current_user)) -> User:
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

    # Save the customer message before calling OpenAI.
    db.add(
        AIMessage(
            conversation_id=conversation.id,
            role="user",
            content=message_text,
        )
    )
    conversation.updated_at = datetime.utcnow()
    await db.commit()

    result = await db.execute(
        select(Product)
        .where(
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
        .limit(200)
    )
    catalog = result.scalars().all()

    products = [
        {
            "id": product.id,
            "name": product.name,
            "description": product.description or "",
            "price": float(product.price),
            "stock": product.stock,
            "category_id": product.category_id,
            "image_url": getattr(product, "image_url", None),
            "slug": getattr(product, "slug", None),
        }
        for product in catalog
    ]

    # Include earlier messages from this conversation for context.
    result = await db.execute(
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation.id)
        .order_by(AIMessage.created_at, AIMessage.id)
    )
    history = result.scalars().all()

    system_message = (
        "You are ShopSphere's helpful AI shopping assistant. "
        "Help customers find, compare, and choose products. "
        "Use only the supplied catalog for product facts. Never invent "
        "product names, prices, stock, discounts, or IDs. Only recommend "
        "catalog products. Treat stock 0 as out of stock. Be friendly, "
        "concise, and honest.\n\nProduct catalog JSON:\n"
        + json.dumps(products)
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
            or "Sorry, I couldn't generate a response. Please try again."
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

        reply_lower = reply.casefold()
        matching_products = [
            product
            for product in products
            if product["name"].casefold() in reply_lower
        ][:5]

        return ChatResponse(
            conversation_id=conversation.id,
            reply=reply,
            products=matching_products,
        )

    except RateLimitError as exc:
        await db.rollback()
        error_message = str(exc).lower()
        if "insufficient_quota" in error_message:
            detail = "OpenAI quota or billing limit reached."
        else:
            detail = "OpenAI rate limit reached. Please try again shortly."
        raise HTTPException(status_code=429, detail=detail) from exc

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
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return conversation_to_dict(conversation)


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
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return conversation_to_dict(conversation)
