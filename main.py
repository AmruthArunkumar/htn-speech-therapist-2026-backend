from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.database import close_database, database
from database.service import ensure_indexes
from routes.router import router as auth_router
from routes.speech import router as speech_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # The speech pipeline is stateless, so an unreachable database degrades the
    # auth routes rather than taking the whole API down.
    try:
        await ensure_indexes(database)
    except Exception:  # noqa: BLE001
        logger.warning("Database unavailable; auth routes will fail", exc_info=True)
    yield
    await close_database()


app = FastAPI(title="HTN Speech Therapist API", lifespan=lifespan)

# Permissive for development; tighten to the Expo app's origins before shipping.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(speech_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
