"""
index.py — Vercel Serverless Entry Point (FastAPI)
Consolidated handler for Ibis Logistics Extraction.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Relative imports from the local function bundle
from .lib.config import configure_logging, settings
from .lib.extraction import extract_bol_vision, preprocess_pdf_to_images

# Configure logging
configure_logging()
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({"pdf", "jpg", "jpeg", "png", "webp"})

_MIME_BY_EXT: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

# ─── Rate limiter ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY is not set — extraction requests will fail")
    logger.info("Ibis Serverless Handler started")
    yield

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="IBIS Unified Logistics Extractor",
    description="High-precision vision extraction API for BOLs and Delivery Notes.",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
_origins = [o.strip() for o in settings.allowed_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Static assets - resolved relative to the function directory
_static_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(_static_path):
    app.mount("/static", StaticFiles(directory=_static_path), name="static")


# ─── Middleware ───────────────────────────────────────────────────────────────

@app.middleware("http")
async def security_and_tracing(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # CSP optimized for production hosting
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok", "version": app.version}


@app.get("/", include_in_schema=False)
async def read_index():
    index_file = os.path.join(_static_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Static index.html not found")


@app.post("/extract-bol", tags=["extraction"])
@limiter.limit(settings.rate_limit)
async def extract_bol(request: Request, file: UploadFile = File(...)):
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '.{ext}'",
        )

    content = await file.read(settings.max_file_bytes + 1)
    if len(content) > settings.max_file_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    logger.info("Extraction request received", extra={"request_id": request_id})
    start = time.monotonic()

    try:
        if ext == "pdf":
            base64_images = await asyncio.to_thread(preprocess_pdf_to_images, content)
            mime_types = ["image/jpeg"] * len(base64_images)
        else:
            base64_images = [base64.b64encode(content).decode("utf-8")]
            mime_types = [_MIME_BY_EXT[ext]]

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

    except Exception:
        logger.exception("Extraction failed", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail="Extraction pipeline failed.",
            headers={"X-Request-ID": request_id},
        )

# Vercel handler
handler = app
