from contextlib import asynccontextmanager

from fastapi import FastAPI

from database.database import close_database, database
from database.service import ensure_indexes
from routes.router import router as auth_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_indexes(database)
    yield
    await close_database()


app = FastAPI(title="HTN Speech Therapist API", lifespan=lifespan)
app.include_router(auth_router)