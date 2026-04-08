"""
api.py — FastAPI application entry point.

Exposes a single extraction endpoint backed by the Gemini Vision pipeline.
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

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import configure_logging, settings
from extraction import extract_bol_vision, preprocess_pdf_to_images

# Configure logging before any log records are emitted.
configure_logging()
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({"pdf", "jpg", "jpeg", "png", "webp"})

# Maps file extension → MIME type expected by the Gemini inlineData field.
# PDFs are always rasterised to JPEG by preprocessing.py, so "pdf" is not here.
_MIME_BY_EXT: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

# ─── Rate limiter ─────────────────────────────────────────────────────────────
# Key function: client IP address.
# SOC2 (CC6.6): limits request volume to mitigate abuse and quota exhaustion.
limiter = Limiter(key_func=get_remote_address)


# ─── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Warn early so ops teams catch misconfiguration before a request fails.
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY is not set — extraction requests will fail")
    logger.info("Ibis Logistics Extractor started (rate_limit=%s)", settings.rate_limit)
    yield
    logger.info("Ibis Logistics Extractor shutting down")


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="IBIS Unified Logistics Extractor",
    description="High-precision vision extraction API for BOLs and Delivery Notes.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — configure allowed origins via the ALLOWED_ORIGINS environment variable.
_origins = [o.strip() for o in settings.allowed_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Static assets (CSS, JS, images)
_static_path = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_path), name="static")


# ─── Middleware ───────────────────────────────────────────────────────────────

@app.middleware("http")
async def security_and_tracing(request: Request, call_next):
    """
    Per-request middleware that:
    - Generates a UUID request ID for distributed tracing.
    - Attaches security headers to every response.

    SOC2:
    - CC7.2: X-Request-ID enables correlation of logs across services.
    - CC6.6: Security headers mitigate common web vulnerabilities (clickjacking,
      MIME sniffing, XSS via framing).
    """
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)

    # Distributed tracing — also surfaced in 500 error responses so clients can
    # provide the ID when contacting support.
    response.headers["X-Request-ID"] = request_id

    # Security response headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        # Google Fonts stylesheet + inline style attributes used in index.html
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"], summary="Liveness check")
async def health():
    """
    Returns 200 when the server is running.
    Does NOT verify upstream connectivity (Gemini, etc.) — use for load-balancer
    health probes only.
    """
    return {"status": "ok", "version": app.version}


@app.get("/", include_in_schema=False)
async def read_index():
    return FileResponse(os.path.join(_static_path, "index.html"))


@app.post("/extract-bol", tags=["extraction"], summary="Extract structured BOL data")
@limiter.limit(settings.rate_limit)
async def extract_bol(request: Request, file: UploadFile = File(...)):
    """
    Accepts a PDF or image file and returns strictly-validated JSON logistics data
    extracted by the Gemini Vision pipeline.

    Audit trail: each request is assigned a unique `X-Request-ID`. The ID appears
    in response headers, in the `_pipeline` response body, and in server logs —
    enabling end-to-end traceability without logging document contents.

    SOC2: CC6.6 (input validation), CC7.2 (audit trail), CC9.2 (vendor risk tracked
    via `_pipeline.model`).
    """
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '.{ext}'. Accepted: pdf, png, jpg, jpeg, webp.",
        )

    # Read with a hard cap — prevents OOM from oversized uploads.
    content = await file.read(settings.max_file_bytes + 1)
    if len(content) > settings.max_file_bytes:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit.")

    # Audit log: record submission metadata without logging document content.
    # SOC2 (CC7.2): filename is omitted to avoid logging PII embedded in filenames.
    logger.info(
        "Extraction request received",
        extra={"request_id": request_id, "file_bytes": len(content)},
    )
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
        logger.info(
            "Extraction completed",
            extra={"request_id": request_id, "pages": len(base64_images), "elapsed_ms": elapsed_ms},
        )

        response_data = result.model_dump()
        response_data["_pipeline"] = {
            "processing_time_ms": elapsed_ms,
            "pages_processed": len(base64_images),
            "model": "Gemini 3.1 Flash-Lite",
            "request_id": request_id,
        }
        return JSONResponse(content=response_data)

    except Exception:
        logger.exception("Extraction pipeline failed", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail=(
                "Extraction pipeline failed. "
                f"Provide request_id '{request_id}' when contacting support."
            ),
            headers={"X-Request-ID": request_id},
        )


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
