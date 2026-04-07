"""
test_process_document.py — Integration tests for the full extraction pipeline.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from process_document import process_document


SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


class TestDENDocument:
    """Test extraction of DEN5755177.pdf (LTL BOL)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = process_document(os.path.join(SAMPLES_DIR, "DEN5755177.pdf"))

    def test_document_type(self):
        assert self.result["document_type"] == "bill_of_lading"
        assert self.result["document_subtype"] == "ltl"

    def test_bol_number(self):
        assert self.result["references"]["bol_number"] == "DEN5755177"

    def test_pro_number(self):
        assert self.result["references"]["pro_number"] == "4909362636"

    def test_po_number(self):
        assert self.result["references"]["po_number"] == "5840607392"

    def test_carrier(self):
        assert "FEDEX FREIGHT" in self.result["carrier"]["name"].upper()
        assert self.result["carrier"]["scac"] == "FXFE"

    def test_has_parties(self):
        roles = [p["role"] for p in self.result["parties"]]
        assert "shipper" in roles
        assert "consignee" in roles

    def test_consignee_address(self):
        consignee = next(p for p in self.result["parties"] if p["role"] == "consignee")
        assert consignee["address"]["city"] == "SALT LAKE CITY"
        assert consignee["address"]["state"] == "UT"

    def test_line_items(self):
        assert len(self.result["line_items"]) > 0
        item = self.result["line_items"][0]
        assert item["weight"] == 778.0
        assert item["quantity"] == 2

    def test_totals(self):
        assert self.result["totals"]["total_weight"] == 778.0
        assert self.result["totals"]["total_pieces"] == 2

    def test_confidence(self):
        assert self.result["extraction_confidence"] >= 0.5

    def test_has_raw_text(self):
        assert len(self.result["raw_text"]) > 100


class TestTCLUDocument:
    """Test extraction of TCLU7950467.pdf (Ocean BOL)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.result = process_document(os.path.join(SAMPLES_DIR, "TCLU7950467.pdf"))

    def test_document_type(self):
        assert self.result["document_type"] == "bill_of_lading"
        assert self.result["document_subtype"] == "ocean"

    def test_container_number(self):
        assert self.result["container_info"]["container_number"] == "TCLU7950467"

    def test_vessel_info(self):
        assert self.result["vessel_info"]["vessel_name"] == "MSC OLIVER"
        assert self.result["vessel_info"]["voyage_number"] == "0036"

    def test_seal_number(self):
        assert self.result["container_info"]["seal_number"] == "ML-CN5744476"

    def test_has_parties(self):
        roles = [p["role"] for p in self.result["parties"]]
        assert "shipper" in roles
        assert "consignee" in roles

    def test_totals(self):
        assert self.result["totals"]["total_volume_cbm"] == 60.0
        assert self.result["totals"]["total_cartons"] == 1350

    def test_document_date(self):
        assert "2020" in self.result["document_date"]

    def test_confidence(self):
        assert self.result["extraction_confidence"] >= 0.5


class TestEdgeCases:
    """Test error handling and edge cases."""

    def test_nonexistent_file(self):
        result = process_document("nonexistent.pdf")
        assert result["document_type"] == "error"
        assert len(result["extraction_warnings"]) > 0

    def test_non_pdf_file(self):
        result = process_document(__file__)  # This .py file
        assert result["document_type"] == "error"

    def test_result_is_json_serializable(self):
        result = process_document(os.path.join(SAMPLES_DIR, "DEN5755177.pdf"))
        # Should not raise
        json_str = json.dumps(result)
        assert len(json_str) > 100
