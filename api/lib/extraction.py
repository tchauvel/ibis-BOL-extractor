"""
extraction.py — Document Pipeline: Rasterisation + Vision-LLM Extraction

Three responsibilities:
  1. preprocess_pdf_to_images  — converts PDF bytes to base64 JPEG images
  2. classify_document         — Pass 1: identifies document type via plain-text prompt
  3. extract_document          — Pass 1 + Pass 2: classify then extract with typed schema
  4. extract_bol_vision        — legacy helper (calls _extract_with_schema with UnifiedBOL)
"""
from __future__ import annotations

import base64
import io
import json
import logging
from typing import Any

import fitz  # PyMuPDF
import httpx
from pydantic import BaseModel

from lib.config import settings

try:
    from schema import ExtractionResult, UnifiedBOL
except ImportError:
    from lib.schema import ExtractionResult, UnifiedBOL  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

MODEL_ID = "gemini-3.1-flash-lite-preview"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent"


# ─── Rasterisation ────────────────────────────────────────────────────────────

def preprocess_pdf_to_images(pdf_bytes: bytes) -> list[str]:
    """
    Converts the first two pages of a PDF to 300 DPI JPEG images.
    Returns a list of base64-encoded JPEG strings ready for Gemini inlineData.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    result = []
    for page_num in range(min(2, len(doc))):
        page = doc[page_num]
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        buf = io.BytesIO(pix.tobytes("jpeg", jpg_quality=85))
        result.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
    doc.close()
    return result


# ─── Schema helpers ───────────────────────────────────────────────────────────

def resolve_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Flattens a Pydantic JSON Schema into a form Gemini's Structured Output accepts.
    Resolves $ref/$defs, simplifies anyOf, and strips metadata (title, description).
    """
    defs = schema.get("$defs", {})

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                node = _resolve(defs[node["$ref"].split("/")[-1]])
            if "anyOf" in node:
                options = node["anyOf"]
                non_null = [o for o in options if o.get("type") != "null"]
                node = _resolve((non_null or options)[0])
            return {
                k: _resolve(v) for k, v in node.items()
                if k not in {"title", "description", "$defs", "$ref", "anyOf", "oneOf", "default"}
            }
        if isinstance(node, list):
            return [_resolve(x) for x in node]
        return node

    return _resolve(schema)


# ─── Internal Gemini call ─────────────────────────────────────────────────────

def _call_gemini(payload: dict[str, Any]) -> str:
    """
    Sends payload to Gemini REST and returns the raw text response.
    Raises ValueError on HTTP errors or malformed responses.
    """
    if not settings.gemini_api_key:
        raise ValueError(
            "GEMINI_API_KEY is not configured. "
            "Add it to Vercel Project Settings > Environment Variables and redeploy."
        )

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            API_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": settings.gemini_api_key,
            },
        )

    if response.status_code != 200:
        logger.error("Gemini API returned HTTP %d", response.status_code)
        raise ValueError(f"Gemini API error (HTTP {response.status_code})")

    try:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        logger.error("Unexpected Gemini response structure")
        raise ValueError("Malformed Gemini response") from exc


def _build_image_parts(base64_images: list[str], mime_types: list[str]) -> list[dict]:
    return [
        {"inlineData": {"mimeType": mime, "data": b64}}
        for b64, mime in zip(base64_images, mime_types)
    ]


# ─── Generic extraction ───────────────────────────────────────────────────────

def _extract_with_schema(
    base64_images: list[str],
    mime_types: list[str],
    schema_cls: type[BaseModel],
    system_prompt: str,
) -> BaseModel:
    """
    Calls Gemini with structured output enforced for schema_cls.
    Returns an instance of schema_cls.
    """
    resolved_schema = resolve_schema_refs(schema_cls.model_json_schema())
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": system_prompt}, *_build_image_parts(base64_images, mime_types)]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": resolved_schema,
        },
    }
    text = _call_gemini(payload)
    return schema_cls(**json.loads(text))


# ─── Public API ───────────────────────────────────────────────────────────────

def classify_document(
    base64_images: list[str],
    mime_types: list[str] | None = None,
) -> str:
    """
    Pass 1: asks Gemini to identify the document type.
    Returns one of: 'bol', 'cartage_advice', 'unknown'.
    Any response not in the registry falls back to 'unknown'.
    """
    try:
        from registry import CLASSIFICATION_PROMPT, REGISTRY  # type: ignore[import]
    except ImportError:
        from lib.registry import CLASSIFICATION_PROMPT, REGISTRY  # type: ignore[no-redef]

    if mime_types is None:
        mime_types = ["image/jpeg"] * len(base64_images)

    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": CLASSIFICATION_PROMPT}, *_build_image_parts(base64_images, mime_types)]}],
    }

    try:
        raw = _call_gemini(payload)
        doc_type = raw.strip().lower()
        return doc_type if doc_type in REGISTRY else "unknown"
    except Exception:
        logger.exception("Document classification failed — falling back to 'unknown'")
        return "unknown"


def extract_document(
    base64_images: list[str],
    mime_types: list[str] | None = None,
) -> ExtractionResult:
    """
    Pass 1 + Pass 2: classify the document, then extract with the matched schema.
    Always returns an ExtractionResult — never raises for unknown document types.
    """
    try:
        from registry import get_registry_entry  # type: ignore[import]
    except ImportError:
        from lib.registry import get_registry_entry  # type: ignore[no-redef]

    if mime_types is None:
        mime_types = ["image/jpeg"] * len(base64_images)

    doc_type = classify_document(base64_images, mime_types)
    schema_cls, system_prompt = get_registry_entry(doc_type)

    instance = _extract_with_schema(base64_images, mime_types, schema_cls, system_prompt)
    return ExtractionResult(document_type=doc_type, data=instance.model_dump())


def extract_bol_vision(
    base64_images: list[str],
    mime_types: list[str] | None = None,
) -> UnifiedBOL:
    """
    Legacy single-schema extraction. Kept for backward compatibility with /extract-bol.
    """
    try:
        from registry import BOL_SYSTEM_PROMPT  # type: ignore[import]
    except ImportError:
        from lib.registry import BOL_SYSTEM_PROMPT  # type: ignore[no-redef]

    if mime_types is None:
        mime_types = ["image/jpeg"] * len(base64_images)

    return _extract_with_schema(base64_images, mime_types, UnifiedBOL, BOL_SYSTEM_PROMPT)  # type: ignore[return-value]
