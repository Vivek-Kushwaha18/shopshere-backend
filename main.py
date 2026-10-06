from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.category import router as category_router
from app.api.product import router as product_router
from app.api.auth import router as auth_router
from app.api.cart import router as cart_router
from app.api.order import router as order_router
from app.api.address import router as address_router
from app.api.payment import router as payment_router
from app.api.wishlist import router as wishlist_router
from app.api.reports import router as reports_router
from app.api.coupon import router as coupon_router
from app.api.customer_coupon import router as customer_coupon_router
from app.api.review import router as review_router
from app.api.shipment import router as shipment_router


app = FastAPI(
    title="ShopSphere API",
    description="AI-Powered Multi-Vendor E-Commerce Platform API",
    version="1.0.0",
)


# ============================================================
# STATIC UPLOADED FILES
# ============================================================

app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://shopshere-frontend-theta.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROUTERS
# ============================================================

app.include_router(category_router)
app.include_router(product_router)
app.include_router(auth_router)
app.include_router(cart_router)
app.include_router(order_router)
app.include_router(address_router)
app.include_router(payment_router)
app.include_router(wishlist_router)
app.include_router(reports_router)
app.include_router(coupon_router)
app.include_router(customer_coupon_router)
app.include_router(review_router)
app.include_router(shipment_router)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():
    return {
        "message": "ShopSphere API is running"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }