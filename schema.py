"""
schema.py — Pydantic models for the unified BOL document schema.

Design rationale:
- All fields are Optional to handle partial extraction gracefully
- Confidence scoring is baked into the output so consumers know what to trust
- The schema is broad enough to cover domestic LTL, ocean container, and unknown doc types
- `raw_text` is always included for debugging and downstream processing

Classification covers three dimensions (per DOT/FMCSA requirements):
  1. Functional Type: Straight, Order/Negotiable, Master, Through, Ocean
  2. Regulatory Type: General Commodity, Hazmat, Household Goods
  3. Transport Mode: LTL, Truckload (TL)
"""

from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field


# ─── Sub-models ───────────────────────────────────────────────────────────────

class Address(BaseModel):
    """Structured address, parsed from free-text address blocks."""
    name: Optional[str] = Field(None, description="Company or facility name")
    address_line_1: Optional[str] = Field(None, description="Street address")
    address_line_2: Optional[str] = Field(None, description="Suite, unit, etc.")
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = Field(None, description="Country code or name")
    phone: Optional[str] = None
    fax: Optional[str] = None


class Party(BaseModel):
    """A named party in the shipping transaction."""
    role: str = Field(..., description="Role: shipper, consignee, third_party_billing, broker, etc.")
    address: Optional[Address] = None


class CarrierInfo(BaseModel):
    """Carrier / transport provider details."""
    name: Optional[str] = None
    scac: Optional[str] = Field(None, description="Standard Carrier Alpha Code")
    pro_number: Optional[str] = Field(None, description="Progressive/tracking number (LTL)")
    trailer_number: Optional[str] = Field(None, description="Trailer ID (TL/FTL)")


class VesselInfo(BaseModel):
    """Ocean vessel details — only present on ocean/container BOLs."""
    vessel_name: Optional[str] = None
    voyage_number: Optional[str] = None
    port_of_loading: Optional[str] = Field(None, description="Port of Loading / Origin")
    port_of_discharge: Optional[str] = Field(None, description="Port of Discharge / Destination")
    port_of_origin: Optional[str] = None
    port_of_destination: Optional[str] = None
    eta: Optional[str] = None


class ContainerInfo(BaseModel):
    """Container details — only present on ocean/container BOLs."""
    container_number: Optional[str] = None
    container_size: Optional[str] = Field(None, description="e.g., 40HD, 20ST")
    seal_number: Optional[str] = None


class HazmatInfo(BaseModel):
    """
    Hazardous materials data per DOT 49 CFR 172.
    Extracted from H.M. column markers and regulatory fields.
    """
    un_na_number: Optional[str] = Field(None, description="UN/NA ID e.g. UN3480, NA1993")
    proper_shipping_name: Optional[str] = None
    hazard_class: Optional[str] = Field(None, description="DOT hazard class e.g. 9, 3, 2.1")
    packing_group: Optional[str] = Field(None, description="I, II, or III")
    emergency_contact: Optional[str] = Field(None, description="24-hour emergency phone")
    placard_required: Optional[bool] = None


class LineItem(BaseModel):
    """Individual item in the shipment."""
    description: Optional[str] = None
    quantity: Optional[int] = None
    packaging_type: Optional[str] = Field(None, description="e.g., PLT (pallet), CTN (carton)")
    weight: Optional[float] = Field(None, description="Weight in lbs or kg")
    weight_unit: Optional[str] = Field("lbs", description="lbs or kg")
    dimensions: Optional[str] = Field(None, description="L x W x H")
    volume_cbm: Optional[float] = Field(None, description="Volume in cubic meters")
    nmfc: Optional[str] = Field(None, description="National Motor Freight Classification")
    ltl_class: Optional[float] = Field(None, description="LTL freight class (50–500)")
    hazmat: Optional[bool] = Field(False, description="True if H.M. column marked 'X'")
    hazmat_info: Optional[HazmatInfo] = Field(None, description="Hazmat detail (only if hazmat=True)")
    carton_count: Optional[int] = None


class ShippingDetails(BaseModel):
    """Dates, terms, and logistics metadata."""
    pickup_date: Optional[str] = None
    estimated_delivery: Optional[str] = None
    freight_terms: Optional[str] = Field(None, description="e.g., Prepaid, Collect, 3rd Party")
    origin_terminal: Optional[str] = None
    destination_terminal: Optional[str] = None
    special_instructions: Optional[str] = None
    accessorials: Optional[str] = None


class Totals(BaseModel):
    """Shipment totals."""
    total_pieces: Optional[int] = None
    total_weight: Optional[float] = None
    total_weight_unit: Optional[str] = Field("lbs", description="lbs or kg")
    total_volume_cbm: Optional[float] = None
    total_cartons: Optional[int] = None


# ─── Document Classification ─────────────────────────────────────────────────

