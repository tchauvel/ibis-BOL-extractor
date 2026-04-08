"""
parsers/ltl_bol_parser.py — Parser for domestic LTL (Less-Than-Truckload) BOLs.

Targets documents like DEN5755177.pdf:
- FedEx Freight, UPS Freight, etc.
- Grid/table layout with carrier info, terminals, references
- Item table: Qty, Type, Weight, NMFC, LTL Class, H.M. column

Enhanced with:
- Zone-based coordinate extraction for layout-aware address parsing
- Fuzzy table header matching for cross-carrier compatibility
- Mathematical verification (line item weights vs. total weight)
"""

from __future__ import annotations

import logging
import re

from extractors.base import ExtractionResult
from extractors.pdfplumber_extractor import PdfPlumberExtractor
from parsers.base import BaseBOLParser
from schema import (
    BOLDocument, Party, Address, CarrierInfo,
    ShippingDetails, LineItem, Totals, HazmatInfo,
)
from utils import (
    extract_field_after_label,
    parse_address_block,
    normalize_date,
    safe_int,
    safe_float,
)

logger = logging.getLogger(__name__)


class LTLBOLParser(BaseBOLParser):
    """Parse domestic LTL freight Bills of Lading."""

    # Reference label patterns specific to LTL BOLs
    REFERENCE_LABELS = {
        'bol_number': ['BOL NO', 'BOL#', 'B/L NO', 'B/L#'],
        'pro_number': ['PRO', 'PRO#', 'PRO NO', 'FXFE PRO'],
        'po_number': ['PO Number', 'PO#', 'PO NO', 'PO:'],
        'shipper_reference': ['Shipper Reference', 'Shipper Ref', 'Ref:'],
        'airway_bill_number': ['Airway Bill Number', 'Airway Bill'],
        'control': ['Control'],
    }

    def parse(self, extraction: ExtractionResult) -> BOLDocument:
        """Parse LTL BOL from extracted text and tables."""
        text = extraction.raw_text
        doc = BOLDocument(
            document_type="bill_of_lading",
            document_subtype="ltl",
            extraction_method="pdfplumber",
            raw_text=text,
        )

        # ── References ──
        doc.references = self._extract_references(text, self.REFERENCE_LABELS)

        # Also try SCAC from references section
        scac = extract_field_after_label(text, 'SCAC')
        if scac:
            doc.references['scac'] = scac

        # ── Carrier ──
        carrier_name = extract_field_after_label(text, 'Carrier')

        # Check for trailer number (TL indicator)
        trailer_num = extract_field_after_label(text, 'Trailer')
        if not trailer_num:
            trailer_num = extract_field_after_label(text, 'Trailer Number')

        doc.carrier = CarrierInfo(
            name=carrier_name,
            scac=scac or doc.references.get('scac'),
            pro_number=doc.references.get('pro_number'),
            trailer_number=trailer_num,
        )

        # ── Dates ──
        pickup = extract_field_after_label(text, 'Pickup Date')
        est_delivery = extract_field_after_label(text, 'Est. Delivery')
        if not est_delivery:
            est_delivery = extract_field_after_label(text, 'Est Delivery')

        doc.document_date = normalize_date(pickup) if pickup else None

        # ── Shipping Details ──
        freight_terms = extract_field_after_label(text, 'Freight Terms')
        origin_terminal = extract_field_after_label(text, 'Origin Terminal')
        dest_terminal = extract_field_after_label(text, 'Destination Terminal')
        special = extract_field_after_label(text, 'Special Instructions')
        accessorials = extract_field_after_label(text, 'Accessorials')

        doc.shipping_details = ShippingDetails(
            pickup_date=normalize_date(pickup) if pickup else None,
            estimated_delivery=normalize_date(est_delivery) if est_delivery else None,
            freight_terms=freight_terms,
            origin_terminal=origin_terminal,
            destination_terminal=dest_terminal,
            special_instructions=special,
            accessorials=accessorials,
        )

        # ── Parties (Zone-Based + Regex Fallback) ──
        doc.parties = self._extract_parties_zone(extraction)
        if len(doc.parties) < 2:
            # Fallback: try the old regex-based approach
            doc.parties = self._extract_parties(text)

        # ── Line Items (from tables) — including H.M. column scan ──
        doc.line_items = self._extract_line_items(extraction)

        # ── Totals ──
        doc.totals = self._extract_totals(text, extraction)

        # ── Mathematical Verification ──
        self._verify_weight_totals(doc)

        # ── Confidence ──
        doc.compute_confidence()

        return doc

    # ── Zone-Based Party Extraction ──

    def _extract_parties_zone(self, extraction: ExtractionResult) -> list[Party]:
        """
        Use coordinate-aware zone extraction to find Shipper and Consignee.
        Standard LTL BOL layout:
          - Ship From (Shipper): Top-left quadrant (~0-50% width, ~10-35% height)
          - Ship To (Consignee): Top-right quadrant (~50-100% width, ~10-35% height)
        """
        parties = []

        if not extraction.word_positions or not extraction.page_dimensions:
            return parties

        # Use only page 1 (addresses are always on the first page)
        words = extraction.word_positions[0] if extraction.word_positions else []
        dims = extraction.page_dimensions[0] if extraction.page_dimensions else None
        if not words or not dims:
            return parties

        pw, ph = dims

        # Zone: Ship From (Shipper) — left side, upper section
        shipper_text = PdfPlumberExtractor.extract_text_from_zone(
            words, pw, ph, x_range=(0.0, 0.5), y_range=(0.08, 0.35)
        )
        if shipper_text and len(shipper_text.strip()) > 10:
            addr = parse_address_block(shipper_text)
            if addr and addr.name:
                parties.append(Party(role="shipper", address=addr))
                logger.info(f"Zone-parsed Shipper: {addr.name}")

        # Zone: Ship To (Consignee) — right side, upper section
        consignee_text = PdfPlumberExtractor.extract_text_from_zone(
            words, pw, ph, x_range=(0.5, 1.0), y_range=(0.08, 0.35)
        )
        if consignee_text and len(consignee_text.strip()) > 10:
            addr = parse_address_block(consignee_text)
            if addr and addr.name:
                parties.append(Party(role="consignee", address=addr))
                logger.info(f"Zone-parsed Consignee: {addr.name}")

        return parties

    # ── Mathematical Verification ──

    def _verify_weight_totals(self, doc: BOLDocument) -> None:
        """
        Cross-check: sum of line item weights should equal the document's total weight.
        If they don't match, add a warning (but don't overwrite — just flag).
        """
        if not doc.line_items or not doc.totals or not doc.totals.total_weight:
            return

        computed_weight = sum(
            item.weight for item in doc.line_items
            if item.weight is not None
        )

        if computed_weight > 0:
            declared_weight = doc.totals.total_weight
            tolerance = max(declared_weight * 0.02, 1.0)  # 2% or 1 lb tolerance

            if abs(computed_weight - declared_weight) > tolerance:
                doc.extraction_warnings.append(
                    f"Weight mismatch: line items sum to {computed_weight} "
                    f"but declared total is {declared_weight}. "
                    f"Difference: {abs(computed_weight - declared_weight):.1f}"
                )
                logger.warning(
                    f"Math verification FAILED: {computed_weight} vs {declared_weight}"
                )
            else:
                logger.info(
                    f"Math verification PASSED: {computed_weight} ≈ {declared_weight}"
                )

    def _extract_parties(self, text: str) -> list[Party]:
        """Extract shipper, consignee, and third-party billing from LTL BOL."""
        parties = []

        # Ship From (Shipper)
        shipper_addr = self._extract_address_block_between(text, 'Ship From', 'Ship To')
        if shipper_addr:
            parties.append(Party(role="shipper", address=shipper_addr))

        # Ship To (Consignee)
        consignee_addr = self._extract_address_block_between(text, 'Ship To', '3rd Party')
        if not consignee_addr:
            consignee_addr = self._extract_address_block_between(text, 'Ship To', 'Destination')
        if consignee_addr:
            parties.append(Party(role="consignee", address=consignee_addr))

        # 3rd Party Billing
        third_party = self._extract_address_block_between(
            text, '3rd Party Freight Charges Bill To', 'Freight Terms'
        )
        if not third_party:
            third_party = self._extract_address_block_between(
                text, '3rd Party', 'Freight Terms'
            )
        if third_party:
            parties.append(Party(role="third_party_billing", address=third_party))

        return parties

    def _extract_line_items(self, extraction: ExtractionResult) -> list[LineItem]:
        """
        Extract line items from tables or text.
        Scans the H.M. column for hazmat indicators per 49 CFR 172.
        """
        items = []

        # Try to find the items table
        for table in extraction.tables:
            if not table or len(table) < 2:
                continue

            # Look for header row with item-related columns
            header = [str(cell).upper().strip() for cell in table[0]]

            # Check if this looks like an item table
            item_indicators = {'QTY', 'QUANTITY', 'TYPE', 'WEIGHT', 'DESCRIPTION', 'ITEM'}
            if not any(ind in ' '.join(header) for ind in item_indicators):
                continue

            # Map column indices — including H.M. column
            col_map = {}
            for i, h in enumerate(header):
                if 'DESCRIPTION' in h or 'ITEM' in h:
                    col_map['description'] = i
                elif h in ('QTY', 'QUANTITY'):
                    col_map['qty'] = i
                elif h == 'TYPE':
                    col_map['type'] = i
                elif 'WEIGHT' in h:
                    col_map['weight'] = i
                elif 'NMFC' in h:
                    col_map['nmfc'] = i
                elif 'CLASS' in h or 'LTL' in h:
                    col_map['ltl_class'] = i
                elif h in ('HM', 'H.M.', 'H.M', 'HAZMAT', 'HAZ'):
                    col_map['hm'] = i

            # Parse data rows
            for row in table[1:]:
                if not row or all(not str(cell).strip() for cell in row):
                    continue
                # Skip "GRAND TOTALS" row
                row_text = ' '.join(str(c) for c in row)
                if 'GRAND TOTAL' in row_text.upper() or 'TOTAL' in row_text.upper():
                    continue

                item = LineItem()
                if 'description' in col_map and col_map['description'] < len(row):
                    item.description = str(row[col_map['description']]).strip() or None
                if 'qty' in col_map and col_map['qty'] < len(row):
                    item.quantity = safe_int(str(row[col_map['qty']]))
                if 'type' in col_map and col_map['type'] < len(row):
                    item.packaging_type = str(row[col_map['type']]).strip() or None
                if 'weight' in col_map and col_map['weight'] < len(row):
                    item.weight = safe_float(str(row[col_map['weight']]))
                if 'nmfc' in col_map and col_map['nmfc'] < len(row):
                    nmfc_val = str(row[col_map['nmfc']]).strip()
                    item.nmfc = nmfc_val if nmfc_val else None
                if 'ltl_class' in col_map and col_map['ltl_class'] < len(row):
                    item.ltl_class = safe_float(str(row[col_map['ltl_class']]))

                # ── Hazmat detection from H.M. column ──
                if 'hm' in col_map and col_map['hm'] < len(row):
                    hm_val = str(row[col_map['hm']]).strip().upper()
                    if hm_val in ('X', 'YES', 'Y', '✓', '✗'):
                        item.hazmat = True
                        # Try to extract hazmat details from description
                        item.hazmat_info = self._extract_hazmat_from_text(
                            item.description or row_text
                        )

                # Only add if we got at least some data
                if item.description or item.quantity or item.weight:
                    items.append(item)

        # Fallback: try to parse from text if no tables found
        if not items:
            items = self._extract_items_from_text(extraction.raw_text)

        return items

    def _extract_hazmat_from_text(self, text: str) -> HazmatInfo:
        """
        Extract hazmat regulatory fields from item text per DOT 49 CFR 172.
        Looks for UN/NA numbers, hazard class, packing group.
        """
        info = HazmatInfo()

        # UN/NA identification number (e.g., UN3480, NA1993)
        un_match = re.search(r'\b(UN\d{4}|NA\d{4})\b', text, re.IGNORECASE)
        if un_match:
            info.un_na_number = un_match.group(1).upper()

        # Hazard class (e.g., "Class 9", "3", "2.1")
        class_match = re.search(
            r'(?:HAZARD\s*)?CLASS\s*[:\s]?\s*(\d(?:\.\d)?)',
            text, re.IGNORECASE
        )
        if class_match:
            info.hazard_class = class_match.group(1)

        # Packing group (I, II, III)
        pg_match = re.search(
            r'PACKING\s+GROUP\s*[:\s]?\s*(I{1,3}|[123])',
            text, re.IGNORECASE
        )
        if pg_match:
            info.packing_group = pg_match.group(1).upper()

        return info

    def _extract_items_from_text(self, text: str) -> list[LineItem]:
        """Fallback: extract item info from raw text using regex."""
        items = []
        # Look for pattern: description, qty, type, weight
        pattern = re.compile(
            r'FREIGHT.*?(\d+)\s+(PLT|CTN|SKD|PCS|CRT)\s+(\d[\d,]*)',
            re.IGNORECASE
        )
        for match in pattern.finditer(text):
            items.append(LineItem(
                description="FREIGHT",
                quantity=safe_int(match.group(1)),
                packaging_type=match.group(2).upper(),
                weight=safe_float(match.group(3)),
            ))
        return items

    def _extract_totals(self, text: str, extraction: ExtractionResult) -> Totals:
        """Extract shipment totals."""
        totals = Totals()

        # Try from tables - look for GRAND TOTALS row
        for table in extraction.tables:
            for row in table:
                row_text = ' '.join(str(c) for c in row).upper()
                if 'GRAND TOTAL' in row_text or 'TOTAL' in row_text:
                    # Try to find numeric values in this row
                    nums = re.findall(r'(\d[\d,]*\.?\d*)', row_text)
                    if len(nums) >= 2:
                        totals.total_pieces = safe_int(nums[0])
                        totals.total_weight = safe_float(nums[1])
                    elif len(nums) == 1:
                        totals.total_weight = safe_float(nums[0])

        # Fallback: regex from text
        if not totals.total_weight:
            match = re.search(r'GRAND\s+TOTALS?:?\s*(\d+)\s+(\d[\d,]*)', text, re.IGNORECASE)
            if match:
                totals.total_pieces = safe_int(match.group(1))
                totals.total_weight = safe_float(match.group(2))

        return totals
