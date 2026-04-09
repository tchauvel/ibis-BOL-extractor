"""
schema.py — Unified BOL Data Model
Strict Pydantic v2 models for logistics extraction.
Includes validation for weights and locale-aware date normalization.
"""
from __future__ import annotations
import re
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Date Normalisation ───────────────────────────────────────────────────────

# Countries that write dates as DD/MM/YYYY (not MM/DD/YYYY).
# Used to resolve the slash-date ambiguity: "04/03/2026" = Apr 3 (US) vs Mar 4 (EU).
_DD_MM_COUNTRIES = {
    # Europe
    "FR", "DE", "NL", "BE", "ES", "IT", "PT", "AT", "CH",
    "PL", "SE", "NO", "DK", "FI", "CZ", "HU", "RO", "BG",
    "HR", "GR", "SK", "SI", "LT", "LV", "EE", "LU", "MT",
    # UK & Ireland
    "GB", "IE",
    # Oceania
    "AU", "NZ",
    # Latin America (most use DD/MM)
    "BR", "AR", "CL", "CO", "MX", "PE",
    # Africa (Francophone)
    "MA", "TN", "DZ", "SN", "CI",
}

# Unambiguous formats (named months, ISO, EDI) — order doesn't matter for these.
_FORMATS_UNAMBIGUOUS = [
    "%Y-%m-%d",     # ISO 8601            2026-03-30
    "%Y%m%d",       # EDI/ANSI X12        20260330
    "%d-%b-%Y",     # 30-MAR-2026         maritime/ocean standard
    "%d %b %Y",     # 30 MAR 2026
    "%d-%b-%y",     # 30-MAR-26           maritime short year
    "%b %d, %Y",    # Mar 30, 2026
    "%b %d %Y",     # Mar 30 2026
    "%B %d, %Y",    # March 30, 2026
    "%B %d %Y",     # March 30 2026
]

# Ambiguous slash/dot formats — order is locale-dependent.
_FORMATS_SLASH_US = [
    "%m/%d/%Y",     # 03/30/2026  US
    "%m/%d/%y",     # 03/30/26    US short
    "%d/%m/%Y",     # 30/03/2026  EU
    "%d/%m/%y",     # 30/03/26    EU short
    "%d.%m.%Y",     # 30.03.2026  European dot
    "%d.%m.%y",     # 30.03.26    European dot short
    "%d-%m-%Y",     # 30-03-2026
]

_FORMATS_SLASH_EU = [
    "%d/%m/%Y",     # 30/03/2026  EU  ← promoted
    "%d/%m/%y",     # 30/03/26    EU short
    "%m/%d/%Y",     # 03/30/2026  US  (fallback — only valid when day > 12)
    "%m/%d/%y",     # 03/30/26    US short
    "%d.%m.%Y",     # 30.03.2026  European dot
    "%d.%m.%y",     # 30.03.26
    "%d-%m-%Y",     # 30-03-2026
]

# Captures the date prefix from datetime strings like "30 MAR 2026 14:00" or "2026-03-30T14:00"
_DATETIME_PREFIX = re.compile(
    r"^(\d{1,2}[-/ ]\w+[-/ ]\d{2,4}|\d{4}[-/]\d{2}[-/]\d{2}|\d{8})"
)


def _normalize_date(v: Optional[str], eu_priority: bool = False) -> Optional[str]:
    """
    Coerce any recognized date string to YYYY-MM-DD.

    eu_priority=True promotes DD/MM/YYYY above MM/DD/YYYY for documents
    originating from countries in _DD_MM_COUNTRIES.
    """
    if v is None:
        return None
    s = v.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s  # already ISO — fast path

    # Strip time component if present
    m = _DATETIME_PREFIX.match(s)
    date_str = (m.group(1) if m else s).strip()

    slash_formats = _FORMATS_SLASH_EU if eu_priority else _FORMATS_SLASH_US
    for fmt in _FORMATS_UNAMBIGUOUS + slash_formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return v  # unrecognized — preserve original rather than lose data


# ─── Models ───────────────────────────────────────────────────────────────────

class Address(BaseModel):
    address_line: str = Field(..., description="Street address (including lines 1 & 2)")
    city: str
    state: str
    zip_code: str
    country_code: Optional[str] = Field(
        None,
        description="ISO 3166-1 alpha-2 country code (e.g. 'US', 'FR', 'DE'). "
                    "Infer from the address or document header."
    )
    phone: Optional[str] = None


