"""
tests/test_api_extract.py — Integration tests for the /extract endpoint.
Gemini calls are mocked; no real network requests are made.
"""
from __future__ import annotations

from unittest.mock import patch

from schema import CartageAdvice, ExtractionResult, GenericDocument, UnifiedBOL


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_bol() -> UnifiedBOL:
    address = dict(address_line="1 Dock St", city="Miami", state="FL", zip_code="33101")
    entity = dict(name="Shipper Inc", address=address)
    return UnifiedBOL(
        bol_number="TEST-001",
        shipper=entity,
        consignee=entity,
        carrier_name="Test Carrier",
        grand_total_weight_lbs=200.0,
        grand_total_handling_units=2,
    )


def _make_cartage_advice() -> CartageAdvice:
    return CartageAdvice(
        shipment_number="S03273285",
        consol_number="C02123952",
        container_number="HASU5014997",
    )


def _bol_extraction_result() -> ExtractionResult:
    return ExtractionResult(document_type="bol", data=_make_bol().model_dump())


def _cartage_extraction_result() -> ExtractionResult:
    return ExtractionResult(document_type="cartage_advice", data=_make_cartage_advice().model_dump())


def _unknown_extraction_result() -> ExtractionResult:
    return ExtractionResult(document_type="unknown", data={"fields": {"key": "value"}})


# ─── Input validation ─────────────────────────────────────────────────────────

def test_extract_no_file_returns_422(client):
    resp = client.post("/extract")
    assert resp.status_code == 422


def test_extract_unsupported_extension_returns_400(client):
    resp = client.post(
        "/extract",
        files={"file": ("doc.txt", b"data", "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


def test_extract_oversized_file_returns_413(client):
    from api import settings
    huge = b"x" * (settings.max_file_bytes + 1)
    resp = client.post(
        "/extract",
        files={"file": ("big.pdf", huge, "application/pdf")},
    )
    assert resp.status_code == 413


# ─── Success paths ────────────────────────────────────────────────────────────

@patch("api.preprocess_pdf_to_images", return_value=["fake_b64"])
@patch("api.extract_document", return_value=_bol_extraction_result())
def test_extract_pdf_bol_success(mock_extract, mock_preprocess, client):
    resp = client.post(
        "/extract",
        files={"file": ("bol.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "bol"
    assert body["data"]["bol_number"] == "TEST-001"
    assert "_pipeline" in body
    assert body["_pipeline"]["pages_processed"] == 1
    mock_preprocess.assert_called_once()


@patch("api.preprocess_pdf_to_images", return_value=["fake_b64"])
@patch("api.extract_document", return_value=_cartage_extraction_result())
def test_extract_pdf_cartage_advice_success(mock_extract, mock_preprocess, client):
    resp = client.post(
        "/extract",
        files={"file": ("cartage.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "cartage_advice"
    assert body["data"]["shipment_number"] == "S03273285"


@patch("api.preprocess_pdf_to_images", return_value=["fake_b64"])
@patch("api.extract_document", return_value=_unknown_extraction_result())
def test_extract_unknown_document_type_returns_200(mock_extract, mock_preprocess, client):
    resp = client.post(
        "/extract",
        files={"file": ("mystery.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "unknown"
    assert "fields" in body["data"]


@patch("api.extract_document", return_value=_bol_extraction_result())
def test_extract_jpeg_success(mock_extract, client):
    resp = client.post(
        "/extract",
        files={"file": ("photo.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    assert resp.status_code == 200
    assert resp.json()["document_type"] == "bol"
    mime_types = mock_extract.call_args[0][1]
    assert mime_types == ["image/jpeg"]


# ─── Error handling ───────────────────────────────────────────────────────────

@patch("api.preprocess_pdf_to_images", return_value=["b64"])
@patch("api.extract_document", side_effect=RuntimeError("Gemini exploded"))
def test_extract_pipeline_error_returns_500(_mock_pre, _mock_ext, client):
    resp = client.post(
        "/extract",
        files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 500
    assert "Gemini exploded" not in resp.json()["detail"]
    assert "x-request-id" in resp.headers


# ─── Pipeline metadata ────────────────────────────────────────────────────────

@patch("api.preprocess_pdf_to_images", return_value=["p1", "p2"])
@patch("api.extract_document", return_value=_bol_extraction_result())
def test_extract_page_count_in_pipeline(_mock_ext, _mock_pre, client):
    resp = client.post(
        "/extract",
        files={"file": ("bol.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["_pipeline"]["pages_processed"] == 2


@patch("api.extract_document", return_value=_bol_extraction_result())
def test_extract_pipeline_latency_non_negative(_mock_ext, client):
    resp = client.post(
        "/extract",
        files={"file": ("scan.jpg", b"fake", "image/jpeg")},
    )
    assert resp.status_code == 200
    latency = resp.json()["_pipeline"]["processing_time_ms"]
    assert isinstance(latency, int) and latency >= 0
