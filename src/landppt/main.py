"""
Main FastAPI application entry point
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
import uvicorn
import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from . import __version__
from .api.openai_compat import router as openai_router
from .api.landppt_api import router as landppt_router
from .api.database_api import router as database_router
from .api.global_master_template_api import router as template_api_router
from .api.template_package_api import router as template_package_router
from .api.template_package_import_api import router as template_package_import_router
from .api.config_api import router as config_router
from .api.image_api import router as image_router

from .web import router as web_router
from .web.admin_routes import router as admin_router
from .api.managed_provider_api import router as managed_provider_router
from .web.community_routes import router as community_router
from .web.credits_routes import router as credits_router
from .auth import auth_router, create_auth_middleware
from .auth.openapi import install_auth_openapi
from .database.startup_initialization import run_startup_initialization
from .core.config import app_config
from .services.metrics import metrics_collector

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable SQLAlchemy verbose logging completely
logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.engine.Engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(application):
    """Always release application resources, including on cancellation."""
    try:
        await startup_event()
        try:
            yield
        except asyncio.CancelledError:
            logger.info("Application lifespan cancelled")
    finally:
        await shutdown_event()


# Create FastAPI app
app = FastAPI(
    title="LandPPT API",
    description="AI-powered PPT generation platform with OpenAI-compatible API",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs" if app_config.enable_api_docs else None,
    redoc_url="/redoc" if app_config.enable_api_docs else None,
    openapi_url="/openapi.json" if app_config.enable_api_docs else None,
)


async def startup_event():
    """Initialize database on startup"""
    try:
        await run_startup_initialization()

    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        raise


async def shutdown_event():
    """Clean up database connections on shutdown"""
    try:
        logger.info("Shutting down application...")
        # Close cache service if enabled
        try:
            from .services.cache_service import close_cache_service
            await close_cache_service()
        except Exception:
            pass
        logger.info("Application shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    finally:
        from .database.database import close_db

        await close_db()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add authentication middleware
auth_middleware = create_auth_middleware()
app.middleware("http")(auth_middleware)
install_auth_openapi(app, auth_middleware.is_public_path)


@app.middleware("http")
async def metrics_middleware(request, call_next):
    metrics_collector.start_request()
    started_at = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        metrics_collector.finish_request(
            request.method,
            path,
            status_code,
            time.perf_counter() - started_at,
        )

# Include routers
app.include_router(auth_router, prefix="", tags=["Authentication"])
app.include_router(config_router, prefix="", tags=["Configuration Management"])
app.include_router(image_router, prefix="", tags=["Image Service"])

# Web router must come before landppt_router to ensure specific endpoints take precedence
app.include_router(web_router, prefix="", tags=["Web Interface"])
app.include_router(admin_router, tags=["Admin Management"])
app.include_router(managed_provider_router)
app.include_router(community_router, tags=["Community Pages"])
app.include_router(credits_router, tags=["Credits System"])
app.include_router(openai_router, prefix="/v1", tags=["OpenAI Compatible"])
app.include_router(landppt_router, prefix="/api", tags=["LandPPT API"])
app.include_router(template_package_router)
app.include_router(template_package_import_router)
app.include_router(template_api_router, tags=["Global Master Templates"])
app.include_router(database_router, tags=["Database Management"])


# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Redirect /assets/ font requests to fontsource CDN
# AI-generated slide HTML may reference fonts like /assets/inter-latin-400-normal-C38fXH4l.woff2
# (Vite/@fontsource bundled paths). This route parses the naming pattern and redirects to CDN.
import re
_FONTSOURCE_RE = re.compile(
    r'^(?P<family>[a-z0-9-]+?)-(?P<subset>[a-z]+)-(?P<weight>\d+)-(?P<style>[a-z]+)-[A-Za-z0-9_-]+\.woff2$'
)

@app.get("/assets/{filename:path}")
async def serve_font_asset(filename: str):
    """Redirect fontsource-style font requests to jsDelivr CDN"""
    from fastapi.responses import RedirectResponse
    m = _FONTSOURCE_RE.match(filename)
    if m:
        family = m.group('family')
        subset = m.group('subset')
        weight = m.group('weight')
        style = m.group('style')
        cdn_url = f"https://cdn.jsdelivr.net/fontsource/fonts/{family}@latest/{subset}-{weight}-{style}.woff2"
        return RedirectResponse(url=cdn_url, status_code=301)
    raise HTTPException(status_code=404, detail="Asset not found")

# Mount temp directory for image cache
temp_dir = os.path.join(os.getcwd(), "temp")
if app_config.expose_temp_static_files and os.path.exists(temp_dir):
    app.mount("/temp", StaticFiles(directory=temp_dir), name="temp")
    logger.info(f"Mounted temp directory: {temp_dir}")
elif not app_config.expose_temp_static_files:
    logger.info("Temp static file mount disabled by configuration")
else:
    logger.warning(f"Temp directory not found: {temp_dir}")

@app.get("/", response_class=HTMLResponse)
async def root():
    """Open the product homepage; the workspace remains at /dashboard."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/home", status_code=302)

@app.get("/favicon.ico")
async def favicon():
    """Serve favicon"""
    favicon_path = os.path.join(os.path.dirname(__file__), "web", "static", "images", "favicon.svg")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path, media_type="image/svg+xml")
    else:
        raise HTTPException(status_code=404, detail="Favicon not found")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "LandPPT API"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint."""
    return PlainTextResponse(metrics_collector.render_prometheus(), media_type="text/plain; version=0.0.4")

if __name__ == "__main__":
    uvicorn.run(
        "src.landppt.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