class Entity(BaseModel):
    name: str = Field(..., description="Full legal name of the entity")
    address: Address


class DocumentReference(BaseModel):
    reference_label: str = Field(..., description="e.g., 'Airway Bill', 'Shipper Reference', 'Control'")
    reference_value: str


class LogisticsDates(BaseModel):
    document_date: Optional[str] = Field(None, description="The generic date printed at the top of the form")
    dispatch_or_ship_date: Optional[str] = Field(None, description="Look specifically for 'Dispatch Date' or 'Ship Date'")
    delivery_date: Optional[str] = Field(None, description="Look for 'Delivery Date' or 'Est. Delivery'")
    appointment_time: Optional[str] = Field(None, description="Look for 'Appointment Time' in yard management sections")
    arrival_time: Optional[str] = Field(None, description="Look for 'Arrival Time'")
    leaving_time: Optional[str] = Field(None, description="Look for 'Leaving Time'")

    @field_validator("document_date", "dispatch_or_ship_date", "delivery_date", mode="before")
    @classmethod
    def normalize_dates(cls, v):
        # Fallback normalizer (no locale context here — locale-aware pass
        # happens in UnifiedBOL.apply_locale_dates before this runs).
        return _normalize_date(v)


class LineItem(BaseModel):
    handling_unit_qty: int
    handling_unit_type: str = Field(..., description="e.g., PLT, SKD")
    package_qty: int
    package_type: str = Field(..., description="e.g., Cartons, Boxes")
    weight_lbs: float
    item_description: str
    article_or_item_number: Optional[str] = Field(None, description="Look for 'Article nr', 'Item code', 'Item#', or 'UPC Number'")
    best_before_or_expiration_date: Optional[str] = Field(None, description="Look for 'Best before', 'BDD', or 'Expiration Date'")
    frozen_date: Optional[str] = Field(None, description="Look specifically for 'Frozen date' on meat/seafood products")
    batch_lot_number_or_supplier_ref: Optional[str] = Field(None, description="Look for 'BatchLot', 'Lot#', or 'Supplier ref.'")
    nmfc_code: Optional[str] = None
    freight_class: Optional[float] = None
    is_hazardous: bool = False
    un_number: Optional[str] = None

    @field_validator("weight_lbs", "freight_class", mode="before")
    @classmethod
    def parse_item_numeric(cls, v):
        if isinstance(v, str):
            cleaned = "".join(c for c in v if c.isdigit() or c in ".-")
            try:
                return float(cleaned)
            except (ValueError, TypeError):
                return 0.0
        return v


