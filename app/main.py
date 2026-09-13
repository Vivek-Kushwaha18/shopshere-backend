
from fastapi import FastAPI


# for apis
from app.api.auth import router as auth_router


from app.api.products import router as products_router



#for database or models
from app.database.database import engine


from app.models.product import Base
from app.models.user import User
from app.models.product import Product


#Base.metadata.create_all


app = FastAPI (

tittle ="shopshere API",

)
# also api part
app.include_router(auth_router)

app.include_router(products_router)

# data base part
@app.on_event("startup")
async def create_tables():

    async with engine.begin() as connection:

        await connection.run_sync(
            Base.metadata.create_all
        )
# comman
@app.get("/")
async def root():
    return {"message": "ShopSphere API is running"}