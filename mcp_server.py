"""
mcp_server.py — Ibis Logistics MCP Server
Exposes the Ibis Vision AI pipeline as a set of tools for AI Agents.
Usage: mcp run mcp_server.py
"""
import base64
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from extraction import extract_bol_vision, preprocess_pdf_to_images
from schema import UnifiedBOL

# Initialize FastMCP server
mcp = FastMCP("Ibis Logistics Extractor")

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}

_MIME_BY_EXT: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _validate_file_path(file_path: str) -> Path:
    """
    Resolves and validates a file path before reading.
    - Resolves symlinks to prevent traversal via symlinks to sensitive files.
    - Confirms the path points to a regular file (not a directory or device).
    Raises ValueError with a descriptive message on any violation.
    """
    try:
        resolved = Path(file_path).resolve(strict=True)
    except (OSError, ValueError) as e:
        raise ValueError(f"File not found or inaccessible: {file_path}") from e

    if not resolved.is_file():
        raise ValueError(f"Path is not a regular file: {resolved}")

    return resolved


@mcp.tool()
def extract_logistics_data(file_path: str) -> str:
    """
    Extracts structured logistics data (BOL, Delivery Note) from a local file path.
    Supports PDF, PNG, JPG, JPEG, and WEBP.
    """
    try:
        resolved = _validate_file_path(file_path)
    except ValueError as e:
        return f"Error: {e}"

    ext = resolved.suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"Error: Unsupported file extension '.{ext}'"

    try:
        content = resolved.read_bytes()

        # 1. Preprocessing
        if ext == "pdf":
            base64_images = preprocess_pdf_to_images(content)
            mime_types = ["image/jpeg"] * len(base64_images)
        else:
            base64_images = [base64.b64encode(content).decode("utf-8")]
            mime_types = [_MIME_BY_EXT[ext]]

        # 2. Vision Extraction
        result = extract_bol_vision(base64_images, mime_types)

        # 3. Return as pretty JSON
        return json.dumps(result.model_dump(), indent=2)

    except Exception as e:
        return f"Extraction Failed: {e}"


@mcp.tool()
def get_logistics_schema() -> str:
    """
    Returns the JSON representation of the UnifiedBOL schema to help the agent
    understand the available logistics fields and data structure.
    """
    return json.dumps(UnifiedBOL.model_json_schema(), indent=2)


if __name__ == "__main__":
    mcp.run()