class UnifiedBOL(BaseModel):
    """
    Unified Pydantic V2 model for logistics extraction.
    Strictly follows the technical specification for field naming and types.
    """
    # Document Metadata & Operational Numbers
    bol_number: str
    pro_number: Optional[str] = None
    waybill_number: Optional[str] = Field(None, description="Look for 'Waybill', 'Waybill No.', 'Airway Bill', 'AWB', or 'Air Waybill Number'")
    order_number: Optional[str] = Field(None, description="Look for 'Order#', proprietary order patterns, or supplier-specific references")
    web_id: Optional[str] = Field(None, description="Look for 'Web ID#'")
    master_bol_indicator: bool = False

    # Document locale — drives unambiguous date parsing for slash-format dates
    origin_country_code: Optional[str] = Field(
        None,
        description="ISO 3166-1 alpha-2 code for the country where this document originates "
                    "(typically the shipper's country). E.g. 'US', 'FR', 'DE', 'NL'. "
                    "Infer from the shipper address or document header."
    )

    # Dates & Times
    logistics_dates: Optional[LogisticsDates] = None

    # Entities
    shipper: Entity
    consignee: Entity
    third_party_bill_to: Optional[Entity] = None

    # Carrier & Routing
    carrier_name: str
    scac_code: Optional[str] = None

    # Ocean/Container Details
    vessel_name: Optional[str] = None
    voyage_number: Optional[str] = None
    container_number: Optional[str] = None
    seal_number: Optional[str] = None

    # Cold Chain Details
    temperature_setpoint_fahrenheit: Optional[float] = None
    temperature_recorder_number: Optional[str] = None

    # Inventory Line Items
    line_items: List[LineItem] = Field(default_factory=list)

    # Proprietary References
    other_references: List[DocumentReference] = Field(default_factory=list)

    # Totals & Compliance
    grand_total_weight_lbs: float
    grand_total_handling_units: int
    shipper_signature_present: bool = False
    carrier_signature_present: bool = False

    @model_validator(mode="before")
    @classmethod
    def apply_locale_dates(cls, data: Any) -> Any:
        """
        Runs before field validators. Normalizes all date fields in logistics_dates
        using the document's locale so slash-format ambiguity (MM/DD vs DD/MM) is
        resolved correctly before LogisticsDates.normalize_dates sees the value.
        """
        if not isinstance(data, dict):
            return data

        # Resolve origin country: explicit field wins, then fall back to shipper address
        country = (data.get("origin_country_code") or "").upper()
        if not country:
            shipper = data.get("shipper")
            if isinstance(shipper, dict):
                addr = shipper.get("address")
                if isinstance(addr, dict):
                    country = (addr.get("country_code") or "").upper()

        eu_priority = country in _DD_MM_COUNTRIES

        ld = data.get("logistics_dates")
        if isinstance(ld, dict):
            for field in ("document_date", "dispatch_or_ship_date", "delivery_date"):
                if ld.get(field):
                    ld[field] = _normalize_date(ld[field], eu_priority=eu_priority)

        return data

    @field_validator("temperature_setpoint_fahrenheit", "grand_total_weight_lbs", mode="before")
    @classmethod
    def parse_numeric(cls, v):
        if isinstance(v, str):
            cleaned = "".join(c for c in v if c.isdigit() or c in ".-")
            try:
                return float(cleaned)
            except (ValueError, TypeError):
                return 0.0
        return v


# ─── Cartage Advice Models ────────────────────────────────────────────────────

class RoutingLeg(BaseModel):
    mode: str = Field(..., description="Transport mode: SEA, AIR, RAI, TRK")
    vessel_name: Optional[str] = None
    voyage_number: Optional[str] = None
    carrier: Optional[str] = None
    load_port: Optional[str] = Field(None, description="UN/LOCODE of loading port, e.g. CNNBG")
    discharge_port: Optional[str] = Field(None, description="UN/LOCODE of discharge port, e.g. USLGB")
    etd: Optional[str] = Field(None, description="Estimated Time of Departure (YYYY-MM-DD)")
    eta: Optional[str] = Field(None, description="Estimated Time of Arrival (YYYY-MM-DD)")

    @field_validator("etd", "eta", mode="before")
    @classmethod
    def normalize_leg_dates(cls, v):
        return _normalize_date(v)


class CartageAdvice(BaseModel):
    """Sea Freight FCL Arrival Cartage Advice — e.g. Rohlig format."""
    shipment_number: str
    consol_number: str
    container_number: str
    container_type: Optional[str] = Field(None, description="e.g. 40HC FCL")
    seal_number: Optional[str] = None
    gross_weight_kg: Optional[float] = None
    packages: Optional[int] = None
    volume_m3: Optional[float] = None
    ocean_bol_number: Optional[str] = None
    house_bol_number: Optional[str] = None
    carrier_booking_ref: Optional[str] = None
    document_date: Optional[str] = None
    available_date: Optional[str] = None
    storage_starts_date: Optional[str] = None
    shipper: Optional[Entity] = None
    consignee: Optional[Entity] = None
    routing_legs: List[RoutingLeg] = Field(default_factory=list)
    goods_description: List[str] = Field(default_factory=list)
    handling_instructions: Optional[str] = None

    @field_validator("document_date", "available_date", "storage_starts_date", mode="before")
    @classmethod
    def normalize_ca_dates(cls, v):
        return _normalize_date(v)

    @field_validator("gross_weight_kg", "volume_m3", mode="before")
    @classmethod
    def parse_ca_numeric(cls, v):
        if isinstance(v, str):
            cleaned = "".join(c for c in v if c.isdigit() or c in ".-")
            try:
                return float(cleaned)
            except (ValueError, TypeError):
                return None
        return v


# ─── Fallback & Envelope Models ──────────────────────────────────────────────

class GenericDocument(BaseModel):
    """Best-effort extraction for unrecognized document types."""
    fields: dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """Envelope returned by /api/extract for all document types."""
    document_type: str
    data: dict[str, Any]
