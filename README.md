# IBIS BOL Extractor

A production-grade logistics extraction platform that converts unstructured Bills of Lading (BOLs) and Delivery Notes into strict, validated JSON data using Gemini 3.1 Vision AI.

##  Key Features
- **Template-Free**: Uses Gemini 3.1 Flash-Lite to understand document structure dynamically. No more regex or OCR-zone maintenance.
- **Multimodal**: Native support for PDF rasterization and direct Image (PNG, JPG, WEBP) processing.
- **High Accuracy**: Pre-processes documents at 300 DPI for maximum extraction fidelity.
- **Strict Schema**: Uses Pydantic v2 to enforce data integrity and specific business rules (e.g., numeric weights).
- **Modern UI**: Secure, responsive frontend with a CSP-compliant audit interface.

## Technical Architecture
- **Backend**: FastAPI (Python 3.10+)
- **Extraction Engine**: Gemini 3.1 Flash-Lite (via direct REST connectivity)
- **Deployment**: Vercel-optimized consolidated structure.
- **Frontend**: Vanilla HTML5 / Modern CSS / Event-Delegated JS.

## Quickstart

### Prerequisites
1. Get a [Gemini API Key](https://ai.google.dev/).
2. Install [Poppler](https://pdf2image.readthedocs.io/en/latest/installation.html) (required for local PDF processing).

### Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set your API Key
export GEMINI_API_KEY="your_api_key_here"

# Start the server (Local Development)
python3 -m uvicorn api.index:app --reload
```
The UI will be available at `http://127.0.0.1:8000`.

## 📂 Project Structure
- `api/index.py`: Unified Vercel/Local entry point.
- `api/lib/`: Core logic package.
    - `extraction.py`: Vision AI orchestration & PDF rasterization.
    - `schema.py`: Structured Pydantic logistics models.
    - `config.py`: Environment-driven configuration.
- `mcp_server.py`: Agentic integration server.
- `static/`: Frontend assets (index.html, style.css, app.js).
- `docs/`: Detailed specs and deployment guides.

## 📄 Documentation
- [Architecture Details](docs/ARCHITECTURE.md)
- [API Specification](docs/API.md)
- [Deployment Guide](docs/DEPLOYMENT.md)

---
**License**: Internal Proprietary - Ibis Labs
