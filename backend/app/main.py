from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db import engine, init_db
from app.core.logging import configure_logging
from app.core.middleware import CSRFMiddleware, NoStoreMiddleware
from app.services.profile_service import get_profile_service

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    await init_db()
    await get_profile_service().warm_up()
    try:
        yield
    finally:
        await get_profile_service().shutdown()
        await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
if settings.allowed_host_list:
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list
    )
app.add_middleware(NoStoreMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"app": settings.app_name, "docs": "/docs", "api": settings.api_prefix}
