# IBIS BOL Extractor

A production-grade logistics extraction platform that converts unstructured, highly variable Bills of Lading (BOLs), Delivery Notes, and Master BOLs into strict, validated JSON data using Gemini 3.1 Vision AI.

## Engineering and Business Judgment

This project was built with the philosophy that data extraction must serve regulatory compliance and supply chain workflows, not just transcribe text.

### 1. What We Choose to Extract (Prioritizing Liability)

Rather than scraping the document left-to-right, the pipeline acts as an expert Compliance Auditor, prioritizing data that carries legal and financial weight:

*   **FMCSA Mandated Fields**: Actively extracts the 17 fields mandated by 49 CFR 375.505 (e.g., exact weights, carrier SCACs, and the presence of shipper/carrier signatures) to prevent regulatory fines and freight claim denials.
*   **Regulatory Triggers (Hazmat)**: Scans for DOT compliance markers under 49 CFR 172.202, such as UN identification numbers (e.g., UN1184), Hazard Classes, and emergency contact information.
*   **Cold Chain and Operational Metadata**: Actively hunts for hidden operational data essential for food logistics, such as Temperature Setpoints, Best Before Dates (BDD), Frozen Dates, and proprietary Plan# or Web ID# identifiers.

### 2. How We Structure It (Designing for Resilience)

The data is mapped into a single UnifiedBOL Pydantic schema, designed to handle extreme variation across LTL, Truckload, Ocean, and Master BOLs:

*   **Granular Inventory Decoupling**: Adhering to GS1 US supply chain standards, the schema separates handling_unit_qty (what the forklift moves, e.g., pallets) from package_qty (the inner units, e.g., cartons) to prevent warehouse receiving miscounts.
*   **Flexible Catch-All Arrays**: Real-world shippers invent custom reference labels daily. The schema uses a dynamic other_references array to capture unexpected identifiers as key-value pairs, ensuring the database never breaks on unseen PDF formats.
*   **Graceful Degradation**: Fields specific to maritime tracking (e.g., Vessel Name, Seal Number) or cold storage naturally default to null on standard documents without hallucinating data.

## Technical Architecture

The system uses a Consolidated 3-Phase Vision Pipeline:

1.  **High-Fidelity Normalization**: Uses fitz (PyMuPDF) to rasterize PDF pages (pages 1 and 2) into 300 DPI JPEG buffers. This is the optimal resolution for Vision-LLMs to read fine print like NMFC codes without exceeding token limits.
2.  **Sanitization and Structured Orchestration**: Uses Gemini 3.1 Flash-Lite in Structured Output mode. The pipeline bypasses standard SDKs to make direct REST calls, utilizing schema resolution to strip incompatible metadata and force a pure JSON response.
3.  **Validation and Integrity**: A Pydantic v2 layer ensures strict data types (e.g., enforcing numeric weights and valid date formats) before the API responds.

## Quickstart

### Prerequisites
*   A Google Gemini API Key.
*   poppler installed on your system (required for local PDF rasterization).

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
  "carrier_name": "LTL Transportation",
  "grand_total_weight_lbs": 2000.00,
  "line_items": [
    {
      "handling_unit_qty": 5,
      "item_description": "Sport Accessories",
      "weight_lbs": 500.00
    }
  ],
  "_pipeline": {
    "processing_time_ms": 14500,
    "pages_processed": 1,
    "model": "Gemini 3.1 Flash-Lite"
  }
}
```
Note: The `_pipeline` object contains telemetry for latency and tracking.

## Deployment

### 1. Vercel (Serverless)
The repository is structured to deploy natively to Vercel.
1.  Connect the GitHub repository.
2.  Add your `GEMINI_API_KEY` to the environment variables.
3.  Set the function timeout (`maxDuration`) to 60 seconds in your `vercel.json` to accommodate LLM processing times.

### 2. Agentic MCP Integration
To use the Ibis extractor as a native tool in Claude Desktop or Cursor, you can register it as a Model Context Protocol (MCP) server:
1.  Open your Claude Desktop config file: `~/Library/Application Support/Claude/claude_desktop_config.json`
2.  Add the Ibis server to the `mcpServers` block.
3.  Restart Claude Desktop. The `ibis-extractor` tool will now be available for document analysis via natural language.

---
**License**: Internal Proprietary - Ibis Labs