class DocumentClassification(BaseModel):
    """
    Three-dimensional BOL classification per DOT/FMCSA requirements.

    Dimension 1 — Functional & Legal Type:
        straight:  Non-negotiable, consigned to a specific party
        order:     Negotiable, contains "to order" / endorsement language
        master:    Consolidation — references multiple underlying BOLs
        through:   Multi-carrier / intermodal under one issuer
        ocean:     Maritime-specific (vessel, ports, containers)

    Dimension 2 — Regulatory & Commodity Type:
        general:   Standard freight (49 CFR 373.101)
        hazmat:    Hazardous materials (49 CFR 172/173)
        household: Consumer moving services (FMCSA 49 CFR 375.505)

    Dimension 3 — Transport Mode:
        ltl:       Less-Than-Truckload (PRO number, NMFC class)
        tl:        Full Truckload (trailer number, sealed shipment)
        ocean:     Ocean container / drayage
        air:       Air freight
        intermodal: Multi-mode
    """
    functional_type: Optional[str] = Field(
        "straight",
        description="straight | order | master | through | ocean"
    )
    regulatory_type: Optional[str] = Field(
        "general",
        description="general | hazmat | household"
    )
    transport_mode: Optional[str] = Field(
        None,
        description="ltl | tl | ocean | air | intermodal"
    )

    # Explain *why* the system classified this way
    functional_type_signals: list[str] = Field(
        default_factory=list,
        description="Signals that triggered functional type classification"
    )
    regulatory_type_signals: list[str] = Field(
        default_factory=list,
        description="Signals that triggered regulatory type classification"
    )
    transport_mode_signals: list[str] = Field(
        default_factory=list,
        description="Signals that triggered transport mode classification"
    )

    is_hazmat: bool = Field(False, description="Quick flag: any hazmat items?")
    is_master_bol: bool = Field(False, description="Quick flag: consolidation BOL?")
    is_negotiable: bool = Field(False, description="Quick flag: negotiable/order BOL?")


# ─── Root Document Model ─────────────────────────────────────────────────────

class BOLDocument(BaseModel):
    """
    Unified Bill of Lading schema — covers domestic LTL, ocean container,
    truckload, hazmat, and generic shipping documents.

    Designed for graceful degradation: every field is optional except
    `document_type` and `extraction_method`.
    """
    # Document metadata
    document_type: str = Field("bill_of_lading", description="Detected document type")
    document_subtype: Optional[str] = Field(None, description="e.g., ltl, ocean, drayage")
    document_date: Optional[str] = None

    # ── NEW: Three-dimensional classification ──
    classification: Optional[DocumentClassification] = Field(
        None,
        description="Functional type, regulatory type, and transport mode"
    )

    # Key identifiers — varies by document type
    references: Optional[dict[str, Optional[str]]] = Field(
        default_factory=dict,
        description="All reference numbers: bol_number, pro_number, po_number, etc."
    )

    # Parties
    parties: list[Party] = Field(default_factory=list)

    # Carrier
    carrier: Optional[CarrierInfo] = None

    # Shipping logistics
    shipping_details: Optional[ShippingDetails] = None

    # Items
    line_items: list[LineItem] = Field(default_factory=list)

    # Totals
    totals: Optional[Totals] = None

    # Ocean-specific (optional)
    vessel_info: Optional[VesselInfo] = None
    container_info: Optional[ContainerInfo] = None

    # Extraction metadata
    raw_text: Optional[str] = Field(None, description="Full extracted text for debugging")
    extraction_method: str = Field("unknown", description="pdfplumber, vision_llm, hybrid, verified")
    extraction_confidence: float = Field(0.0, description="0.0 to 1.0 confidence score")
    extraction_warnings: list[str] = Field(default_factory=list)

    # Verification metadata
    is_verified: bool = Field(False, description="True if LLM verification confirmed the primary extraction")
    verification_method: Optional[str] = Field(None, description="The LLM backend that performed verification (e.g. gemini, openai)")
    verification_discrepancies: list[str] = Field(default_factory=list, description="Fields where Primary and LLM disagreed")

    def to_json(self) -> str:
        """Serialize to pretty-printed JSON string."""
        return self.model_dump_json(indent=2, exclude_none=True)

    def compute_confidence(self) -> float:
        """
        Compute extraction confidence based on how many key fields were extracted.
        Weights: references and parties are most important.
        """
        score = 0.0
        max_score = 0.0

        # References (high weight)
        max_score += 3.0
        ref_count = len(self.references)
        score += min(ref_count, 3) * 1.0

        # Parties (high weight)
        max_score += 2.0
        party_count = len([p for p in self.parties if p.address and p.address.name])
        score += min(party_count, 2) * 1.0

        # Carrier
        max_score += 1.0
        if self.carrier and self.carrier.name:
            score += 1.0

        # Line items
        max_score += 1.0
        if self.line_items:
            score += 1.0

        # Shipping details
        max_score += 1.0
        if self.shipping_details and (self.shipping_details.pickup_date or self.shipping_details.freight_terms):
            score += 1.0

        # Document date
        max_score += 1.0
        if self.document_date:
            score += 1.0

        # Totals
        max_score += 1.0
        if self.totals and (self.totals.total_weight or self.totals.total_pieces):
            score += 1.0

        # Classification (bonus)
        max_score += 1.0
        if self.classification and self.classification.functional_type:
            score += 1.0

        confidence = score / max_score if max_score > 0 else 0.0
        self.extraction_confidence = round(confidence, 2)
        return self.extraction_confidence
