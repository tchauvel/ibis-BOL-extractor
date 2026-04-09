# IBIS BOL Extractor

A production-grade logistics extraction platform that converts unstructured, highly variable Bills of Lading (BOLs), Delivery Notes, and Master BOLs into strict, validated JSON data using Gemini Vision AI.

## Engineering and Business Judgment

This project was built with the philosophy that data extraction must serve regulatory compliance and supply chain workflows, not just transcribe text.

### 1. What We Choose to Extract (Prioritizing Liability)

Rather than scraping the document left-to-right, the pipeline acts as an expert Compliance Auditor, prioritizing data that carries legal and financial weight:

*   **FMCSA Mandated Fields**: Actively extracts the 17 fields mandated by 49 CFR 375.505 (e.g., exact weights, carrier SCACs, and the presence of shipper/carrier signatures) to prevent regulatory fines and freight claim denials.
*   **Regulatory Triggers (Hazmat)**: Scans for DOT compliance markers under 49 CFR 172.202, such as UN identification numbers (e.g., UN1184), Hazard Classes, and emergency contact information.
*   **Cold Chain and Operational Metadata**: Actively hunts for hidden operational data essential for food logistics, such as Temperature Setpoints, Best Before Dates (BDD), Frozen Dates, and proprietary Web ID# identifiers. Non-standard references (Plan#, Customer PO, etc.) are captured in a structured `other_references` array.

### 2. How We Structure It (Designing for Resilience)

The data is mapped into a single UnifiedBOL Pydantic schema, designed to handle extreme variation across LTL, Truckload, Ocean, and Master BOLs:

*   **Granular Inventory Decoupling**: Adhering to GS1 US supply chain standards, the schema separates handling_unit_qty (what the forklift moves, e.g., pallets) from package_qty (the inner units, e.g., cartons) to prevent warehouse receiving miscounts.
*   **Flexible Catch-All Arrays**: Real-world shippers invent custom reference labels daily. The schema uses a dynamic other_references array to capture unexpected identifiers as key-value pairs, ensuring the database never breaks on unseen PDF formats.
*   **Graceful Degradation**: Fields specific to maritime tracking (e.g., Vessel Name, Seal Number) or cold storage naturally default to null on standard documents without hallucinating data.

## Technical Architecture

The system uses a Consolidated 3-Phase Vision Pipeline:

1.  **High-Fidelity Normalization**: Uses `fitz` (PyMuPDF) to rasterize PDF pages (pages 1 and 2) into 300 DPI JPEG buffers. This is the optimal resolution for Vision-LLMs to read fine print like NMFC codes without exceeding token limits.
2.  **Sanitization and Structured Orchestration**: Uses Gemini in Structured Output mode. The pipeline bypasses standard SDKs for direct REST calls, resolving Pydantic schema references into the pure JSON Schema Gemini requires.
3.  **Validation and Integrity**: A Pydantic v2 layer enforces strict data types (numeric weights, ISO 8601 dates with locale-aware slash-format resolution, English-only field names) before the API responds.

## Quickstart

### Prerequisites
*   A Google Gemini API Key.
*   Python 3.11+ (PyMuPDF handles PDF rasterization natively — no system-level dependencies like poppler required).

### Local Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set your API Key
export GEMINI_API_KEY="your_api_key_here"

# Start the server (Local Development)
python3 -m uvicorn api.extract:app --reload
```
The UI will be available at `http://127.0.0.1:8000`.

## API Reference

### POST /extract-bol
Accepts a multipart/form-data upload of a PDF or image (PNG, JPG, WEBP) and returns a validated JSON object.

#### Response Schema (UnifiedBOL)
```json
{
  "bol_number": "06141411234567890",
  "pro_number": null,
  "waybill_number": null,
  "order_number": "PO-998877",
  "web_id": null,
  "master_bol_indicator": false,
  "origin_country_code": "US",
  "logistics_dates": {
    "document_date": "2026-03-30",
    "dispatch_or_ship_date": "2026-03-30",
    "delivery_date": null,
    "appointment_time": null,
    "arrival_time": null,
    "leaving_time": null
  },
  "shipper": {
    "name": "ACME FOODS INC",
    "address": {
      "address_line": "123 WAREHOUSE BLVD",
      "city": "CHICAGO",
      "state": "IL",
      "zip_code": "60601",
      "country_code": "US",
      "phone": "+1-312-555-0100"
    }
  },
  "consignee": {
    "name": "METRO DISTRIBUTION CENTER",
    "address": {
      "address_line": "456 RECEIVING DR",
      "city": "DALLAS",
      "state": "TX",
      "zip_code": "75201",
      "country_code": "US",
      "phone": null
    }
  },
  "third_party_bill_to": null,
  "carrier_name": "XPO Logistics",
  "scac_code": "XPOL",
  "vessel_name": null,
  "voyage_number": null,
  "container_number": null,
  "seal_number": null,
  "temperature_setpoint_fahrenheit": 34.0,
  "temperature_recorder_number": "TR-20045",
  "line_items": [
    {
      "handling_unit_qty": 5,
      "handling_unit_type": "PLT",
      "package_qty": 60,
      "package_type": "Cartons",
      "weight_lbs": 2000.0,
      "item_description": "FROZEN SEAFOOD - SHRIMP",
      "article_or_item_number": "SHR-001",
      "best_before_or_expiration_date": "2026-09-01",
      "frozen_date": "2026-01-15",
      "batch_lot_number_or_supplier_ref": "LOT-4421",
      "nmfc_code": "155240",
      "freight_class": 70.0,
      "is_hazardous": false,
      "un_number": null
    }
  ],
  "other_references": [
    { "reference_label": "Plan#", "reference_value": "PLN-88123" },
    { "reference_label": "Customer Reference", "reference_value": "CUST-REF-2290" }
  ],
  "grand_total_weight_lbs": 2000.0,
  "grand_total_handling_units": 5,
  "shipper_signature_present": true,
  "carrier_signature_present": false,
  "_pipeline": {
    "processing_time_ms": 14500,
    "pages_processed": 2,
    "model": "Gemini Flash-Lite",
    "request_id": "b3d2f1a0-9c4e-4f8b-a123-0e1f2d3c4b5a"
  }
}
```
Note: The `_pipeline` object contains telemetry for latency and request tracing.

## Deployment

### 1. Vercel (Serverless)
The repository is structured to deploy natively to Vercel.
1.  Connect the GitHub repository.
2.  Add your `GEMINI_API_KEY` to the environment variables.
3.  Set the function timeout (`maxDuration`) to 60 seconds in your `vercel.json` to accommodate LLM processing times.

### 2. Agentic MCP Integration
To use the Ibis extractor as a native tool in Claude Desktop or Cursor, add the following to your MCP config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ibis-extractor": {
      "command": "python3",
      "args": ["mcp_server.py"],
      "cwd": "/path/to/ibis-pdf-extractor",
      "env": {
        "GEMINI_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

Restart Claude Desktop. The `extract_logistics_data` and `get_logistics_schema` tools will be available for document analysis via natural language. See `docs/DEPLOYMENT.md` for full setup details including virtual environment and Cursor configuration.

---
**License**: Internal Proprietary - Ibis Labs
