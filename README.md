# IBIS Logistics Extractor

A production-grade logistics extraction platform that auto-detects the document type and converts unstructured freight documents — Bills of Lading (BOLs), Delivery Notes, Sea Freight Cartage Advice, and more — into strict, validated JSON data using Gemini Vision AI.

## Engineering and Business Judgment

This project was built with the philosophy that data extraction must serve regulatory compliance and supply chain workflows, not just transcribe text.

### 1. What We Choose to Extract (Prioritizing Liability)

Rather than scraping the document left-to-right, the pipeline acts as an expert Compliance Auditor, prioritizing data that carries legal and financial weight:

*   **FMCSA Mandated Fields**: Actively extracts the 17 fields mandated by 49 CFR 375.505 (e.g., exact weights, carrier SCACs, and the presence of shipper/carrier signatures) to prevent regulatory fines and freight claim denials.
*   **Regulatory Triggers (Hazmat)**: Scans for DOT compliance markers under 49 CFR 172.202, such as UN identification numbers (e.g., UN1184), Hazard Classes, and emergency contact information.
*   **Cold Chain and Operational Metadata**: Actively hunts for hidden operational data essential for food logistics, such as Temperature Setpoints, Best Before Dates (BDD), Frozen Dates, and proprietary Web ID# identifiers. Non-standard references (Plan#, Customer PO, etc.) are captured in a structured `other_references` array.

### 2. How We Structure It (Designing for Resilience)

Documents are auto-classified and routed to a type-specific Pydantic schema (`UnifiedBOL`, `CartageAdvice`, or a best-effort `GenericDocument` fallback), designed to handle extreme variation across LTL, Truckload, Ocean, and Master BOLs:

*   **Granular Inventory Decoupling**: Adhering to GS1 US supply chain standards, the schema separates handling_unit_qty (what the forklift moves, e.g., pallets) from package_qty (the inner units, e.g., cartons) to prevent warehouse receiving miscounts.
*   **Flexible Catch-All Arrays**: Real-world shippers invent custom reference labels daily. The schema uses a dynamic other_references array to capture unexpected identifiers as key-value pairs, ensuring the database never breaks on unseen PDF formats.
*   **Graceful Degradation**: Fields specific to maritime tracking (e.g., Vessel Name, Seal Number) or cold storage naturally default to null on standard documents without hallucinating data.

## Technical Architecture

The system uses a two-pass Vision Pipeline:

1.  **High-Fidelity Normalization**: Uses `fitz` (PyMuPDF) to rasterize PDF pages (pages 1 and 2) into 300 DPI JPEG buffers — optimal for Vision-LLMs reading fine print like NMFC codes without exceeding token limits.
2.  **Document Classification (Pass 1)**: A lightweight Gemini call returns the document type (`bol`, `cartage_advice`, or `unknown`). Fast and cheap — no schema enforcement.
3.  **Structured Extraction (Pass 2)**: A schema registry maps the detected type to its Pydantic model and system prompt. Gemini is called with structured output enforced via `responseSchema`. Direct REST calls bypass the SDK for full payload control.
4.  **Validation and Integrity**: A Pydantic v2 layer enforces strict data types (numeric weights, ISO 8601 dates with locale-aware slash-format resolution, English-only field names) before the API responds.

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
python3 -m uvicorn api:app --reload
```
The UI will be available at `http://127.0.0.1:8000`.

## API Reference

### POST /extract *(recommended)*

Accepts a multipart/form-data upload of a PDF or image (PNG, JPG, WEBP). Auto-detects the document type and returns a typed JSON envelope.

```bash
curl -X POST "https://ibis-bol-extractor.vercel.app/api/extract" \
     -F "file=@your_document.pdf" | jq
```

#### Response Envelope

```json
{
  "document_type": "bol | cartage_advice | unknown",
  "data": { ... },
  "_pipeline": {
    "processing_time_ms": 14500,
    "pages_processed": 2,
    "model": "Gemini 3.1 Flash-Lite",
    "request_id": "b3d2f1a0-9c4e-4f8b-a123-0e1f2d3c4b5a"
  }
}
```

The `data` field contains a typed schema depending on `document_type`:
- **`bol`** → `UnifiedBOL` (BOL number, shipper, consignee, line items, weights, signatures, cold-chain metadata…)
- **`cartage_advice`** → `CartageAdvice` (container, consol, routing legs, available date…)
- **`unknown`** → `{ "fields": { ... } }` (best-effort flat extraction)

See [`docs/API.md`](docs/API.md) for the full schema reference.

### POST /extract-bol *(legacy — not recommended)*

Always extracts as `UnifiedBOL` regardless of document type. Kept for backward compatibility only — use `/extract` for all new integrations.

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
