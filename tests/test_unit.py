"""
tests/test_unit.py — Unit tests for schema models, extraction helpers, and MCP path validation.
No network calls or external services required.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from extraction import resolve_schema_refs
from mcp_server import _validate_file_path
from schema import LineItem, UnifiedBOL


# ─── resolve_schema_refs ──────────────────────────────────────────────────────

def _has_key(obj, key) -> bool:
    if isinstance(obj, dict):
        return key in obj or any(_has_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(i, key) for i in obj)
    return False


def test_resolve_schema_refs_flattens_refs():
    resolved = resolve_schema_refs(UnifiedBOL.model_json_schema())
    assert not _has_key(resolved, "$ref")
    assert not _has_key(resolved, "$defs")
    assert not _has_key(resolved, "anyOf")


def test_resolve_schema_refs_strips_metadata():
    resolved = resolve_schema_refs(UnifiedBOL.model_json_schema())
    for banned in ("title", "description", "default"):
        assert not _has_key(resolved, banned), f"Resolved schema still contains '{banned}'"


def test_resolve_schema_refs_is_idempotent():
    raw = UnifiedBOL.model_json_schema()
    assert resolve_schema_refs(resolve_schema_refs(raw)) == resolve_schema_refs(raw)


# ─── LineItem validators ──────────────────────────────────────────────────────

def _item(**kw) -> LineItem:
    return LineItem(**{
        "handling_unit_qty": 1, "handling_unit_type": "PLT",
        "package_qty": 10, "package_type": "Cartons",
        "weight_lbs": 100.0, "item_description": "Frozen salmon",
        **kw,
    })


def test_line_item_string_weight_coercion():
    assert _item(weight_lbs="250.5 lbs").weight_lbs == 250.5


def test_line_item_invalid_weight_defaults_to_zero():
    assert _item(weight_lbs="N/A").weight_lbs == 0.0


def test_line_item_none_freight_class_stays_none():
    assert _item(freight_class=None).freight_class is None


def test_line_item_string_freight_class_coercion():
    assert _item(freight_class="70.0").freight_class == 70.0


# ─── UnifiedBOL validators ────────────────────────────────────────────────────

def _bol(**kw) -> UnifiedBOL:
    addr = dict(address_line="123 Main St", city="Boston", state="MA", zip_code="02101")
    entity = dict(name="Acme Corp", address=addr)
    return UnifiedBOL(**{
        "bol_number": "BOL-001", "shipper": entity, "consignee": entity,
        "carrier_name": "FedEx Freight", "grand_total_weight_lbs": 500.0,
        "grand_total_handling_units": 5,
        **kw,
    })


def test_bol_minimal_valid():
    bol = _bol()
    assert bol.bol_number == "BOL-001"
    assert bol.grand_total_weight_lbs == 500.0


def test_bol_string_weight_coercion():
    assert isinstance(_bol(grand_total_weight_lbs="1,500 lbs").grand_total_weight_lbs, float)


def test_bol_invalid_weight_defaults_to_zero():
    assert _bol(grand_total_weight_lbs="unknown").grand_total_weight_lbs == 0.0


def test_bol_string_temperature_coercion():
    assert _bol(temperature_setpoint_fahrenheit="-10.5F").temperature_setpoint_fahrenheit == -10.5


def test_bol_optional_fields_default_none():
    bol = _bol()
    assert bol.pro_number is None
    assert bol.container_number is None


def test_bol_line_items_default_empty():
    assert _bol().line_items == []


def test_bol_missing_required_field_raises():
    with pytest.raises(ValidationError):
        _bol(bol_number=None)


# ─── MCP path validation ──────────────────────────────────────────────────────

def test_validate_existing_file(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"data")
    assert _validate_file_path(str(f)) == f.resolve()


def test_validate_nonexistent_file_raises():
    with pytest.raises(ValueError, match="not found"):
        _validate_file_path("/nonexistent/path/file.pdf")


def test_validate_directory_raises(tmp_path):
    with pytest.raises(ValueError, match="not a regular file"):
        _validate_file_path(str(tmp_path))


def test_validate_symlink_to_file_allowed(tmp_path):
    target = tmp_path / "target.pdf"
    target.write_bytes(b"data")
    link = tmp_path / "link.pdf"
    link.symlink_to(target)
    assert _validate_file_path(str(link)) == target.resolve()


def test_validate_relative_path(tmp_path, monkeypatch):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"data")
    monkeypatch.chdir(tmp_path)
    assert _validate_file_path("doc.pdf").is_file()


# ─── New schema imports ────────────────────────────────────────────────────────
from schema import CartageAdvice, ExtractionResult, GenericDocument, RoutingLeg


# ─── RoutingLeg ────────────────────────────────────────────────────────────────

def test_routing_leg_minimal():
    leg = RoutingLeg(mode="SEA")
    assert leg.mode == "SEA"
    assert leg.vessel_name is None
    assert leg.etd is None


def test_routing_leg_full():
    leg = RoutingLeg(
        mode="SEA",
        vessel_name="CAP SAN VINCENT",
        voyage_number="043N",
        carrier="MAERSK LINE",
        load_port="CNNBG",
        discharge_port="KRPUS",
        etd="31-Oct-20",
        eta="02-Nov-20",
    )
    assert leg.etd == "2020-10-31"
    assert leg.eta == "2020-11-02"


# ─── CartageAdvice ─────────────────────────────────────────────────────────────

def test_cartage_advice_minimal():
    ca = CartageAdvice(
        shipment_number="S03273285",
        consol_number="C02123952",
        container_number="HASU5014997",
    )
    assert ca.shipment_number == "S03273285"
    assert ca.routing_legs == []
    assert ca.goods_description == []


def test_cartage_advice_date_normalization():
    ca = CartageAdvice(
        shipment_number="S1",
        consol_number="C1",
        container_number="X1",
        document_date="23-Jan-21",
        available_date="23-Jan-21",
        storage_starts_date="26-Jan-21",
    )
    assert ca.document_date == "2021-01-23"
    assert ca.available_date == "2021-01-23"
    assert ca.storage_starts_date == "2021-01-26"


def test_cartage_advice_routing_legs():
    ca = CartageAdvice(
        shipment_number="S1",
        consol_number="C1",
        container_number="X1",
        routing_legs=[
            {"mode": "SEA", "vessel_name": "GERNER MAERSK", "voyage_number": "44N"},
        ],
    )
    assert len(ca.routing_legs) == 1
    assert ca.routing_legs[0].vessel_name == "GERNER MAERSK"


# ─── GenericDocument ──────────────────────────────────────────────────────────

def test_generic_document_stores_arbitrary_fields():
    doc = GenericDocument(fields={"invoice_number": "INV-001", "amount": 1500.0})
    assert doc.fields["invoice_number"] == "INV-001"
    assert doc.fields["amount"] == 1500.0


def test_generic_document_empty_fields():
    doc = GenericDocument(fields={})
    assert doc.fields == {}


# ─── ExtractionResult ─────────────────────────────────────────────────────────

def test_extraction_result_bol_type():
    result = ExtractionResult(document_type="bol", data={"bol_number": "B-001"})
    assert result.document_type == "bol"
    assert result.data["bol_number"] == "B-001"


def test_extraction_result_cartage_type():
    result = ExtractionResult(
        document_type="cartage_advice",
        data={"shipment_number": "S03273285"},
    )
    assert result.document_type == "cartage_advice"


def test_extraction_result_unknown_type():
    result = ExtractionResult(document_type="unknown", data={"foo": "bar"})
    assert result.document_type == "unknown"

# ─── Registry ─────────────────────────────────────────────────────────────────
from lib.registry import CLASSIFICATION_PROMPT, REGISTRY, get_registry_entry


def test_registry_contains_all_known_types():
    for t in ("bol", "cartage_advice", "unknown"):
        assert t in REGISTRY, f"REGISTRY missing '{t}'"


def test_registry_values_are_schema_prompt_tuples():
    from pydantic import BaseModel
    for doc_type, (schema_cls, prompt) in REGISTRY.items():
        assert issubclass(schema_cls, BaseModel), f"{doc_type}: schema must be a BaseModel subclass"
        assert isinstance(prompt, str) and len(prompt) > 50, f"{doc_type}: prompt too short"


def test_get_registry_entry_returns_bol():
    schema_cls, prompt = get_registry_entry("bol")
    assert schema_cls is UnifiedBOL


def test_get_registry_entry_returns_cartage_advice():
    schema_cls, prompt = get_registry_entry("cartage_advice")
    assert schema_cls is CartageAdvice


def test_get_registry_entry_unknown_type_falls_back_to_generic():
    schema_cls, prompt = get_registry_entry("invoice")
    assert schema_cls is GenericDocument


def test_get_registry_entry_unknown_string_falls_back():
    schema_cls, _ = get_registry_entry("completely_unknown_type_xyz")
    assert schema_cls is GenericDocument


def test_classification_prompt_lists_known_types():
    for t in ("bol", "cartage_advice", "unknown"):
        assert t in CLASSIFICATION_PROMPT, f"CLASSIFICATION_PROMPT missing '{t}'"
