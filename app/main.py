"""Lone Wolf CYOA application entry point."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.dependencies import VersionConflictError
from app.limiter import limiter
from app.routers import auth, characters, gameplay
from app.routers.admin import auth as admin_auth
from app.routers.admin import users as admin_users


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Lone Wolf CYOA", version="0.1.0")

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Version conflict handler — produces a flat JSON body per spec
    @app.exception_handler(VersionConflictError)
    async def version_conflict_handler(request: Request, exc: VersionConflictError):  # noqa: ARG001
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Version mismatch — character state has changed",
                "error_code": "VERSION_MISMATCH",
                "current_version": exc.current_version,
            },
            headers={"X-Current-Version": str(exc.current_version)},
        )

    # Routers
    app.include_router(auth.router)
    app.include_router(characters.router)
    app.include_router(gameplay.router)
    app.include_router(admin_auth.router)
    app.include_router(admin_users.router)

    return app


app = create_app()
