# Ibis v2.0 Architecture: The Modern Archivist (2026 Edition)

The Ibis Logistics Extractor is designed as a **Decoupled 4-Layer Vision Pipeline**. This document details the technical implementation of each layer.

---

## 🖼️ Layer 1: The Rasterization Engine (`preprocessing.py`)
Direct LLM analysis of high-fidelity PDFs often leads to token bloat or truncation. Our engine normalizes every document before analysis.
- **Process**: Uses `pdf2image` (Poppler backend) to convert PDF pages into 300 DPI JPEG buffers.
- **Why?**: 300 DPI is the "goldilocks" resolution for Vision-LLMs—high enough for small text (like NMFC codes) but efficient enough for low-latency inference.
- **Scope**: By default, targets pages 1 & 2, where 95% of headers and line items reside.

## 🧹 Layer 2: Sanitization & Flattening (`extraction.py`)
Modern Vision-LLMs (Gemini 3.1) in **Structured Output** mode require a "Pure JSON Schema" (JSON Schema draft 4+ compatible). 
- **The Challenge**: Standard Pydantic schemas contain keywords like `$defs`, `$ref`, `anyOf`, and metadata (`title`, `description`) that Gemini currently rejects.
- **Our Solution**: The `resolve_schema_refs` utility recursively traverses the Pydantic schema, resolving all references and stripping metadata to present a clean, flat schema to the model.

## 🎯 Layer 3: Orchestration Layer (`extraction.py`)
This layer handles the multimodal request construction.
- **REST Implementation**: We bypass standard SDKs in favor of `httpx` direct REST calls to the Gemini `v1beta` endpoint. This ensures 100% control over the payload and avoids SDK-level model resolution errors.
- **Persona-Driven Prompting**: Injects a high-seniority "Compliance Auditor" persona with specific rules for Seafrigo, Cavendish, and IKEA document patterns.

## 🏛️ Layer 4: Data Validation (`schema_unified.py`)
Final data integrity is enforced via Pydantic v2.
- **Validation**: Even if the LLM returns valid JSON, this layer ensures field types, mandatory fields, and proprietary tracking formats are strictly followed.
- **Dynamic Mapping**: Supports specialized fields like `BDD`, `Frozen date`, and `SF Plan#`.

---

## 🔌 Interface Access
1. **FastAPI (`api.py`)**: Unified REST endpoint for web/mobile integrations.
2. **MCP Server (`mcp_server.py`)**: Local agentic integration for Claude Desktop and Cursor.
