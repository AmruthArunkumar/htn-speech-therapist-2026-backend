from collections.abc import AsyncGenerator

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import get_settings

settings = get_settings()
client = AsyncIOMotorClient(settings.mongodb_url)
database = client[settings.mongodb_database]


async def get_database() -> AsyncGenerator[AsyncIOMotorDatabase, None]:
    yield database


async def close_database() -> None:
    client.close()