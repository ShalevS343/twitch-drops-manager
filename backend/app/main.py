from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.progress import (
    shutdown_profile_refresh,
    start_profile_refresh_warmup,
)
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db import SessionLocal, engine, init_db
from app.core.logging import configure_logging
from app.core.middleware import CSRFMiddleware, NoStoreMiddleware
from app.core.security import prune_expired_sessions

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    await init_db()
    async with SessionLocal() as session:
        await prune_expired_sessions(session)
    start_profile_refresh_warmup()
    try:
        yield
    finally:
        await shutdown_profile_refresh()
        await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(NoStoreMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Starlette runs the last-added middleware outermost. TrustedHost must see the
# raw Host header before same-origin/CSRF decisions use it.
if settings.allowed_host_list:
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list
    )
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"app": settings.app_name, "docs": "/docs", "api": settings.api_prefix}
