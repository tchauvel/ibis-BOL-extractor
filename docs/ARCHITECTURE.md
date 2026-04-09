# Architecture:

The Ibis Logistics Extractor is designed as a Consolidated 3-Phase Vision Pipeline. This document details the technical implementation of each phase within the Vercel-native structure.

---

## Phase 1: High-Fidelity Normalization (`api/lib/extraction.py`)

Direct LLM analysis of raw PDFs often leads to token bloat or failure. The pipeline normalizes all documents into a high-fidelity image stream before analysis.

- **Process**: Memory-efficient rasterization using `fitz` (PyMuPDF) converts PDF pages into 300 DPI JPEG buffers.
- **Why 300 DPI**: High enough for small text (NMFC codes, lot numbers, BDD stamps) without exceeding Vision-LLM token limits.
- **Scope**: Pages 1 and 2, which contain all headers, routing blocks, and primary line items on every BOL format encountered in practice.

## Phase 2: Sanitization and Structured Orchestration (`api/lib/extraction.py`)

Gemini in Structured Output mode requires a "Pure JSON Schema" — no `$ref`, `$defs`, `anyOf`, or metadata fields.

- **Schema Resolution**: The `resolve_schema_refs` utility recursively traverses the Pydantic-generated schema, resolving all references and stripping incompatible metadata before sending to Gemini.
- **REST Implementation**: Direct `httpx` REST calls bypass the Gemini SDK, giving full payload control and eliminating SDK-level model resolution errors.
- **Persona-Driven Audit**: The system prompt injects a "Senior Compliance Auditor" persona with explicit rules for language (English only), date format (ISO 8601), weight units (numeric lbs), and reference routing (Plan#, Customer Ref → `other_references`).

## Phase 3: Validation and Integrity (`api/lib/schema.py`)

Final data integrity is enforced via Pydantic v2 with two validation passes:

- **Locale-Aware Date Normalization**: A `model_validator(mode="before")` runs first on the full raw dict. It reads `origin_country_code` (or falls back to `shipper.address.country_code`) to determine whether slash-format dates like `"04/03/2026"` should be parsed as MM/DD (US) or DD/MM (EU/Oceania/Latin America). This resolves the fundamental ambiguity that a field-level validator cannot, because it lacks document context.
- **Field-Level Validation**: Field validators on `LogisticsDates` handle any remaining date normalization (covering 15 formats including EDI compact, maritime short-year, and European dot-separated). Numeric validators on weight fields strip unit suffixes and coerce strings to floats.
- **Graceful Degradation**: Maritime fields (`vessel_name`, `seal_number`), cold-chain fields, and optional references default to `null` on standard documents without hallucinating data.

---

## Entry Points

1. **Serverless Handler (`api/extract.py`)**: FastAPI endpoint with rate limiting (`slowapi`), security headers, request tracing (`X-Request-ID`), and dual routing (`/extract-bol` + `/api/extract-bol` for Vercel).
2. **MCP Server (`mcp_server.py`)**: Agentic integration for Claude Desktop and Cursor, enabling local document audits via natural language.
