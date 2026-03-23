"""Lone Wolf CYOA application entry point."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.dependencies import VersionConflictError
from app.limiter import limiter
from app.routers import auth, books, characters, game_objects, gameplay, leaderboards, reports
from app.routers.admin import auth as admin_auth
from app.routers.admin import content as admin_content
from app.routers.admin import reports as admin_reports
from app.routers.admin import users as admin_users
from app.routers.ui import auth as ui_auth
from app.routers.ui import browse as ui_browse
from app.routers.ui import characters as ui_characters
from app.routers.ui import gameplay as ui_gameplay
from app.ui_dependencies import LoginRequired, login_required_handler

_STATIC_DIR = Path(__file__).parent.parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Lone Wolf CYOA", version="0.1.0")

    # Static files (vendored Pico CSS, HTMX, custom app.css)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # UI auth redirect — converts LoginRequired to 303 → /ui/login
    app.add_exception_handler(LoginRequired, login_required_handler)  # type: ignore[arg-type]

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

    # JSON API routers
    app.include_router(auth.router)
    app.include_router(characters.router)
    app.include_router(gameplay.router)
    app.include_router(books.router)
    app.include_router(game_objects.router)
    app.include_router(leaderboards.router)
    app.include_router(reports.router)
    app.include_router(admin_auth.router)
    app.include_router(admin_users.router)
    app.include_router(admin_content.router)
    app.include_router(admin_reports.router)

    # UI routers (HTMX + Jinja2)
    app.include_router(ui_auth.router)
    app.include_router(ui_browse.router)
    app.include_router(ui_characters.router)
    app.include_router(ui_gameplay.router)

    return app


app = create_app()
