"""
schema.py — Unified BOL Data Model
Strict Pydantic v2 models for logistics extraction.
Includes validation for weights and specific field naming for Gemini compatibility.
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class Address(BaseModel):
    address_line: str = Field(..., description="Street address (including lines 1 & 2)")
    city: str
    state: str
    zip_code: str
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
    plan_number: Optional[str] = Field(None, description="Look for 'Plan#' or 'SF Plan#'")
    order_number: Optional[str] = Field(None, description="Look for 'Order#', 'SF Order#', or 'Cavendish Order No.'")
    web_id: Optional[str] = Field(None, description="Look for 'Web ID#'")
    customer_reference: Optional[str] = Field(None, description="Look specifically for 'CUSTOMER REF' or 'Customer PO. No.'")
    master_bol_indicator: bool = False
    
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
