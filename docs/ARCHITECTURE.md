# Ibis v2.0 Architecture: The Modern Archivist (2026 Edition)

The Ibis Logistics Extractor is designed as a **Consolidated 3-Phase Vision Pipeline**. This document details the technical implementation of each phase within the Vercel-native structure.

---

## Phase 1: High-Fidelity Normalization (`api/lib/extraction.py`)
Direct LLM analysis of raw PDFs often leads to token bloat or failure. Our pipeline normalizes all documents into a high-fidelity image stream before analysis.
- **Process**: Implements memory-efficient rasterization using `fitz` (PyMuPDF) to convert PDF pages into 300 DPI JPEG buffers.
- **Why?**: 300 DPI is the "goldilocks" resolution for Vision-LLMs—high enough for small text (like NMFC codes or lot numbers) without exceeding token limits.
- **Scope**: Targets pages 1 & 2, ensuring discovery of all headers and primary line items.

## Phase 2: Sanitization & Structured Orchestration (`api/lib/extraction.py`)
Modern Vision-LLMs (Gemini 3.1) in **Structured Output** mode require a "Pure JSON Schema".
- **Schema Resolution**: We implement the `resolve_schema_refs` utility to recursively traverse Pydantic schemas, resolving references ($refs) and stripping metadata ($defs) that Gemini otherwise rejects.
- **REST Implementation**: We bypass standard SDKs for `httpx` direct REST calls. This ensures full payload control and eliminates SDK-level model resolution errors.
- **Persona-Driven Audit**: Injects a high-seniority "Compliance Auditor" persona with logic specialized for enterprise-tier logistics and retail documentation.

## Phase 3: Validation & Integrity (`api/lib/schema.py`)
Final data integrity is enforced via Pydantic v2.
- **Stricter Validation**: Even if the LLM returns valid JSON, this layer ensures field types, mandatory fields, and proprietary tracking formats (e.g., weights in numeric lbs) are strictly followed.
- **Dynamic Field Support**: Natively supports specialized fields like `BDD`, `Frozen date`, and proprietary Plan numbers.

---

## Entry Points
1. **Serverless Handler (`api/extract.py`)**: Unified FastAPI endpoint optimized for Vercel Serverless Functions.
2. **MCP Server (`mcp_server.py`)**: Agentic integration for Claude Desktop and Cursor, enabling local document audits directly via natural language.
