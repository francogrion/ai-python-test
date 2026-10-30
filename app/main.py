import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from api import router
from config import Settings
from pipeline import Pipeline
from provider import ProviderClient, create_http_client
from rate_limiter import RateLimiter
from store import InMemoryStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        http = create_http_client(settings, transport)
        provider = ProviderClient(http, settings.notify_read_timeout)
        limiter = RateLimiter(settings.notify_rate_per_second)
        app.state.store = InMemoryStore()
        app.state.pipeline = Pipeline(app.state.store, provider, limiter, settings)
        await app.state.pipeline.start()
        yield
        await app.state.pipeline.stop()
        await http.aclose()

    app = FastAPI(title="Notification Service (Technical Test)", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
