"""
app.py — FastAPI application serving the API and web UI.

Endpoints:
    GET  /          → Serves the upload UI
    POST /api/process → Accepts PDF upload, returns structured JSON

Run with:
    uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
import tempfile
import os
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from process_document import process_document

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="IBIS PDF Extractor",
    description="Convert PDFs to structured JSON data",
    version="1.0.0",
)

# Serve static files (CSS, JS)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_ui():
    """Serve the main upload UI."""
    return FileResponse(str(static_dir / "index.html"))


@app.post("/api/process")
async def process_pdf(file: UploadFile = File(...)):
    """
    Process an uploaded PDF and return structured JSON.

    Accepts: multipart/form-data with a 'file' field containing the PDF.
    Returns: JSON object following the BOLDocument schema.
    """
    # Validate file type
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing.")
        
    ext = file.filename.lower().split('.')[-1]
    valid_exts = ['pdf', 'png', 'jpg', 'jpeg', 'webp']
    if ext not in valid_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Accepted formats: {', '.join(valid_exts)}"
        )

    # Save to temp file
    try:
        with tempfile.NamedTemporaryFile(
            suffix=f'.{ext}',
            delete=False,
            dir=tempfile.gettempdir(),
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        logger.info(f"Processing uploaded file: {file.filename} ({len(content)} bytes)")

        # Process the document
        result = process_document(tmp_path)

        # Add original filename to result
        result['_source_filename'] = file.filename

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {str(e)}"
        )
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "ibis-pdf-extractor"}
