"""
llm/vision_extractor.py — Vision LLM integration for OCR and document extraction.

This is the ace in the hole for unseen documents and scanned PDFs.
Two backends supported:
  1. Ollama (local, free) — llava, moondream, bakllava
  2. DeepSeek API (cloud, cheap) — excellent vision capabilities

The LLM receives the PDF page as an image + a structured prompt,
and returns JSON that maps to our BOLDocument schema.
"""

from __future__ import annotations

import base64
import json
import os
import re
import logging
from pathlib import Path
from typing import Optional

from schema import (
    BOLDocument, Party, Address, CarrierInfo,
    VesselInfo, ContainerInfo, ShippingDetails,
    LineItem, Totals,
)

logger = logging.getLogger(__name__)


# ─── Extraction Prompt ────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are an expert document parser specializing in logistics and shipping documents, including DOT/FMCSA regulatory compliance.

Analyze this document image and extract ALL structured data you can find.

IMPORTANT — CLASSIFICATION STEP (do this FIRST before extracting line items):
1. Check if any "H.M." or "Hazmat" column has an "X" mark. Look for UN/NA numbers (e.g. UN3480).
2. Check if it says "Master Bill of Lading" or references underlying BOL numbers.
3. Check if it contains "to order" or endorsement language (negotiable BOL).
4. Check for vessel/voyage fields (ocean BOL) vs PRO/NMFC (LTL) vs trailer/seal (truckload).

Return ONLY valid JSON matching this schema:

{
  "document_metadata": {
    "is_hazmat": false,
    "bol_type": "Straight | Order | Master | Through | Ocean",
    "transport_mode": "LTL | TL | Ocean | Air | Intermodal",
    "regulatory_type": "general | hazmat | household",
    "hazmat_details": {
      "un_na_number": "UN3480 or null",
      "proper_shipping_name": "...",
      "hazard_class": "9 or null",
      "packing_group": "I | II | III or null",
      "emergency_contact": "24-hour phone or null"
    }
  },
  "document_type": "bill_of_lading | invoice | packing_list | other",
  "document_subtype": "ltl | ocean | drayage | air | other",
  "document_date": "YYYY-MM-DD or original format",
  "references": {
    "bol_number": "...",
    "pro_number": "...",
    "po_number": "...",
    "trailer_number": "...",
    "seal_number": "..."
  },
  "parties": [
    {
      "role": "shipper | consignee | third_party_billing | broker",
      "name": "...",
      "address": "...",
      "city": "...",
      "state": "...",
      "zip_code": "...",
      "phone": "..."
    }
  ],
  "carrier": {
    "name": "...",
    "scac": "...",
    "pro_number": "...",
    "trailer_number": "..."
  },
  "vessel_info": {
    "vessel_name": "...",
    "voyage_number": "...",
    "port_of_loading": "...",
    "port_of_discharge": "...",
    "eta": "..."
  },
  "container_info": {
    "container_number": "...",
    "container_size": "...",
    "seal_number": "..."
  },
  "shipping_details": {
    "pickup_date": "...",
    "estimated_delivery": "...",
    "freight_terms": "...",
    "special_instructions": "..."
  },
  "line_items": [
    {
      "description": "...",
      "quantity": 0,
      "packaging_type": "...",
      "weight": 0.0,
      "weight_unit": "lbs",
      "nmfc": "NMFC number or null",
      "ltl_class": "freight class 50-500 or null",
      "hazmat": false,
      "hazmat_info": {
        "un_na_number": "...",
        "hazard_class": "...",
        "packing_group": "..."
      },
      "carton_count": 0
    }
  ],
  "totals": {
    "total_pieces": 0,
    "total_weight": 0.0,
    "total_cartons": 0
  }
}

