"""
process_document.py — Core interface as specified by the assignment.

    def process_document(file_path: str) -> dict:

Orchestrates: extract → classify (3 dimensions) → parse → validate → return

This is the single entry point for everything — CLI, API, and tests.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from extractors.pdfplumber_extractor import PdfPlumberExtractor
from classifier import classify_document_full, DocumentType
from parsers.ltl_bol_parser import LTLBOLParser
from parsers.ocean_bol_parser import OceanBOLParser
from parsers.generic_parser import GenericParser
from schema import BOLDocument

logger = logging.getLogger(__name__)


def process_document(file_path: str) -> dict:
    """
    Process a PDF document and extract structured data.

    Args:
        file_path: Path to the PDF file.

    Returns:
        dict: Structured data following the BOLDocument schema.
              Always returns a result — never raises on bad input.
    """
    file_path = str(Path(file_path).resolve())

    # ── Validate Input ──
    if not os.path.exists(file_path):
        return _error_result(f"File not found: {file_path}")

    # ── Image Fast-Track ──
    ext = file_path.lower().split('.')[-1]
    if ext in ['png', 'jpg', 'jpeg', 'webp']:
        logger.info(f"Image file detected ({ext}). Bypassing PDF regex parser. Fast-tracking to Vision LLM...")
        try:
            from llm.vision_extractor import extract_with_vision_llm
            vision_doc = extract_with_vision_llm(file_path)
            if not vision_doc:
                return _error_result("Extraction failed: Vision LLM could not process the image or was unavailable.")
            
            vision_doc.extraction_method = vision_doc.verification_method or "vision_llm"
            vision_doc.is_verified = False
            vision_doc.extraction_warnings.append("Parsed from Image input. Single-pass extraction (no regex baseline).")
            return json.loads(vision_doc.to_json())
        except Exception as e:
            return _error_result(f"Vision LLM crash on image input: {e}")

    # ── Verify PDF Input ──
    if ext != 'pdf':
        return _error_result(f"Unsupported file format: {file_path}")

    # ── Step 1: Extract text with pdfplumber (PDF ONLY) ──
    logger.info(f"Extracting text from: {file_path}")
    extractor = PdfPlumberExtractor()
    extraction = extractor.extract(file_path)

    # ── Step 2: Attempt Dual Extraction for Verification ──
    primary_doc = None
    if extraction.has_text:
        # Text-based path: classify → parse with regex
        logger.info(f"Text extraction successful ({len(extraction.raw_text)} chars)")
        primary_doc = _text_based_extraction(extraction)

    # Secondary: Vision LLM
    logger.info("Attempting Vision LLM extraction for verification...")
    vision_doc = None
    try:
        from llm.vision_extractor import extract_with_vision_llm
        # extract_with_vision_llm already handles the fallback logic: Ollama first, then DeepSeek
        vision_doc = extract_with_vision_llm(
            file_path, 
            raw_text=extraction.raw_text if extraction.has_text else None
        )
    except Exception as e:
        logger.warning(f"Vision LLM extraction failed: {e}")

    # ── Step 3: Verification Engine ──
    from verifier import verify_documents
    
    if primary_doc and vision_doc:
        logger.info("Running dual verification engine...")
        doc = verify_documents(primary_doc, vision_doc)
    elif primary_doc:
        logger.info("Vision LLM failed/unavailable. Returning unverified primary document.")
        doc = primary_doc
        doc.extraction_warnings.append("Unverified: Vision LLM fallback was unavailable.")
    elif vision_doc:
        logger.info("No text extracted. Returning vision LLM document (unverified against text).")
        doc = vision_doc
        doc.extraction_warnings.append("Unverified: No text found to compare against Vision LLM.")
    else:
        # Final fallback: try generic parser on whatever text we have
        logger.info("Falling back to generic text parser as last resort")
        parser = GenericParser()
        doc = parser.parse(extraction)
        doc.extraction_warnings.append("Vision LLM unavailable and text extraction failed. Using generic parser.")

    # ── Step 4: Validate and return ──
    result = json.loads(doc.to_json())
    return result


def _text_based_extraction(extraction) -> BOLDocument:
    """
    Text-based extraction pipeline: classify (3 dimensions) → route to parser.
    """
    # Full three-dimensional classification
    result = classify_document_full(extraction.raw_text)
    logger.info(
        f"Classified as: parser={result.parser_type.value} "
        f"(conf={result.parser_confidence}), "
        f"functional={result.classification.functional_type}, "
        f"regulatory={result.classification.regulatory_type}, "
        f"transport={result.classification.transport_mode}"
    )

    # Route to appropriate parser
    parser_map = {
        DocumentType.BOL_LTL: LTLBOLParser(),
        DocumentType.BOL_OCEAN: OceanBOLParser(),
        DocumentType.BOL_GENERIC: GenericParser(),
        DocumentType.UNKNOWN: GenericParser(),
    }

    parser = parser_map.get(result.parser_type, GenericParser())
    doc = parser.parse(extraction)

    # ── Attach classification to document ──
    doc.classification = result.classification

    # Add classification confidence to warnings if low
    if result.parser_confidence < 0.3:
        doc.extraction_warnings.append(
            f"Low classification confidence ({result.parser_confidence}). "
            "Document type may be incorrect."
        )

    # Add hazmat warning if detected
    if result.classification.is_hazmat:
        doc.extraction_warnings.append(
            "HAZMAT: Hazardous materials detected. "
            "Verify DOT compliance (49 CFR 172/173)."
        )

    return doc





def _error_result(message: str) -> dict:
    """Create an error result that still follows the schema."""
    doc = BOLDocument(
        document_type="error",
        extraction_method="none",
        extraction_confidence=0.0,
        extraction_warnings=[message],
    )
    return json.loads(doc.to_json())
