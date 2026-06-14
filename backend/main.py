import asyncio
import json
import logging
import sys
import time
import uuid
import warnings
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware


class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


class CrestJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, cls=_DecimalEncoder, ensure_ascii=False).encode("utf-8")

sys.path.insert(0, str(Path(__file__).parent))

from shared.logging_config import configure_logging, set_request_context
configure_logging()

from auth import router as auth_router, setup_oauth, get_session_secret, is_authenticated
from modules.portfolio.routes import router as portfolio_router
from modules.market_monitor.routes import router as market_monitor_router
from modules.swing_detector.routes import router as swing_detector_router
from modules.charts.routes import router as charts_router
from modules.watchlist.routes import router as watchlist_router
from modules.user.routes import router as user_router
from modules.alerts.routes import router as alerts_router
from modules.dashboard.routes import router as dashboard_router
from modules.ws.routes import router as ws_router, get_ws_manager
from modules.settings.routes import router as settings_router
from modules.kite.routes import router as kite_router
from modules.research.routes import router as research_router
from modules.custom_index.routes import router as custom_index_router

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.json"
_FRONTEND    = Path(__file__).parent.parent / "frontend"


def _compute_asset_version() -> str:
    globs = list(_FRONTEND.glob("js/**/*.js")) + list(_FRONTEND.glob("css/**/*.css"))
    if not globs:
        return "1"
    return str(int(max(p.stat().st_mtime for p in globs)))


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        user_id = str(request.session.get("user_id", "")) if hasattr(request, "session") else ""
        set_request_context(request_id, user_id)
        t0 = time.monotonic()
        response = await call_next(request)
        latency_ms = round((time.monotonic() - t0) * 1000)
        log.info(
            "request",
            extra={
                "event": "http_request",
                "endpoint": str(request.url.path),
                "method": request.method,
                "status": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        return response


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return json.load(f)


async def _broadcast_loop() -> None:
    """Drain price_queue and broadcast to WS clients."""
    from shared.price_channel import price_queue
    manager = get_ws_manager()
    while True:
        try:
            batch = await price_queue.get()
            if manager.active_count() > 0:
                await manager.broadcast(batch)
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("broadcast_loop error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import init_db
    from scripts.seed_db import auto_seed
    from scheduler import create_scheduler
    from shared.price_channel import set_event_loop
    log.info("Initialising database…")
    init_db()
    auto_seed()
    log.info("Database ready.")
    set_event_loop(asyncio.get_event_loop())
    broadcast_task = asyncio.create_task(_broadcast_loop())
    scheduler = create_scheduler()
    scheduler.start()
    log.info("Scheduler started (%d jobs)", len(scheduler.get_jobs()))
    yield
    scheduler.shutdown(wait=False)
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass
    log.info("Scheduler stopped.")


app = FastAPI(title="Crest", docs_url=None, redoc_url=None, lifespan=lifespan,
              default_response_class=CrestJSONResponse)

import os as _os
cfg = _load_config()
_https_only = _os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true"
# RequestLoggingMiddleware added first (inner); SessionMiddleware added second (outer).
# Starlette LIFO: request flows SessionMiddleware → RequestLoggingMiddleware → handler,
# so session is already populated when we read it for context binding.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret(),
    https_only=_https_only,
    same_site="strict",
    max_age=604800,
)

setup_oauth()
app.include_router(auth_router)
app.include_router(portfolio_router)
app.include_router(market_monitor_router)
app.include_router(swing_detector_router)
app.include_router(charts_router)
app.include_router(watchlist_router)
app.include_router(user_router)
app.include_router(alerts_router)
app.include_router(dashboard_router)
app.include_router(ws_router)
app.include_router(settings_router)
app.include_router(kite_router)
app.include_router(research_router)
app.include_router(custom_index_router)

_JS_DIR  = _FRONTEND / "js"
_CSS_DIR = _FRONTEND / "css"
if _JS_DIR.exists():
    app.mount("/js",  StaticFiles(directory=str(_JS_DIR)),  name="js")
if _CSS_DIR.exists():
    app.mount("/css", StaticFiles(directory=str(_CSS_DIR)), name="css")


@app.get("/api/version")
async def api_version():
    return {"version": _compute_asset_version()}


@app.get("/login.html")
async def login_page():
    return FileResponse(_FRONTEND / "login.html")


@app.get("/")
async def root(request: Request):
    if not is_authenticated(request):
        return FileResponse(_FRONTEND / "login.html")
    html = (_FRONTEND / "index.html").read_text(encoding="utf-8")
    ver = _compute_asset_version()
    html = html.replace(
        'content="2"',
        f'content="{ver}"',
        1,
    )
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


@app.get("/onboarding")
async def onboarding(request: Request):
    if not is_authenticated(request):
        return FileResponse(_FRONTEND / "login.html")
    return FileResponse(_FRONTEND / "onboarding.html")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(_FRONTEND / "sw.js", media_type="application/javascript")


@app.get("/api/quote")
async def quote(request: Request):
    from modules.portfolio.quotes import get_random_quote
    return get_random_quote()


@app.get("/api/scheduler/status")
async def scheduler_status(request: Request):
    from scheduler import get_scheduler
    s = get_scheduler()
    if s is None:
        return {"running": False, "jobs": []}
    return {
        "running": s.running,
        "jobs": [
            {
                "id":       j.id,
                "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
            }
            for j in s.get_jobs()
        ],
    }


@app.post("/api/scheduler/run-now/prune")
async def run_pruner_now(request: Request):
    """Manually trigger the trade pruner for the current user — for testing."""
    from database import SessionLocal
    from deps import get_current_user_id
    from services.trade_pruner import prune_open_recommendations

    db = SessionLocal()
    try:
        user_id = get_current_user_id(request, db)
        pruned = await asyncio.to_thread(prune_open_recommendations, user_id)
        return {"ok": True, "pruned": pruned}
    finally:
        db.close()


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