Rules:
- FIRST classify the document type, then extract fields.
- For each line item, check the H.M. column — set hazmat=true if marked "X".
- If hazmat, extract UN/NA number, hazard class, and packing group.
- Look for "Master Bill of Lading" checkbox or text to identify Master BOLs.
- Look for "to order" language to identify negotiable/order BOLs.
- For LTL: extract PRO number and NMFC/freight class.
- For TL: extract trailer number and seal number.
- Extract EVERY field you can find. Use null for missing fields.
- Preserve original values (don't guess).
- For dates, try to format as YYYY-MM-DD.
- Return ONLY the JSON, no markdown formatting or explanation."""


def file_to_images(file_path: str) -> list[str]:
    """
    Convert a file (PDF, PNG, JPG) to base64-encoded PNG images.
    Returns list of base64 strings. (1 item for images, N items for PDFs).
    """
    import io
    ext = file_path.lower().split('.')[-1]
    
    if ext in ['png', 'jpg', 'jpeg', 'webp']:
        try:
            from PIL import Image
            img = Image.open(file_path)
            # Ensure RGB to avoid issues with transparency
            if img.mode in ('RGBA', 'P'): img = img.convert('RGB')
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            return [b64]
        except ImportError:
            logger.warning("Pillow not installed. Install with: pip install Pillow")
            return []
        except Exception as e:
            logger.warning(f"Failed to process image: {e}")
            return []
            
    # Fallback to PDF processing (Vercel-friendly using PyMuPDF)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        b64_images = []
        for page in doc:
            # Render page to an image (200 DPI for balance of detail and size)
            pix = page.get_pixmap(dpi=200)
            img_data = pix.tobytes("png")
            b64 = base64.b64encode(img_data).decode('utf-8')
            b64_images.append(b64)
        doc.close()
        return b64_images
    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed. Install with: pip install pymupdf")
        return []
    except Exception as e:
        logger.warning(f"Failed to convert PDF to images using PyMuPDF: {e}")
        return []


# ─── Ollama Backend ───────────────────────────────────────────────────────────

def extract_with_ollama(
    file_path: str,
    model: str = "deepseek-ocr",
) -> Optional[dict]:
    """
    Extract structured data using Ollama's local vision models.

    Requires: ollama installed + model pulled
    """
    try:
        import ollama as ollama_client
    except ImportError:
        logger.warning("ollama package not installed. Install with: pip install ollama")
        return None

    images_b64 = file_to_images(file_path)
    if not images_b64:
        return None

    all_results = []
    for i, img_b64 in enumerate(images_b64):
        try:
            response = ollama_client.chat(
                model=model,
                messages=[{
                    'role': 'user',
                    'content': EXTRACTION_PROMPT,
                    'images': [img_b64],
                }],
            )
            content = response['message']['content']
            parsed = _parse_llm_json(content)
            if parsed:
                all_results.append(parsed)
        except Exception as e:
            logger.warning(f"Ollama extraction failed for page {i + 1}: {e}")

    return _merge_page_results(all_results) if all_results else None


# ─── Cloud API Backends (Vercel Ready) ────────────────────────────────────────

def extract_with_datalab(file_path: str, api_key: Optional[str] = None) -> Optional[dict]:
    """
    Extract structured data using Datalab.to's Extraction API.
    Sends the PDF natively and parses against our Pydantic JSON schema.
    Set DATALAB_API_KEY env var.
    """
    api_key = api_key or os.environ.get("DATALAB_API_KEY")
    if not api_key:
        return None

    import requests
    import time
    from schema import BOLDocument

    try:
        # Generate strict JSON Schema from our Pydantic model
        schema_dict = BOLDocument.model_json_schema()
        
        url = "https://www.datalab.to/api/v1/extract"
        headers = {"X-API-Key": api_key}
        
        with open(file_path, "rb") as f:
            mime_type = "application/pdf" if file_path.lower().endswith(".pdf") else "image/png"
            files = {"file": (os.path.basename(file_path), f, mime_type)}
            data = {
                "page_schema": json.dumps(schema_dict),
                "mode": "balanced"
            }
            logger.info("Sending document to Datalab.to API...")
            response = requests.post(url, headers=headers, files=files, data=data)
            response.raise_for_status()
            
            result = response.json()
            if not result.get("success") or "request_check_url" not in result:
                logger.warning(f"Datalab returned unexpected start response: {result}")
                return None
                
            check_url = result["request_check_url"]
            logger.info("Datalab API processing... waiting for completion.")
            
            # Poll the check_url until complete
            for _ in range(30):  # Wait up to ~60 seconds
                time.sleep(2)
                poll_resp = requests.get(check_url, headers=headers)
                poll_resp.raise_for_status()
                poll_result = poll_resp.json()
                
                if poll_result.get("status") == "complete":
                    if "extraction_schema_json" in poll_result:
                        extracted_str = poll_result["extraction_schema_json"]
                        return json.loads(extracted_str)
                    else:
                        logger.warning("Datalab finished but returned no schema JSON.")
                        return None
                elif poll_result.get("status") in ["failed", "error"]:
                    logger.warning(f"Datalab processing failed: {poll_result}")
                    return None
                    
            logger.warning("Datalab API polling timed out.")
            return None
    except Exception as e:
        logger.warning(f"Datalab extraction failed: {e}")
        
    return None


def extract_with_gemini(
    file_path: str,
    api_key: Optional[str] = None,
    model: str = "gemini-flash-latest",
) -> Optional[dict]:
    """
    Extract using Google Gemini's Vision model (Vercel-ready).
    Uses the native REST API to avoid dependency bloat.
    Set GEMINI_API_KEY env var.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    import requests

    images_b64 = file_to_images(file_path)
    if not images_b64:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    all_results = []
    for i, img_b64 in enumerate(images_b64):
        try:
            data = {
                "contents": [{
                    "parts": [
                        {"text": EXTRACTION_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": img_b64
                            }
                        }
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                }
            }
            logger.info(f"Sending page {i + 1} to Gemini API...")
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code != 200:
                logger.warning(f"Gemini API returned {response.status_code}: {response.text}")
                continue
                
            content = response.json()
            if "candidates" in content and len(content["candidates"]) > 0:
                text_response = content["candidates"][0]["content"]["parts"][0].get("text", "")
                parsed = _parse_llm_json(text_response)
                if parsed:
                    all_results.append(parsed)
            else:
                logger.warning(f"Gemini returned unexpected structure: {content}")
        except Exception as e:
            logger.warning(f"Gemini extraction failed for page {i + 1}: {e}")

    return _merge_page_results(all_results) if all_results else None



def extract_with_openai(
    file_path: str,
    api_key: Optional[str] = None,
    model: str = "gpt-4o-mini",
) -> Optional[dict]:
    """
    Extract using OpenAI's Vision model (Vercel-ready).
    Set OPENAI_API_KEY env var.
    """
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed. run: pip install openai")
        return None

    images_b64 = file_to_images(file_path)
    if not images_b64:
        return None

    client = OpenAI(api_key=api_key)

    all_results = []
    for i, img_b64 in enumerate(images_b64):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": EXTRACTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{img_b64}"
                            }
                        }
                    ],
                }],
                max_tokens=4096,
                temperature=0.1,
            )
            content = response.choices[0].message.content
            parsed = _parse_llm_json(content)
            if parsed:
                all_results.append(parsed)
        except Exception as e:
            logger.warning(f"OpenAI extraction failed for page {i + 1}: {e}")

    return _merge_page_results(all_results) if all_results else None



