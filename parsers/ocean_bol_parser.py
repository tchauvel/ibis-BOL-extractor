"""
parsers/ocean_bol_parser.py — Parser for ocean container / drayage BOLs.

Targets documents like TCLU7950467.pdf:
- Ocean containers, drayage operations
- Form layout with labeled fields
- Inventory table: Container, BOL, PO, Weight, CBM, Cartons
- Vessel/voyage info, SCAC codes, seal numbers
"""

from __future__ import annotations

import re
from typing import Optional

from extractors.base import ExtractionResult
from parsers.base import BaseBOLParser
from schema import (
    BOLDocument, Party, Address, CarrierInfo,
    VesselInfo, ContainerInfo, ShippingDetails,
    LineItem, Totals,
)
from utils import (
    extract_field_after_label,
    parse_address_block,
    normalize_date,
    safe_int,
    safe_float,
)


class OceanBOLParser(BaseBOLParser):
    """Parse ocean container / drayage Bills of Lading."""

    REFERENCE_LABELS = {
        'bol_number': ['BOL', 'B/L', 'B/L NO'],
        'po_number': ['PO', 'PO#', 'PO:'],
        'din_number': ['DIN #', 'DIN#', 'DIN NO'],
        'seal_number': ['Seal Number', 'Seal#', 'Seal No'],
        'container_number': ['Container', 'Container#', 'Container No'],
    }

    def parse(self, extraction: ExtractionResult) -> BOLDocument:
        """Parse ocean BOL from extracted text and tables."""
        text = extraction.raw_text
        doc = BOLDocument(
            document_type="bill_of_lading",
            document_subtype="ocean",
            extraction_method="pdfplumber",
            raw_text=text,
        )

        # ── References ──
        doc.references = self._extract_references(text, self.REFERENCE_LABELS)

        # ── Document Date ──
        # Ocean BOLs often have the date at the top
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', text)
        if date_match:
            doc.document_date = normalize_date(date_match.group(1))

        # ── Vessel Info ──
        vessel_name = extract_field_after_label(text, 'Vessel')
        voyage = extract_field_after_label(text, 'Voyage')
        eta = extract_field_after_label(text, 'ETA')
        port_of_origin = extract_field_after_label(text, 'Port of Origin')

        doc.vessel_info = VesselInfo(
            vessel_name=vessel_name,
            voyage_number=voyage,
            eta=normalize_date(eta) if eta else None,
            port_of_origin=port_of_origin,
        )

        # ── Container Info ──
        container_num = extract_field_after_label(text, 'Container')
        container_size = extract_field_after_label(text, 'Container Size')
        seal_num = extract_field_after_label(text, 'Seal Number')

        doc.container_info = ContainerInfo(
            container_number=container_num,
            container_size=container_size,
            seal_number=seal_num,
        )

        # ── Carrier Info ──
        dray_scac = extract_field_after_label(text, 'Dray SCAC')
        ssl_scac = extract_field_after_label(text, 'SSL SCAC')

        doc.carrier = CarrierInfo(
            name=vessel_name,
            scac=ssl_scac,
        )
        if dray_scac:
            doc.references['dray_scac'] = dray_scac
        if ssl_scac:
            doc.references['ssl_scac'] = ssl_scac

        # ── Shipping Details ──
        special_1 = extract_field_after_label(text, 'Special Instructions 1')
        special_2 = extract_field_after_label(text, 'Special Instructions 2')
        special = ', '.join(filter(None, [special_1, special_2])) or None

        pickup_num = extract_field_after_label(text, 'Pickup #')
        din_num = extract_field_after_label(text, 'DIN #')

        doc.shipping_details = ShippingDetails(
            special_instructions=special,
        )
        if pickup_num:
            doc.references['pickup_number'] = pickup_num
        if din_num:
            doc.references['din_number'] = din_num

        # ── Parties ──
        doc.parties = self._extract_parties(text)

        # ── Line Items (from tables) ──
        doc.line_items = self._extract_line_items(extraction)

        # ── Totals ──
        doc.totals = self._extract_totals(text, extraction)

        # ── Confidence ──
        doc.compute_confidence()

        return doc

    def _extract_parties(self, text: str) -> list[Party]:
        """Extract shipment parties from ocean BOL."""
        parties = []

        # Ship From
        shipper_addr = self._extract_ocean_address(text, 'SHIP FROM', 'SHIP TO')
        if shipper_addr:
            parties.append(Party(role="shipper", address=shipper_addr))

        # Ship To
        consignee_addr = self._extract_ocean_address(text, 'SHIP TO', 'Special Instructions')
        if not consignee_addr:
            consignee_addr = self._extract_ocean_address(text, 'SHIP TO', 'Container')
        if consignee_addr:
            parties.append(Party(role="consignee", address=consignee_addr))

        return parties

    def _extract_ocean_address(self, text: str, start: str, end: str) -> Optional[Address]:
        """
        Extract address from ocean BOL form layout.
        These use labeled fields: Name:, Address:, City/State/Zip:
        """
        pattern = re.compile(
            rf'{re.escape(start)}(.*?){re.escape(end)}',
            re.DOTALL | re.IGNORECASE
        )
        match = pattern.search(text)
        if not match:
            return None

        block = match.group(1)
        addr = Address()

        # Extract labeled fields
        name = extract_field_after_label(block, 'Name')
        address_line = extract_field_after_label(block, 'Address')
        city_state_zip = extract_field_after_label(block, 'City/State/Zip')

        if name:
            addr.name = name
        if address_line:
            addr.address_line_1 = address_line

        # Parse City/State/Zip line
        if city_state_zip:
            # Pattern: City  ST  ZIP
            csz_match = re.match(
                r'(.+?)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)',
                city_state_zip.strip()
            )
            if csz_match:
                addr.city = csz_match.group(1).strip()
                addr.state = csz_match.group(2)
                addr.zip_code = csz_match.group(3)

        return addr if (addr.name or addr.address_line_1) else None

    def _extract_line_items(self, extraction: ExtractionResult) -> list[LineItem]:
        """Extract line items from inventory detail table."""
        items = []

        for table in extraction.tables:
            if not table or len(table) < 2:
                continue

            header = [str(cell).upper().strip() for cell in table[0]]

            # Look for container inventory table
            inventory_indicators = {'CONTAINER', 'BOL', 'PO', 'WEIGHT', 'CBM', 'CARTONS'}
            if not any(ind in ' '.join(header) for ind in inventory_indicators):
                continue

            # Map columns
            col_map = {}
            for i, h in enumerate(header):
                if 'CONTAINER' in h:
                    col_map['container'] = i
                elif h == 'BOL' or 'B/L' in h:
                    col_map['bol'] = i
                elif h == 'PO' or 'P.O' in h:
                    col_map['po'] = i
                elif 'WEIGHT' in h:
                    col_map['weight'] = i
                elif 'CBM' in h:
                    col_map['cbm'] = i
                elif 'CARTON' in h:
                    col_map['cartons'] = i
                elif 'ITEM' in h:
                    col_map['item'] = i

            # Parse data rows
            for row in table[1:]:
                if not row or all(not str(cell).strip() for cell in row):
                    continue

                item = LineItem()
                if 'container' in col_map and col_map['container'] < len(row):
                    desc = str(row[col_map['container']]).strip()
                    if desc:
                        item.description = f"Container: {desc}"
                if 'weight' in col_map and col_map['weight'] < len(row):
                    item.weight = safe_float(str(row[col_map['weight']]))
                if 'cbm' in col_map and col_map['cbm'] < len(row):
                    item.volume_cbm = safe_float(str(row[col_map['cbm']]))
                if 'cartons' in col_map and col_map['cartons'] < len(row):
                    item.carton_count = safe_int(str(row[col_map['cartons']]))

                # Capture BOL/PO as description if no container
                if not item.description:
                    parts = []
                    if 'bol' in col_map and col_map['bol'] < len(row):
                        v = str(row[col_map['bol']]).strip()
                        if v:
                            parts.append(f"BOL: {v}")
                    if 'po' in col_map and col_map['po'] < len(row):
                        v = str(row[col_map['po']]).strip()
                        if v:
                            parts.append(f"PO: {v}")
                    if parts:
                        item.description = ', '.join(parts)

                if item.description or item.weight or item.carton_count:
                    items.append(item)

        return items

    def _extract_totals(self, text: str, extraction: ExtractionResult) -> Totals:
        """Extract shipment totals."""
        totals = Totals()

        # Look for Total row in text
        total_match = re.search(
            r'Total:?\s*(\d[\d,]*\.?\d*)\s+(\d[\d,]*\.?\d*)\s+(\d[\d,]*)',
            text, re.IGNORECASE
        )
        if total_match:
            totals.total_weight = safe_float(total_match.group(1))
            totals.total_volume_cbm = safe_float(total_match.group(2))
            totals.total_cartons = safe_int(total_match.group(3))

        return totals
