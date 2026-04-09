"""
api/__init__.py — FastAPI application entry point.

Owns all HTTP routes and middleware. lib/ modules handle
schema definitions, extraction logic, and configuration.

sys.path is extended here so that tests can use flat imports
(from schema import ..., from extraction import ...) which
mirrors how the lib modules import each other internally.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Make api/lib/ importable as flat modules: schema, extraction, config, registry
_api_root = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.join(_api_root, "lib")
if _lib not in sys.path:
    sys.path.insert(0, _lib)
# Make lib.* importable (e.g. from lib.config import ...) by putting api/ on sys.path
if _api_root not in sys.path:
    sys.path.insert(0, _api_root)

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from lib.config import configure_logging, settings
from lib.extraction import extract_bol_vision, extract_document, preprocess_pdf_to_images

configure_logging()
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({"pdf", "jpg", "jpeg", "png", "webp"})

_MIME_BY_EXT: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY is not set — extraction requests will fail")
    logger.info("Ibis Serverless Handler started")
    yield


app = FastAPI(
    title="IBIS Unified Logistics Extractor",
    description="High-precision vision extraction API for BOLs and Delivery Notes.",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_origins = [o.strip() for o in settings.allowed_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

_static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(_static_path):
    app.mount("/static", StaticFiles(directory=_static_path), name="static")


@app.middleware("http")
async def security_and_tracing(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://vercel.live https://*.vercel-scripts.com; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' https://*.vercel-insights.com https://vercel.live"
    )
    return response


@app.get("/health", tags=["ops"])
@app.get("/api/health", include_in_schema=False)
async def health():
    return {"status": "ok", "version": app.version}


@app.get("/", include_in_schema=False)
async def read_index():
    index_file = os.path.join(_static_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Static index.html not found")


async def _handle_upload(request: Request, file: UploadFile):
    """Shared upload validation. Returns (base64_images, mime_types, request_id)."""
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported format '.{ext}'")

    content = await file.read(settings.max_file_bytes + 1)
    if len(content) > settings.max_file_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    if ext == "pdf":
        base64_images = await asyncio.to_thread(preprocess_pdf_to_images, content)
        mime_types = ["image/jpeg"] * len(base64_images)
    else:
        base64_images = [base64.b64encode(content).decode("utf-8")]
        mime_types = [_MIME_BY_EXT[ext]]

    return base64_images, mime_types, request_id


@app.post("/extract-bol", tags=["extraction"])
@app.post("/api/extract-bol", include_in_schema=False)
@limiter.limit(settings.rate_limit)
async def extract_bol(request: Request, file: UploadFile = File(...)):
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info("BOL extraction request", extra={"request_id": request_id})
    start = time.monotonic()

    try:
        base64_images, mime_types, request_id = await _handle_upload(request, file)
        result = await asyncio.to_thread(extract_bol_vision, base64_images, mime_types)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        response_data = result.model_dump()
        response_data["_pipeline"] = {
            "processing_time_ms": elapsed_ms,
            "pages_processed": len(base64_images),
            "model": "Gemini 3.1 Flash-Lite",
            "request_id": request_id,
        }
        return JSONResponse(content=response_data)
    except HTTPException:
        raise
    except Exception:
        logger.exception("BOL extraction failed", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail="Extraction pipeline failed.",
            headers={"X-Request-ID": request_id},
        )


@app.post("/extract", tags=["extraction"])
@app.post("/api/extract", include_in_schema=False)
@limiter.limit(settings.rate_limit)
async def extract(request: Request, file: UploadFile = File(...)):
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info("Smart extraction request", extra={"request_id": request_id})
    start = time.monotonic()

    try:
        base64_images, mime_types, request_id = await _handle_upload(request, file)
        result = await asyncio.to_thread(extract_document, base64_images, mime_types)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        response_data = result.model_dump()
        response_data["_pipeline"] = {
            "processing_time_ms": elapsed_ms,
            "pages_processed": len(base64_images),
            "model": "Gemini 3.1 Flash-Lite",
            "request_id": request_id,
        }
        return JSONResponse(content=response_data)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Smart extraction failed", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail="Extraction pipeline failed.",
            headers={"X-Request-ID": request_id},
        )