def extract_with_claude(
    file_path: str,
    api_key: Optional[str] = None,
    model: str = "claude-3-haiku-20240307",
) -> Optional[dict]:
    """
    Extract using Anthropic Claude Vision API.
    Optimized for this specific account by prioritizing Haiku-3.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
        
    import requests
    images_b64 = file_to_images(file_path)
    if not images_b64:
        return None
        
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    # Tested and confirmed working for this key: Haiku 3
    models_to_try = [model, "claude-3-sonnet-20240229", "claude-3-5-sonnet-20241022"]
    
    all_results = []
    for i, img_b64 in enumerate(images_b64):
        success = False
        for m in models_to_try:
            try:
                data = {
                    "model": m,
                    "max_tokens": 4096,
                    "temperature": 0.1,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": EXTRACTION_PROMPT},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_b64
                                }
                            }
                        ]
                    }]
                }
                logger.info(f"Sending page {i + 1} to Claude API (model: {m})...")
                response = requests.post(url, headers=headers, json=data)
                
                if response.status_code == 404:
                    logger.warning(f"Claude model {m} not found (404). Trying fallback...")
                    continue
                    
                if response.status_code != 200:
                    logger.warning(f"Claude API returned {response.status_code}: {response.text}")
                    break
                    
                content = response.json()
                if "content" in content and len(content["content"]) > 0:
                    text_response = content["content"][0]["text"]
                    parsed = _parse_llm_json(text_response)
                    if parsed:
                        all_results.append(parsed)
                        success = True
                        break
            except Exception as e:
                logger.warning(f"Claude iteration failed: {e}")
                
        if not success:
            logger.error(f"Failed to extract page {i+1} with all Claude models.")

    return _merge_page_results(all_results) if all_results else None


def extract_with_deepseek(
    file_path: str,
    api_key: Optional[str] = None,
    model: str = "deepseek-chat",
    raw_text: Optional[str] = None,
) -> Optional[dict]:
    """
    Extract using DeepSeek's API (Vercel-ready).
    Uses raw text because deepseek API currently doesn't support images.
    Set DEEPSEEK_API_KEY env var.
    """
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    if not raw_text:
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                raw_text = "\n".join([page.extract_text() or "" for page in pdf.pages])
        except Exception:
            pass

    if not raw_text:
        return None

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    try:
        modified_prompt = EXTRACTION_PROMPT + "\n\n--- DOCUMENT TEXT TO PARSE ---\n" + raw_text
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": modified_prompt}],
            max_tokens=4096,
            temperature=0.1,
        )
        content = response.choices[0].message.content
        parsed = _parse_llm_json(content)
        if parsed:
            return parsed
    except Exception as e:
        logger.warning(f"DeepSeek extraction failed: {e}")

    return None


# ─── Unified Extraction Function ─────────────────────────────────────────────

def extract_with_vision_llm(file_path: str, raw_text: Optional[str] = None) -> Optional[BOLDocument]:
    """
    Try available vision LLM backends in an order that supports Vercel Serverless.
    
    1. Claude (Cloud - Best for OCR and Structure)
    2. Gemini (Cloud - Fast/Cheap for Vercel)
    3. Datalab API (Native Document JSON Extraction)
    4. OpenAI (Cloud - best for Vercel)
    5. DeepSeek (Cloud - best for Vercel)
    6. Ollama (Local only - crashes Vercel)

    Returns a BOLDocument or None if it fails.
    """
    raw_result = None
    backend = None

    # 1. Google Gemini (Fast, cheap, and now #1 per user request)
    if not raw_result and os.environ.get("GEMINI_API_KEY"):
        logger.info("Trying Gemini structured extraction...")
        try:
            raw_result = extract_with_gemini(file_path)
            if raw_result: backend = "gemini"
        except Exception as e:
            logger.warning(f"Gemini extraction crashed: {e}")

    # 2. Claude 3.5/3.7/Haiku (Cloud - Reliable fallback)
    if not raw_result and os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("Trying Claude structured extraction...")
        try:
            raw_result = extract_with_claude(file_path)
            if raw_result: backend = "claude"
        except Exception as e:
            logger.warning(f"Claude extraction crashed: {e}")

    # 3. Datalab API (Native Document JSON Extraction)
    if not raw_result and os.environ.get("DATALAB_API_KEY"):
        logger.info("Trying Datalab.to structured extraction...")
        try:
            raw_result = extract_with_datalab(file_path)
            if raw_result: backend = "datalab"
        except Exception as e:
            logger.warning(f"Datalab extraction crashed: {e}")

    # 4. OpenAI / DeepSeek (Vercel-ready Cloud APIs)
    if not raw_result and os.environ.get("OPENAI_API_KEY"):
        logger.info("Trying OpenAI vision extraction...")
        try:
            raw_result = extract_with_openai(file_path)
            if raw_result: backend = "openai"
        except Exception as e:
            logger.warning(f"OpenAI extraction crashed: {e}")
        
    if not raw_result and os.environ.get("DEEPSEEK_API_KEY"):
        logger.info("Trying DeepSeek API extension...")
        try:
            raw_result = extract_with_deepseek(file_path, raw_text=raw_text)
            if raw_result: backend = "deepseek"
        except Exception as e:
            logger.warning(f"DeepSeek extraction crashed: {e}")

    # Local Engine Fallback (for local testing)
    if not raw_result:
        logger.info("Trying Ollama vision extraction...")
        raw_result = extract_with_ollama(file_path)
        if raw_result: backend = "ollama"

    if not raw_result:
        logger.warning("No verification LLM responded (Check your API Keys or Ollama).")
        return None

    # Convert raw dict to BOLDocument
    doc = _dict_to_bol_document(raw_result, file_path)
    if doc:
        doc.verification_method = backend
    return doc

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_llm_json(text: str) -> Optional[dict]:
    """
    Parse JSON from LLM response, handling common formatting issues.
    LLMs sometimes wrap JSON in markdown code blocks.
    """
    # Strip markdown code block if present
    text = text.strip()
    if text.startswith('```'):
        # Remove ```json and trailing ```
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def _merge_page_results(results: list[dict]) -> dict:
    """
    Merge extraction results from multiple pages into a single result.
    First page usually has the most data; subsequent pages add to it.
    """
    if not results:
        return {}
    if len(results) == 1:
        return results[0]

    merged = results[0].copy()

    for result in results[1:]:
        # Merge references
        if 'references' in result and result['references']:
            merged.setdefault('references', {})
            merged['references'].update(result['references'])

        # Merge parties (avoid duplicates)
        if 'parties' in result and result['parties']:
            existing_roles = {p.get('role') for p in merged.get('parties', [])}
            for party in result['parties']:
                if party.get('role') not in existing_roles:
                    merged.setdefault('parties', []).append(party)

        # Merge line items
        if 'line_items' in result and result['line_items']:
            merged.setdefault('line_items', []).extend(result['line_items'])

        # Fill in missing fields from later pages
        for key in ['carrier', 'vessel_info', 'container_info', 'shipping_details', 'totals']:
            if key in result and result[key] and not merged.get(key):
                merged[key] = result[key]

    return merged


def _dict_to_bol_document(data: dict, file_path: str) -> BOLDocument:
    """Convert a raw LLM-extracted dict to a proper BOLDocument."""
    # Ensure references is ALWAYS a dict for BOLDocument instantiation
    refs = data.get('references')
    if not isinstance(refs, dict):
        refs = {}

    doc = BOLDocument(
        document_type=data.get('document_type', 'unknown'),
        document_subtype=data.get('document_subtype'),
        document_date=data.get('document_date'),
        references=refs,
        extraction_method="vision_llm",
    )

    # 1. Parties (Safe Block)
    try:
        parties_raw = data.get('parties') or []
        for p in parties_raw:
            if not isinstance(p, dict): continue
            addr_data = p.get('address') or p
            addr = Address(
                name=p.get('name') or addr_data.get('name'),
                address_line_1=addr_data.get('address') or addr_data.get('address_line_1'),
                city=addr_data.get('city'),
                state=addr_data.get('state'),
                zip_code=addr_data.get('zip_code'),
                phone=addr_data.get('phone'),
            )
            doc.parties.append(Party(role=p.get('role', 'unknown'), address=addr))
    except Exception as e:
        logger.warning(f"Failed to parse parties section: {e}")

    # 2. Carrier (Safe Block)
    try:
        carrier_data = data.get('carrier')
        if carrier_data and isinstance(carrier_data, dict):
            doc.carrier = CarrierInfo(
                name=carrier_data.get('name'),
                scac=carrier_data.get('scac'),
                pro_number=carrier_data.get('pro_number'),
            )
    except Exception as e:
        logger.warning(f"Failed to parse carrier section: {e}")

    # 3. Vessel / Container (Safe Block)
    try:
        vessel_data = data.get('vessel_info')
        if vessel_data and isinstance(vessel_data, dict):
            doc.vessel_info = VesselInfo(
                vessel_name=vessel_data.get('vessel_name'),
                voyage_number=vessel_data.get('voyage_number'),
                eta=vessel_data.get('eta'),
            )
        container_data = data.get('container_info')
        if container_data and isinstance(container_data, dict):
            doc.container_info = ContainerInfo(
                container_number=container_data.get('container_number'),
                container_size=container_data.get('container_size'),
                seal_number=container_data.get('seal_number'),
            )
    except Exception as e:
        logger.warning(f"Failed to parse transport info: {e}")

    # 4. Shipping Details (Safe Block)
    try:
        sd = data.get('shipping_details')
        if sd and isinstance(sd, dict):
            doc.shipping_details = ShippingDetails(
                pickup_date=sd.get('pickup_date'),
                estimated_delivery=sd.get('estimated_delivery'),
                freight_terms=sd.get('freight_terms'),
                special_instructions=sd.get('special_instructions'),
            )
    except Exception as e:
        logger.warning(f"Failed to parse shipping details: {e}")

    # 5. Line items (Safe Block)
    try:
        items_raw = data.get('line_items') or []
        for item_data in items_raw:
            if isinstance(item_data, dict):
                doc.line_items.append(LineItem(
                    description=item_data.get('description'),
                    quantity=item_data.get('quantity'),
                    packaging_type=item_data.get('packaging_type'),
                    weight=item_data.get('weight'),
                    weight_unit=item_data.get('weight_unit', 'lbs'),
                    carton_count=item_data.get('carton_count'),
                ))
    except Exception as e:
        logger.warning(f"Failed to parse line items: {e}")

    # 6. Totals (Safe Block)
    try:
        totals_data = data.get('totals')
        if totals_data and isinstance(totals_data, dict):
            doc.totals = Totals(
                total_pieces=totals_data.get('total_pieces'),
                total_weight=totals_data.get('total_weight'),
                total_cartons=totals_data.get('total_cartons'),
            )
    except Exception as e:
        logger.warning(f"Failed to parse totals: {e}")

    # Read raw text from file for reference
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            texts = [p.extract_text() or "" for p in pdf.pages]
            doc.raw_text = "\n\n".join(texts)
    except Exception:
        doc.raw_text = "[Vision LLM extraction — raw text not available]"

    doc.compute_confidence()
    return doc
