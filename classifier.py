"""
classifier.py — Three-dimensional document classification.

Classifies BOLs across three dimensions:
  1. Functional Type: Straight, Order, Master, Through, Ocean
  2. Regulatory Type: General, Hazmat, Household Goods
  3. Transport Mode: LTL, TL, Ocean, Air, Intermodal

Each dimension uses independent keyword scoring so they compose correctly.
For example: a document can be Ocean + Hazmat + TL simultaneously.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from schema import DocumentClassification


# ═══════════════════════════════════════════════════════════════════════════════
# Dimension 1: Transport Mode (parser routing)
# ═══════════════════════════════════════════════════════════════════════════════

class DocumentType(Enum):
    """Parser routing types — determines which parser handles extraction."""
    BOL_LTL = "bol_ltl"
    BOL_OCEAN = "bol_ocean"
    BOL_GENERIC = "bol_generic"
    UNKNOWN = "unknown"


# Parser routing signatures (kept for backward compat)
TYPE_SIGNATURES = {
    DocumentType.BOL_LTL: {
        'strong': [
            r'LTL\s*CLASS',
            r'NMFC',
            r'FREIGHT\s+PRIORITY',
            r'3RD\s+PARTY\s+(PPD|COLLECT)',
            r'ACCESSORIALS?',
        ],
        'moderate': [
            r'BILL\s+OF\s+LADING',
            r'PRO[\s:#]+',
            r'EST\.?\s*DELIVERY',
            r'PICKUP\s+DATE',
            r'ORIGIN\s+TERMINAL',
            r'DESTINATION\s+TERMINAL',
            r'\bPLT\b',
            r'HANDLING\s+UNIT',
        ],
    },
    DocumentType.BOL_OCEAN: {
        'strong': [
            r'VESSEL',
            r'VOYAGE',
            r'CONTAINER\s*(SIZE|NUMBER|#|:)',
            r'SEAL\s*(NUMBER|#|:)',
            r'SSL\s+SCAC',
            r'DRAY\s+SCAC',
            r'\b(CBM|CUBIC\s+METERS?)\b',
        ],
        'moderate': [
            r'BILL\s+OF\s+LADING',
            r'\bETA\b',
            r'PORT\s+OF\s+(ORIGIN|LOADING|DISCHARGE)',
            r'DIN\s*#',
            r'FBA\s+FCL',
            r'\bCARTONS?\b',
            r'SHIP\s+FROM',
            r'SHIP\s+TO',
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# Dimension 1: Functional & Legal Type
# ═══════════════════════════════════════════════════════════════════════════════

FUNCTIONAL_SIGNALS = {
    'ocean': {
        'patterns': [
            (r'VESSEL\s*(NAME)?[:\s]', 'Vessel name field present'),
            (r'VOYAGE\s*(NUMBER|#)?[:\s]', 'Voyage number present'),
            (r'PORT\s+OF\s+(LOADING|ORIGIN)', 'Port of loading present'),
            (r'PORT\s+OF\s+(DISCHARGE|DESTINATION)', 'Port of discharge present'),
            (r'CONTAINER\s*(NUMBER|SIZE|#)', 'Container info present'),
            (r'SEAL\s*(NUMBER|#)', 'Seal number (maritime)'),
            (r'SSL\s+SCAC', 'Steamship line SCAC code'),
        ],
        'threshold': 2,  # Need at least 2 signals
    },
    'master': {
        'patterns': [
            (r'MASTER\s+BILL\s+OF\s+LADING', 'Master BOL title'),
            (r'MASTER\s+B/?L', 'Master B/L indicator'),
            (r'UNDERLYING\s+BILL', 'References underlying BOLs'),
            (r'CONSOLIDATED\s+SHIPMENT', 'Consolidation language'),
            (r'MULTI[\s-]?STOP', 'Multi-stop truckload'),
        ],
        'threshold': 1,
    },
    'order': {
        'patterns': [
            (r'TO\s+ORDER\b', '"To order" negotiable language'),
            (r'NEGOTIATE', 'Negotiable instrument language'),
            (r'ENDORSEMENT', 'Endorsement section present'),
            (r'ORDER\s+BILL\s+OF\s+LADING', 'Order BOL title'),
            (r'NEGOTIABLE', 'Negotiable label'),
        ],
        'threshold': 1,
    },
    'through': {
        'patterns': [
            (r'THROUGH\s+BILL\s+OF\s+LADING', 'Through BOL title'),
            (r'INTERMODAL\s+BILL', 'Intermodal bill'),
            (r'CONNECTING\s+CARRIER', 'Multiple carriers listed'),
            (r'TRANSFER\s+AT', 'Transfer point between modes'),
        ],
        'threshold': 1,
    },
    # 'straight' is the default if none of the above match
}


# ═══════════════════════════════════════════════════════════════════════════════
# Dimension 2: Regulatory & Commodity Type
# ═══════════════════════════════════════════════════════════════════════════════

REGULATORY_SIGNALS = {
    'hazmat': {
        'patterns': [
            (r'H\.?\s*M\.?\s*\(X\)|HM\s+X|\bX\b.*H\.?M\.?', 'H.M. column marked X'),
            (r'\bUN\d{4}\b', 'UN identification number (e.g. UN3480)'),
            (r'\bNA\d{4}\b', 'NA identification number'),
            (r'HAZARD\s*CLASS', 'Hazard class field'),
            (r'PACKING\s+GROUP', 'Packing group field'),
            (r'PROPER\s+SHIPPING\s+NAME', 'Proper shipping name field'),
            (r'24[\s-]*HOUR\s+EMERGENCY', '24-hour emergency contact'),
            (r'HAZARDOUS\s+MATERIAL', 'Hazardous material label'),
            (r'HAZMAT', 'Hazmat abbreviation'),
            (r'DANGEROUS\s+GOODS', 'Dangerous goods label'),
            (r'PLACARD', 'Placard requirement'),
            (r'DOT\s+SPECIAL\s+PERMIT', 'DOT special permit'),
            (r'49\s*CFR\s*17[23]', 'DOT hazmat regulation reference'),
        ],
        'threshold': 2,  # Need 2+ signals — single hit may be boilerplate text
    },
    'household': {
        'patterns': [
            (r'HOUSEHOLD\s+GOODS', 'Household goods label'),
            (r'49\s*CFR\s*375', 'FMCSA household goods regulation'),
            (r'FULL\s+VALUE\s+PROTECTION', 'Full value protection terms'),
            (r'RELEASED\s+RATE', 'Released rate option'),
            (r'ESTIMATED\s+WEIGHT\s+OF\s+SHIPMENT', 'Consumer move weight estimate'),
            (r'INVENTORY\s+OF\s+PERSONAL\s+PROPERTY', 'Personal property inventory'),
            (r'VEHICLE\s+IDENTIFICATION\s+NUMBER', 'VIN for transport vehicle'),
        ],
        'threshold': 1,
    },
    # 'general' is the default (49 CFR 373.101)
}


# ═══════════════════════════════════════════════════════════════════════════════
# Dimension 3: Transport Mode
# ═══════════════════════════════════════════════════════════════════════════════

TRANSPORT_MODE_SIGNALS = {
    'ltl': {
        'patterns': [
            (r'\bPRO[\s#:]+\S', 'PRO number (LTL tracking)'),
            (r'\bNMFC\b', 'NMFC number present'),
            (r'LTL\s*CLASS', 'LTL freight class'),
            (r'FREIGHT\s+CLASS\s*[:\s]\s*\d', 'Freight class value'),
            (r'ACCESSORIALS?', 'Accessorials section'),
            (r'ORIGIN\s+TERMINAL', 'Origin terminal (LTL network)'),
            (r'DESTINATION\s+TERMINAL', 'Destination terminal (LTL network)'),
        ],
        'threshold': 2,
    },
    'tl': {
        'patterns': [
            (r'TRAILER\s*(NUMBER|#|NO)', 'Trailer number present'),
            (r'TRAILER[\s#:]+[A-Z0-9]{4,}', 'Trailer ID value'),
            (r'SEAL\s*(NUMBER|#|NO)\s*[:\s]+\S', 'Seal number (TL)'),
            (r'RECEIVING\s+STAMP', 'Receiving stamp space'),
            (r'FULL\s*TRUCK\s*LOAD', 'Full truckload label'),
            (r'\bFTL\b', 'FTL abbreviation'),
            (r'\bTL\b(?!.*CLASS)', 'TL abbreviation'),
        ],
        'threshold': 2,
    },
    'ocean': {
        'patterns': [
            (r'VESSEL', 'Vessel field'),
            (r'VOYAGE', 'Voyage field'),
            (r'\bCBM\b', 'CBM (cubic meters)'),
            (r'DRAY', 'Drayage reference'),
        ],
        'threshold': 2,
    },
    'air': {
        'patterns': [
            (r'AIR\s*WAY\s*BILL', 'Air waybill'),
            (r'FLIGHT\s*(NUMBER|#)', 'Flight number'),
            (r'IATA\s+CODE', 'IATA code'),
            (r'\bAWB\b', 'AWB abbreviation'),
        ],
        'threshold': 2,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# Classification Engine
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ClassificationResult:
    """Full classification output."""
    parser_type: DocumentType
    parser_confidence: float
    classification: DocumentClassification


def classify_document(text: str) -> tuple[DocumentType, float]:
    """
    Classify document for parser routing (backward compatible).
    Returns (DocumentType, confidence).
    """
    result = classify_document_full(text)
    return (result.parser_type, result.parser_confidence)


def classify_document_full(text: str) -> ClassificationResult:
    """
    Full three-dimensional classification.
    Returns ClassificationResult with parser routing + DocumentClassification.
    """
    text_upper = text.upper()
    classification = DocumentClassification()

    # ── Dimension 1: Functional Type ──
    functional_type, func_signals = _classify_dimension(text_upper, FUNCTIONAL_SIGNALS)
    classification.functional_type = functional_type or "straight"
    classification.functional_type_signals = func_signals

    # Set quick flags
    if functional_type == "master":
        classification.is_master_bol = True
    if functional_type == "order":
        classification.is_negotiable = True

    # ── Dimension 2: Regulatory Type ──
    regulatory_type, reg_signals = _classify_dimension(text_upper, REGULATORY_SIGNALS)
    classification.regulatory_type = regulatory_type or "general"
    classification.regulatory_type_signals = reg_signals

    if regulatory_type == "hazmat":
        classification.is_hazmat = True

    # ── Dimension 3: Transport Mode ──
    transport_mode, mode_signals = _classify_dimension(text_upper, TRANSPORT_MODE_SIGNALS)
    classification.transport_mode = transport_mode
    classification.transport_mode_signals = mode_signals

    # ── Parser Routing (backward compat) ──
    parser_type, parser_confidence = _route_to_parser(text_upper)

    return ClassificationResult(
        parser_type=parser_type,
        parser_confidence=parser_confidence,
        classification=classification,
    )


def _classify_dimension(
    text_upper: str,
    signal_groups: dict,
) -> tuple[Optional[str], list[str]]:
    """
    Score text against signal groups for a classification dimension.
    Returns (best_type, list_of_matched_signals).
    """
    best_type = None
    best_count = 0
    best_signals = []

    for type_name, config in signal_groups.items():
        matched_signals = []
        for pattern, signal_name in config['patterns']:
            if re.search(pattern, text_upper):
                matched_signals.append(signal_name)

        if len(matched_signals) >= config['threshold'] and len(matched_signals) > best_count:
            best_type = type_name
            best_count = len(matched_signals)
            best_signals = matched_signals

    return (best_type, best_signals)


def _route_to_parser(text_upper: str) -> tuple[DocumentType, float]:
    """Route to a parser based on transport mode keywords (original logic)."""
    scores = {}

    for doc_type, signatures in TYPE_SIGNATURES.items():
        score = 0
        max_possible = len(signatures['strong']) * 2 + len(signatures['moderate'])

        for pattern in signatures['strong']:
            if re.search(pattern, text_upper):
                score += 2

        for pattern in signatures['moderate']:
            if re.search(pattern, text_upper):
                score += 1

        scores[doc_type] = score / max_possible if max_possible > 0 else 0

    if not scores:
        return (DocumentType.UNKNOWN, 0.0)

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    if best_score < 0.15:
        if re.search(r'BILL\s+OF\s+LADING', text_upper):
            return (DocumentType.BOL_GENERIC, 0.3)
        return (DocumentType.UNKNOWN, 0.0)

    return (best_type, round(best_score, 2))
