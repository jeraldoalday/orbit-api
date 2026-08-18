from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import AccessLogMiddleware, configure_logging
from app.core.middleware import RequestIDMiddleware
from app.core.openapi import (
    API_DESCRIPTION,
    API_TITLE,
    API_VERSION,
    COMMON_RESPONSES,
    TAGS_METADATA,
    generate_operation_id,
)
from app.core.rate_limit import RateLimitMiddleware

settings = get_settings()

configure_logging(settings.log_level)

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    # The interactive docs are useful in development and an unnecessary
    # description of the attack surface in production.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    generate_unique_id_function=generate_operation_id,
)

# Starlette runs middleware in reverse registration order, so the request id
# is assigned before rate limiting and a 429 still carries its correlation id.
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIDMiddleware)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix="/api/v1", responses=COMMON_RESPONSES)
