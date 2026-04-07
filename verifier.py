"""
verifier.py — Verification Engine for comparing document extractions.

Takes a primary structured document (e.g., from determinist regex mapping)
and a secondary verification document (e.g., from a Vision LLM), and
compares them field-by-field.

Produces a consolidated BOLDocument that flags discrepancies or boosts
confidence if the two models agree.
"""

from __future__ import annotations

import logging
from typing import Any

from schema import BOLDocument

logger = logging.getLogger(__name__)


def verify_documents(primary: BOLDocument, verification: BOLDocument) -> BOLDocument:
    """
    Compare primary extraction against a verification extraction.
    
    Returns the primary document, augmented with verification status
    and details regarding any mismatched fields.
    """
    discrepancies = []
    match_count = 0
    total_comparisons = 0

    # 1. Compare Document Level Metadata
    if _compare(primary.document_type, verification.document_type):
        match_count += 1
    elif primary.document_type and verification.document_type and verification.document_type != "error":
        discrepancies.append(f"document_type: primary='{primary.document_type}', llm='{verification.document_type}'")
    total_comparisons += 1

    if _compare(primary.document_date, verification.document_date):
        match_count += 1
    elif primary.document_date and verification.document_date:
        discrepancies.append(f"document_date: primary='{primary.document_date}', llm='{verification.document_date}'")
    total_comparisons += 1

    # 2. Compare References
    p_refs = primary.references
    v_refs = verification.references
    for key in set(p_refs.keys()).union(v_refs.keys()):
        p_val = p_refs.get(key)
        v_val = v_refs.get(key)
        
        # Merge if primary missed it entirely
        if not p_val and v_val:
            primary.references[key] = v_val
            continue
            
        if p_val and v_val:
            total_comparisons += 1
            if _compare(p_val, v_val):
                match_count += 1
            else:
                if _is_suspicious_extraction(p_val):
                    discrepancies.append(f"Auto-resolved references.{key} (Overwrote suspicious primary '{p_val}' with LLM '{v_val}')")
                    primary.references[key] = v_val
                else:
                    discrepancies.append(f"references.{key}: primary='{p_val}', llm='{v_val}'")

    # 3. Compare Carrier Info
    if primary.carrier and verification.carrier:
        p_name = primary.carrier.name
        v_name = verification.carrier.name
        
        if not p_name and v_name: primary.carrier.name = v_name
        if p_name and v_name:
            total_comparisons += 1
            if _compare(p_name, v_name):
                match_count += 1
            else:
                if _is_suspicious_extraction(p_name):
                    discrepancies.append(f"Auto-resolved carrier.name (Overwrote suspicious primary '{p_name}' with LLM '{v_name}')")
                    primary.carrier.name = v_name
                else:
                    discrepancies.append(f"carrier.name: primary='{p_name}', llm='{v_name}'")
        
        p_scac = primary.carrier.scac
        v_scac = verification.carrier.scac
        
        if not p_scac and v_scac: primary.carrier.scac = v_scac
        if p_scac and v_scac:
            total_comparisons += 1
            if _compare(p_scac, v_scac):
                match_count += 1
            else:
                if _is_suspicious_extraction(p_scac):
                    discrepancies.append(f"Auto-resolved carrier.scac (Overwrote suspicious primary '{p_scac}' with LLM '{v_scac}')")
                    primary.carrier.scac = v_scac
                else:
                    discrepancies.append(f"carrier.scac: primary='{p_scac}', llm='{v_scac}'")

    # 4. Compare Totals
    if primary.totals and verification.totals:
        p_wt = primary.totals.total_weight
        v_wt = verification.totals.total_weight
        if p_wt and v_wt:
            total_comparisons += 1
            if abs(float(p_wt) - float(v_wt)) < 0.1:
                match_count += 1
            else:
                discrepancies.append(f"totals.total_weight: primary='{p_wt}', llm='{v_wt}'")
        
        p_pcs = primary.totals.total_pieces
        v_pcs = verification.totals.total_pieces
        if p_pcs is not None and v_pcs is not None:
            total_comparisons += 1
            if int(p_pcs) == int(v_pcs):
                match_count += 1
            else:
                discrepancies.append(f"totals.total_pieces: primary='{p_pcs}', llm='{v_pcs}'")

    # Attach verification results to the primary document
    primary.verification_discrepancies = discrepancies
    primary.verification_method = verification.verification_method
    
    # Calculate agreement ratio (ignoring fields where one model found None)
    if total_comparisons > 0:
        agreement_ratio = match_count / total_comparisons
        logger.info(f"Verification completed. Agreement ratio: {agreement_ratio:.2f} ({match_count}/{total_comparisons})")
        
        primary.extraction_method = f"pdfplumber + {verification.verification_method}"
        
        if agreement_ratio > 0.8 and not discrepancies:
            primary.is_verified = True
            primary.extraction_confidence = min(1.0, primary.extraction_confidence + 0.2)
        else:
            primary.is_verified = False
            primary.extraction_warnings.append(
                f"Verification flagged {len(discrepancies)} discrepancies between extraction models."
            )
    else:
        primary.is_verified = False
        primary.extraction_warnings.append("Verification engine had nothing to compare.")

    return primary


def _compare(val1: Any, val2: Any) -> bool:
    """Robust string comparison ignoring case and whitespace differences."""
    if val1 is None and val2 is None:
        return True
    if val1 is None or val2 is None:
        return False
    
    s1 = str(val1).strip().lower()
    s2 = str(val2).strip().lower()
    
    # 1. Direct or partial match (e.g. SCAC "MAEU" inside "MAERSK LINE MAEU")
    if s1 in s2 or s2 in s1:
        return True
    
    # 2. Hard equivalence (no spaces, no punct)
    import re
    c1 = re.sub(r'[\W_]+', '', s1)
    c2 = re.sub(r'[\W_]+', '', s2)
    if not c1 or not c2: return False
    if c1 == c2: return True

    # 3. Fuzzy match for SCACs (if one is 4 chars and the other is a full name)
    # e.g. "FXFE" should match "FedEx"
    if (len(c1) == 4 and c1 in c2) or (len(c2) == 4 and c2 in c1):
        return True
        
    return False


def _is_suspicious_extraction(val1: Any) -> bool:
    """
    Check if the primary extraction (usually regex) looks like garbage, 
    a table header, or redundant text.
    """
    if not val1:
        return True
    
    v = str(val1).strip()
    
    # 1. Ends with a colon (likely a field label captured by regex)
    if v.endswith(':'):
        return True
        
    # 2. Too long with too many spaces (likely a whole line of text or instructions)
    if len(v) > 25 and v.count(' ') > 3:
        return True
        
    # 3. Known header/boilerplate patterns
    boilerplate = [
        'dcpo type dept', 'item weight cbm', 'weight unit', 
        'special instructions', 'carrier name', 'pro number'
    ]
    v_lower = v.lower()
    if any(bp in v_lower for bp in boilerplate):
        return True
        
    # 4. Very short garbage (1-2 chars of punctuation)
    import re
    if len(v) < 3 and not re.search(r'[a-zA-Z0-9]', v):
        return True

    return False

