"""
parsers/generic_parser.py — Fallback parser for unknown/unrecognized documents.

When the classifier can't determine the document type, this parser
extracts whatever it can find using general-purpose heuristics:
- Any address-like blocks
- Any reference numbers
- Any dates
- Any tabular data

This is the safety net for the live session.
"""

from __future__ import annotations

import re

from extractors.base import ExtractionResult
from parsers.base import BaseBOLParser
from schema import (
    BOLDocument, Party, Address, ShippingDetails,
    LineItem, Totals,
)
from utils import (
    parse_address_block,
    extract_dates,
    normalize_date,
    ADDRESS_PATTERN,
    REF_NUMBER_PATTERN,
    WEIGHT_PATTERN,
    safe_float,
)


class GenericParser(BaseBOLParser):
    """
    Best-effort parser for unknown document types.
    Extracts anything recognizable using general heuristics.
    """

    def parse(self, extraction: ExtractionResult) -> BOLDocument:
        """Extract whatever we can from an unknown document."""
        text = extraction.raw_text
        doc = BOLDocument(
            document_type="unknown",
            document_subtype="generic",
            extraction_method="pdfplumber",
            raw_text=text,
        )

        # ── Dates ──
        dates = extract_dates(text)
        if dates:
            doc.document_date = normalize_date(dates[0])

        # ── Addresses ──
        doc.parties = self._find_addresses(text)

        # ── Reference Numbers ──
        doc.references = self._find_references(text)

        # ── Weights ──
        weight_matches = WEIGHT_PATTERN.findall(text)
        if weight_matches:
            total_weight = sum(float(w[0].replace(',', '')) for w in weight_matches)
            doc.totals = Totals(total_weight=total_weight)

        # ── Tables ──
        if extraction.tables:
            doc.line_items = self._parse_generic_tables(extraction.tables)

        # ── Shipping details from any special instructions ──
        for label in ['Special Instructions', 'Instructions', 'Notes', 'Comments']:
            from utils import extract_field_after_label
            value = extract_field_after_label(text, label)
            if value:
                doc.shipping_details = ShippingDetails(special_instructions=value)
                break

        # Low confidence for generic extraction
        doc.extraction_warnings.append("Generic parser used — document type not recognized")
        doc.compute_confidence()
        # Cap generic parser confidence
        doc.extraction_confidence = min(doc.extraction_confidence, 0.5)

        return doc

    def _find_addresses(self, text: str) -> list[Party]:
        """Find all address-like blocks in the text."""
        parties = []
        seen = set()

        # Look for labeled address blocks
        for label, role in [
            ('Ship From', 'shipper'),
            ('Shipper', 'shipper'),
            ('From', 'shipper'),
            ('Ship To', 'consignee'),
            ('Consignee', 'consignee'),
            ('To', 'consignee'),
            ('Bill To', 'third_party_billing'),
            ('Sold To', 'buyer'),
        ]:
            pattern = re.compile(
                rf'{re.escape(label)}[:\s]*(.*?)(?:\n\n|\Z)',
                re.DOTALL | re.IGNORECASE
            )
            match = pattern.search(text)
            if match and role not in seen:
                addr_text = match.group(1).strip()[:200]  # Limit block size
                if addr_text and ADDRESS_PATTERN.search(addr_text):
                    addr = parse_address_block(addr_text)
                    parties.append(Party(role=role, address=addr))
                    seen.add(role)

        return parties

    def _find_references(self, text: str) -> dict[str, str]:
        """Find reference numbers using common label patterns."""
        refs = {}
        common_labels = {
            'bol_number': ['BOL', 'B/L', 'Bill of Lading'],
            'po_number': ['PO', 'Purchase Order'],
            'pro_number': ['PRO'],
            'reference': ['Ref', 'Reference'],
            'invoice': ['Invoice', 'Inv'],
            'order': ['Order', 'Order#'],
        }

        for ref_name, labels in common_labels.items():
            for label in labels:
                pattern = re.compile(
                    rf'{re.escape(label)}\s*[#:]?\s*([A-Z0-9]{{4,}})',
                    re.IGNORECASE
                )
                match = pattern.search(text)
                if match:
                    refs[ref_name] = match.group(1)
                    break

        return refs

    def _parse_generic_tables(self, tables: list) -> list[LineItem]:
        """Convert any detected tables into generic line items."""
        items = []
        for table in tables:
            if len(table) < 2:
                continue
            header = [str(c).strip() for c in table[0]]
            for row in table[1:]:
                if not row or all(not str(c).strip() for c in row):
                    continue
                # Create a description from all non-empty cells
                desc = ' | '.join(
                    f"{header[i]}: {str(row[i]).strip()}"
                    for i in range(min(len(header), len(row)))
                    if str(row[i]).strip()
                )
                if desc:
                    items.append(LineItem(description=desc))
        return items
