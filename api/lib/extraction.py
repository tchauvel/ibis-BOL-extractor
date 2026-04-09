"""
extraction.py — Document Pipeline: Rasterisation + Vision-LLM Extraction

Two responsibilities intentionally kept in one file:
  1. preprocess_pdf_to_images  — converts PDF bytes to base64 JPEG images
  2. extract_bol_vision        — sends images to Gemini and returns a UnifiedBOL
"""
from __future__ import annotations

import base64
import io
import json
import logging
from typing import Any

import fitz  # PyMuPDF — pure-Python wheels, no system deps (Vercel compatible)
import httpx

from lib.config import settings
from lib.schema import UnifiedBOL

logger = logging.getLogger(__name__)

MODEL_ID = "gemini-3.1-flash-lite-preview"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent"

SYSTEM_PROMPT = """
Act as a Senior Logistics Compliance Auditor and Document AI Specialist.
Your task is to extract high-accuracy structured data from the provided Bill of Lading (BOL), Delivery Note, or Master BOL images.

CONTEXT:
You are analyzing highly customized Delivery Notes and Master BOLs from major global logistics providers and multinational retailers.
These documents contain critical proprietary tracking numbers and granular operational metadata.

RULES FOR EXTRACTION:
1. **Persona**: You are an auditor. Precision is everything.
2. **Noise Reduction**: Aggressively ignore barcodes, standard Terms & Conditions boilerplate, and logos.
3. **Operational Numbers**: Pay extremely close attention to the header blocks for internal numbers like 'Plan#', 'Order#', 'Web ID#', 'Customer PO. No.', and proprietary IDs.
4. **Data Integrity**:
   - Capture handling unit quantities (PLT, SKD) and package counts (Cartons, Boxes) accurately.
   - Extract weights as numeric values (always in lbs).
5. **Inventory Tables**: Scan tables carefully. Look below or next to commodity descriptions for hidden cold-storage metadata like 'Best before', 'BDD' (Expiration Date), 'Frozen date', and 'BatchLot'.
6. **Signatures**: Set boolean flags only if a physical signature or stamp is visible.
7. **Catch-All**: Use the `other_references` array for any tracking or reference numbers on the document that do not fit into the primary schema fields.
8. **Output**: Return ONLY a valid JSON object matching the provided schema. No markdown.
"""


# ─── Rasterisation ────────────────────────────────────────────────────────────

def preprocess_pdf_to_images(pdf_bytes: bytes) -> list[str]:
    """
    Converts the first two pages of a PDF to 300 DPI JPEG images.

    300 DPI is the optimal resolution for Vision-LLMs: high enough for small text
    (NMFC codes, lot numbers) without excessive token usage.

    Returns a list of base64-encoded JPEG strings ready for Gemini inlineData.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    result = []
    for page_num in range(min(2, len(doc))):
        page = doc[page_num]
        # 300 DPI → matrix scale factor ≈ 4.17 (300/72)
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


# Computed once at module load — never changes at runtime.
_RESOLVED_SCHEMA: dict[str, Any] = resolve_schema_refs(UnifiedBOL.model_json_schema())


# ─── Extraction ───────────────────────────────────────────────────────────────

def extract_bol_vision(
    base64_images: list[str],
    mime_types: list[str] | None = None,
) -> UnifiedBOL:
    """
    Calls Gemini via direct REST for full payload control and Structured Output.

    Args:
        base64_images: Base64-encoded image strings.
        mime_types: MIME type per image. Defaults to image/jpeg (correct for
                    PDF-rasterised output). Pass ["image/png"] etc. for direct images.

    Raises:
        ValueError: GEMINI_API_KEY missing, or Gemini returned an error/malformed response.
        pydantic.ValidationError: Gemini JSON doesn't match the UnifiedBOL schema.
    """
    if not settings.gemini_api_key:
        raise ValueError(
            "GEMINI_API_KEY is not configured. "
            "Please add it to your Vercel Project Settings > Environment Variables and Redeploy."
        )

    if mime_types is None:
        mime_types = ["image/jpeg"] * len(base64_images)

    if len(mime_types) != len(base64_images):
        raise ValueError("mime_types length must match base64_images length.")

    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": SYSTEM_PROMPT}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESOLVED_SCHEMA,
        },
    }
    for b64, mime in zip(base64_images, mime_types):
        payload["contents"][0]["parts"].append(
            {"inlineData": {"mimeType": mime, "data": b64}}
        )

    try:
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
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            logger.error("Unexpected Gemini response structure")
            raise ValueError("Malformed Gemini response") from exc

        return UnifiedBOL(**json.loads(text))

    except Exception:
        logger.exception("Gemini REST extraction failed")
        raise
