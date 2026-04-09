# Architecture

The Ibis Logistics Extractor is a two-pass Vision Pipeline that auto-detects the document type before extracting typed structured data. This document details the technical implementation within the Vercel-native structure.

---

## Pipeline Overview

```
PDF/Image → Phase 1: Rasterize → Phase 2: Classify → Phase 3: Extract → Phase 4: Validate
```

Each request through `/extract` runs two sequential Gemini Vision calls:

1. **Pass 1 (Classification)** — lightweight plain-text call; returns one of `bol`, `cartage_advice`, or `unknown`
2. **Pass 2 (Extraction)** — structured output call using the schema and system prompt matched to the detected type

---

## Phase 1: High-Fidelity Normalization (`api/lib/extraction.py`)

Direct LLM analysis of raw PDFs often leads to token bloat or failure. The pipeline normalizes all documents into a high-fidelity image stream before analysis.

- **Process**: Memory-efficient rasterization using `fitz` (PyMuPDF) converts PDF pages into 300 DPI JPEG buffers.
- **Why 300 DPI**: High enough for small text (NMFC codes, lot numbers, BDD stamps) without exceeding Vision-LLM token limits.
- **Scope**: Pages 1 and 2, which contain all headers, routing blocks, and primary line items on every document format encountered in practice.

## Phase 2: Document Classification (`api/lib/extraction.py` → `classify_document`)

A cheap plain-text Gemini call determines the document type before running the heavier structured extraction.

- **Input**: Rasterized page images
- **Prompt**: Instructs Gemini to return exactly one of `bol`, `cartage_advice`, or `unknown` — no JSON schema enforcement
- **Normalization**: Response is `.strip().lower()`; any unrecognized value falls back to `"unknown"`
- **Why plain text**: Avoids schema overhead for a classification signal, keeping Pass 1 fast and inexpensive

## Phase 3: Sanitization and Structured Orchestration (`api/lib/extraction.py` → `extract_document`)

Gemini in Structured Output mode requires a "Pure JSON Schema" — no `$ref`, `$defs`, `anyOf`, or metadata fields.

- **Registry Lookup**: `get_registry_entry(document_type)` returns `(schema_cls, system_prompt)` for the detected type
- **Schema Resolution**: The `resolve_schema_refs` utility recursively traverses the Pydantic-generated schema, resolving all references and stripping incompatible metadata before sending to Gemini
- **REST Implementation**: Direct `httpx` REST calls bypass the Gemini SDK, giving full payload control and eliminating SDK-level model resolution errors
- **Persona-Driven Audit**: Each system prompt injects a domain-appropriate persona with explicit rules for language (English only), date format (ISO 8601), weight units, and field routing

## Phase 4: Validation and Integrity (`api/lib/schema.py`)

Final data integrity is enforced via Pydantic v2 with two validation passes:

- **Locale-Aware Date Normalization** (`UnifiedBOL`): A `model_validator(mode="before")` runs first on the full raw dict. It reads `origin_country_code` (or falls back to `shipper.address.country_code`) to determine whether slash-format dates like `"04/03/2026"` should be parsed as MM/DD (US) or DD/MM (EU/Oceania/Latin America). This resolves the fundamental ambiguity that a field-level validator cannot, because it lacks document context.
- **Field-Level Validation**: Field validators on `LogisticsDates`, `RoutingLeg`, and `CartageAdvice` handle remaining date normalization (covering 15+ formats including EDI compact, maritime short-year, and European dot-separated). Numeric validators strip unit suffixes and coerce strings to floats.
- **Graceful Degradation**: Optional fields default to `null` on documents where they don't apply, without hallucinating data.

---

## Schema Registry (`api/lib/registry.py`)

The registry is the single source of truth for supported document types. It maps each type string to a `(Pydantic schema class, system prompt)` pair.

```python
REGISTRY = {
    "bol":            (UnifiedBOL,      BOL_SYSTEM_PROMPT),
    "cartage_advice": (CartageAdvice,   CARTAGE_ADVICE_SYSTEM_PROMPT),
    "unknown":        (GenericDocument, GENERIC_SYSTEM_PROMPT),
}
```

**To add a new document type:**
1. Add a schema class to `api/lib/schema.py`
2. Add a system prompt constant to `api/lib/registry.py`
3. Add one entry to `REGISTRY`
4. Add the new type string to `CLASSIFICATION_PROMPT`

No changes to `extraction.py`, `api/__init__.py`, or any existing schemas are required.

---

## Supported Document Types

| `document_type`  | Schema           | Description                              |
|------------------|------------------|------------------------------------------|
| `bol`            | `UnifiedBOL`     | Bill of Lading / Delivery Note (trucking/domestic) |
| `cartage_advice` | `CartageAdvice`  | Sea Freight FCL Arrival Cartage Advice   |
| `unknown`        | `GenericDocument`| Fallback — best-effort flat key-value extraction |

---

## Entry Points

1. **FastAPI Application (`api/__init__.py`)**: Real FastAPI app with rate limiting (`slowapi`), security headers, request tracing (`X-Request-ID`), and endpoint routing. Exposes `/extract` and `/api/extract` (Vercel alias).
2. **Vercel Handler (`api/extract.py`)**: Thin wrapper — imports the app and re-exports it as `handler` for Vercel's serverless runtime.
3. **MCP Server (`mcp_server.py`)**: Agentic integration for Claude Desktop and Cursor, enabling local document audits via natural language.
