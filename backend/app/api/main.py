"""应用入口：统一错误信封（全局 exception handler 覆盖 FastAPI 默认 {"detail":...}）、
生命周期内启动调度器（单 worker 前提，见 4.1）。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routers import crawl, papers, search, stats, taxonomies
from app.api.middleware import LocalWriteGuard
from app.config import settings
from app.db import get_engine, get_session
from app.services.pipeline import CrawlPipeline
from app.services.scheduler import start_scheduler
from app.services.site_sync import SiteSync

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    if settings.initialize_on_startup:
        from app.bootstrap import initialize_database
        initialize_database(engine)
    pipeline = CrawlPipeline(get_session)
    sync = SiteSync(get_session, pipeline)
    pipeline.on_complete = sync.refresh
    app.state.pipeline = pipeline
    app.state.site_sync = sync
    sync.start()
    app.state.scheduler = start_scheduler(pipeline) if settings.scheduler_enabled else None
    try:
        yield
    finally:
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await sync.shutdown()
        await pipeline.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="LitHub Pavilion", description="知汇于此，文藏此殿", version="1.2.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:5180", "http://127.0.0.1:5180",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LocalWriteGuard)
    for router in (papers.router, search.router, taxonomies.router, stats.router, crawl.router):
        app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(x) for x in err.get("loc", [])), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_PARAM", "message": "请求参数校验失败", "details": details}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_request: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict):
            code = exc.detail.get("code", "HTTP_ERROR")
            content = {"error": {"code": code, "message": exc.detail.get("message", "")}}
            for key in ("official_url", "oa_url"):
                if key in exc.detail and exc.detail[key] is not None:
                    content["error"][key] = exc.detail[key]
        else:
            code_by_status = {
                400: "INVALID_PARAM", 403: "FORBIDDEN", 404: "NOT_FOUND",
                409: "CONFLICT", 416: "RANGE_NOT_SATISFIABLE", 500: "INTERNAL",
            }
            content = {
                "error": {
                    "code": code_by_status.get(exc.status_code, "HTTP_ERROR"),
                    "message": str(exc.detail),
                }
            }
        headers = getattr(exc, "headers", None) or {}
        return JSONResponse(status_code=exc.status_code, content=content, headers=headers)

    @app.exception_handler(Exception)
    async def _unhandled_handler(_request: Request, exc: Exception):
        logging.getLogger("papertracker.api").exception("未处理异常")
        del exc
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "服务器内部错误"}},
        )

    @app.get("/api/health", tags=["health"])
    def health():
        # 纯 ORM 探测数据库连通性（不拼接任何 SQL 字符串）
        db_ok = True
        try:
            from app.models import Paper

            session = get_session()
            try:
                session.query(Paper.id).limit(1).all()
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            db_ok = False
        pipeline = getattr(app.state, "pipeline", None)
        body = {
            "status": "ok" if db_ok else "degraded",
            "db": "ok" if db_ok else "error",
            "crawl_running": bool(pipeline and pipeline.status.running),
            "last_run_id": pipeline.status.run_id if pipeline else None,
        }
        return JSONResponse(status_code=200 if db_ok else 503, content=body)

    return app


app = create_app()
