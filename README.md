# IBIS BOL Extractor (v2.0 Vision AI)

A production-grade logistics extraction platform that converts unstructured Bills of Lading (BOLs) and Delivery Notes into strict, validated JSON data.

## 🚀 Key Features
- **Template-Free**: Uses Gemini 3.1 Vision-LLM to understand document structure dynamically. No more regex or OCR-zone maintenance.
- **Multimodal**: Native support for PDF rasterization and direct Image (PNG, JPG, WEBP) processing.
- **High Accuracy**: Pre-processes documents at 300 DPI for maximum extraction fidelity.
- **Strict Schema**: Uses Pydantic v2 to enforce data integrity and specific business rules (e.g., numeric weights, standardized field names).
- **Modern UI**: Clean, responsive frontend for immediate auditing and JSON output.

## 🏗️ Technical Architecture
- **Backend**: FastAPI (Python 3.10+)
- **Extraction Engine**: Gemini 3.1 Flash-Lite (via REST API)
- **Validation**: Pydantic v2
- **Frontend**: Vanilla HTML5 / Modern CSS / JS

## 📦 Quickstart

### Prerequisites
1. Get a [Gemini API Key](https://ai.google.dev/).
2. Install [Poppler](https://pdf2image.readthedocs.io/en/latest/installation.html) (for PDF processing).

### Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variable
export GEMINI_API_KEY="your_api_key_here"

# Start the server
python3 -m uvicorn api.py:app --reload
```
The UI will be available at `http://127.0.0.1:8000`.

## 📂 Project Structure
- `api.py`: Main FastAPI entry point.
- `extraction.py`: Vision AI orchestration logic.
- `preprocessing.py`: PDF-to-Image rasterization utilities.
- `schema_unified.py`: Pydantic data models.
- `static/`: Frontend assets.
- `docs/`: Detailed specs and deployment guides.

## 📄 License
Internal Proprietary - Ibis Labs
