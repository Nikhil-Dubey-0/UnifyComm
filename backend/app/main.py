"""FastAPI app factory. Run: uv run uvicorn app.main:app --port 8000 (one worker)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.llm import build_llm
from app.api import auth, compliance, conversations, customers, messages, simulator, system, ws
from app.channels.registry import build_registry
from app.compliance.rules import build_rules
from app.config import Settings, get_settings, setup_process
from app.db import asyncpg_dsn, make_engine, make_sessionmaker
from app.errors import DomainError
from app.realtime.bridge import EventBridge
from app.realtime.hub import Hub

log = logging.getLogger(__name__)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        message = f"{where}: {first.get('msg', 'invalid request')}" if where else "Invalid request."
        return _error(422, "validation_error", message)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail))


def create_app(settings: Settings | None = None, *, null_pool: bool = False) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url, null_pool=null_pool)
    hub = Hub()
    bridge = EventBridge(asyncpg_dsn(settings.database_url), hub)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await bridge.start()
        try:
            yield
        finally:
            await bridge.stop()
            await engine.dispose()

    app = FastAPI(title="UnifyComm API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.hub = hub
    app.state.bridge = bridge
    app.state.registry = build_registry()
    app.state.rules = build_rules(settings.promo_window_start, settings.promo_window_end)
    app.state.llm = build_llm(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _install_error_handlers(app)
    for module in (auth, system, simulator, conversations, messages, customers, compliance):
        app.include_router(module.router, prefix="/api")
    app.include_router(auth.agents_router, prefix="/api")
    app.include_router(ws.router)
    return app


def _make_default_app() -> FastAPI:
    settings = get_settings()
    setup_process(settings)
    if settings.jwt_secret.get_secret_value() == "change-me":
        log.warning("JWT_SECRET is the placeholder value; set a random secret in .env")
    return create_app(settings)


app = _make_default_app()
