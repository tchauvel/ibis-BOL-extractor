"""
tests/test_api.py — FastAPI endpoint integration tests.
Gemini API calls are mocked so no real network requests are made.
"""
from __future__ import annotations

from unittest.mock import patch

from schema import UnifiedBOL


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_bol(**overrides) -> UnifiedBOL:
    address = dict(address_line="1 Dock St", city="Miami", state="FL", zip_code="33101")
    entity = dict(name="Shipper Inc", address=address)
    base = dict(
        bol_number="TEST-001",
        shipper=entity,
        consignee=entity,
        carrier_name="Test Carrier",
        grand_total_weight_lbs=200.0,
        grand_total_handling_units=2,
    )
    base.update(overrides)
    return UnifiedBOL(**base)


def _fake_extract(*args, **kwargs) -> UnifiedBOL:
    return _make_bol()


# ─── Health ────────────────────────────────────────────────────────────────────

def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


# ─── Root ─────────────────────────────────────────────────────────────────────

def test_root_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ─── Security headers ─────────────────────────────────────────────────────────

def test_security_headers_present(client):
    resp = client.get("/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert "content-security-policy" in resp.headers
    assert "referrer-policy" in resp.headers


def test_request_id_header_present(client):
    resp = client.get("/health")
    assert "x-request-id" in resp.headers
    # Should be a valid UUID4
    import uuid
    uuid.UUID(resp.headers["x-request-id"], version=4)


# ─── /extract-bol — input validation ──────────────────────────────────────────

def test_extract_no_file_returns_422(client):
    resp = client.post("/extract-bol")
    assert resp.status_code == 422


def test_extract_unsupported_extension_returns_400(client):
    resp = client.post(
        "/extract-bol",
        files={"file": ("doc.txt", b"data", "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


def test_extract_dotless_filename_returns_400(client):
    resp = client.post(
        "/extract-bol",
        files={"file": ("nodotfile", b"data", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_extract_oversized_file_returns_413(client):
    from api import settings
    huge = b"x" * (settings.max_file_bytes + 1)
    resp = client.post(
        "/extract-bol",
        files={"file": ("big.pdf", huge, "application/pdf")},
    )
    assert resp.status_code == 413


# ─── /extract-bol — success paths (Gemini mocked) ────────────────────────────

@patch("api.preprocess_pdf_to_images", return_value=["base64fakeimage=="])
@patch("api.extract_bol_vision", side_effect=_fake_extract)
def test_extract_pdf_success(mock_extract, mock_preprocess, client):
    fake_pdf = b"%PDF-1.4 fake"
    resp = client.post(
        "/extract-bol",
        files={"file": ("bol.pdf", fake_pdf, "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["bol_number"] == "TEST-001"
    assert "_pipeline" in body
    assert body["_pipeline"]["pages_processed"] == 1
    assert "request_id" in body["_pipeline"]
    mock_preprocess.assert_called_once_with(fake_pdf)


@patch("api.extract_bol_vision", side_effect=_fake_extract)
def test_extract_jpeg_success(mock_extract, client):
    resp = client.post(
        "/extract-bol",
        files={"file": ("photo.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    assert resp.status_code == 200
    # Correct MIME type forwarded
    mime_types = mock_extract.call_args[0][1]
    assert mime_types == ["image/jpeg"]


@patch("api.extract_bol_vision", side_effect=_fake_extract)
def test_extract_png_correct_mime(mock_extract, client):
    resp = client.post(
        "/extract-bol",
        files={"file": ("scan.png", b"\x89PNG", "image/png")},
    )
    assert resp.status_code == 200
    assert mock_extract.call_args[0][1] == ["image/png"]


@patch("api.extract_bol_vision", side_effect=_fake_extract)
def test_extract_webp_correct_mime(mock_extract, client):
    resp = client.post(
        "/extract-bol",
        files={"file": ("doc.webp", b"RIFF", "image/webp")},
    )
    assert resp.status_code == 200
    assert mock_extract.call_args[0][1] == ["image/webp"]


# ─── /extract-bol — error handling ───────────────────────────────────────────

@patch("api.extract_bol_vision", side_effect=RuntimeError("Gemini exploded"))
@patch("api.preprocess_pdf_to_images", return_value=["b64"])
def test_pipeline_error_returns_500_without_detail_leak(_mock_pre, _mock_ext, client):
    resp = client.post(
        "/extract-bol",
        files={"file": ("bol.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    # Internal exception message must NOT be exposed to the client.
    assert "Gemini exploded" not in detail
    # Request ID must be present for support correlation.
    assert "request_id" in detail.lower() or "x-request-id" in resp.headers


# ─── Pipeline metadata ────────────────────────────────────────────────────────

@patch("api.preprocess_pdf_to_images", return_value=["p1", "p2"])
@patch("api.extract_bol_vision", side_effect=_fake_extract)
def test_pipeline_page_count_matches_preprocessed_images(_mock_ext, _mock_pre, client):
    resp = client.post(
        "/extract-bol",
        files={"file": ("bol.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["_pipeline"]["pages_processed"] == 2


@patch("api.extract_bol_vision", side_effect=_fake_extract)
def test_pipeline_latency_is_non_negative_int(_mock_ext, client):
    resp = client.post(
        "/extract-bol",
        files={"file": ("scan.jpg", b"fake", "image/jpeg")},
    )
    assert resp.status_code == 200
    latency = resp.json()["_pipeline"]["processing_time_ms"]
    assert isinstance(latency, int) and latency >= 0
