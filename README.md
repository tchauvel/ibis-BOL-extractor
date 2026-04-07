# IBIS PDF Extractor

**PDF → Structured JSON in seconds.**

A repeatable Python system that ingests PDFs (Bills of Lading) and outputs structured JSON data. Built for the IBIS Labs Senior Technical Assignment.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run via CLI
python main.py samples/DEN5755177.pdf
python main.py samples/TCLU7950467.pdf

# 3. Or start the web UI
python -m uvicorn app:app --port 8000
# Then open http://localhost:8000
```

## Architecture

```
PDF Upload → Text Extraction (pdfplumber) → Document Classifier → Type-Specific Parser → Unified JSON
                    ↓ (if scanned/image)
              Vision LLM Fallback (Ollama / DeepSeek)
```

### Core Interface

```python
from process_document import process_document

result = process_document("path/to/document.pdf")  # Returns dict
```

### How It Works

1. **Extract** — `pdfplumber` extracts text + tables with spatial layout preservation
2. **Classify** — Keyword scoring identifies document type (LTL, Ocean, Unknown)
3. **Parse** — Type-specific parser extracts structured fields using regex + heuristics
4. **Validate** — Pydantic schema validates, computes confidence score, flags warnings
5. **Fallback** — If text extraction fails, vision LLM (Ollama/DeepSeek) processes page images

### Supported Document Types

| Type | Description | Parser |
|------|-------------|--------|
| `bol_ltl` | Domestic LTL freight (FedEx, UPS, etc.) | `LTLBOLParser` |
| `bol_ocean` | Ocean container / drayage | `OceanBOLParser` |
| `unknown` | Any unrecognized document | `GenericParser` + Vision LLM |

## Project Structure

```
├── process_document.py    # Core interface
├── main.py                # CLI entry point
├── app.py                 # FastAPI web server + API
├── schema.py              # Pydantic models (unified BOL schema)
├── classifier.py          # Document type detection
├── extractors/            # PDF text extraction
├── parsers/               # Type-specific parsing logic
├── llm/                   # Vision LLM integration (Ollama/DeepSeek)
├── static/                # Web UI (HTML/CSS/JS)
└── samples/               # Sample PDFs
```

## Key Design Decisions

### Why pdfplumber over PyPDF2?
PyPDF2 failed to extract text from our sample documents. pdfplumber preserves spatial layout and has built-in table extraction — critical for form-like BOL documents.

### Why regex + heuristics as primary, LLM as fallback?
- **Determinism**: Regex gives consistent, testable results
- **Speed**: No API calls for known document types
- **Reliability**: No network dependency during the live session
- **Flexibility**: LLM handles anything thrown at it as a fallback

### Why confidence scoring?
A senior system should be self-aware. The confidence score tells the consumer whether to trust the output or flag it for manual review.

## Vision LLM Setup (Optional)

For handling scanned/image-based PDFs or unknown document types:

### Option 1: Ollama (Local, Free)
```bash
# Install Ollama
brew install ollama

# Pull a vision model
ollama pull llava

# The system auto-detects Ollama when running
```

### Option 2: DeepSeek API (Cloud, Cheap)
```bash
export DEEPSEEK_API_KEY="your-key-here"
```

## Web UI

Start the server and open `http://localhost:8000`:

```bash
python -m uvicorn app:app --port 8000
```

Features:
- Drag-and-drop or click-to-upload
- Process multiple documents at once
- Syntax-highlighted JSON output with copy button
- Confidence scoring badges
- Extraction warnings display

## API Endpoint

```bash
curl -X POST http://localhost:8000/api/process \
  -F "file=@samples/DEN5755177.pdf"
```

## Testing

```bash
# Run tests
pytest tests/ -v

# Test CLI directly
python main.py samples/DEN5755177.pdf --verbose
python main.py samples/TCLU7950467.pdf --output output/tclu_result.json
```
