# Deployment Guide: Ibis BOL Extractor

This guide covers deploying the Ibis platform to production and agentic environments in the 2026 stack.

## 1. Vercel Deployment (Serverless)

The repository is configured for Vercel out-of-the-box using the consolidated structure.

### Steps:
1. Connect your GitHub repository to Vercel.
2. Add the following Environment Variables:
   - GEMINI_API_KEY: Your Google AI Studio API Key.
3. Deploy. Vercel will automatically detect the vercel.json and serve the FastAPI backend through `api/extract.py` (the thin Vercel handler that imports the real app from `api/__init__.py`).

> [!IMPORTANT]
> **Timeout Configuration**: Our vercel.json is set to maxDuration: 60. If you encounter timeouts on a free account, try processing smaller documents or upgrading to Pro.

## 2. Docker / Cloud Deployment (Persistent)

For high-volume persistent workloads, a standard FastAPI container is recommended.

### Local Setup:
```bash
# Set API Key
export GEMINI_API_KEY="your_key_here"

# Install Dependencies
pip install -r requirements.txt

# Start Server
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000
```

## 3. Agentic Deployment (MCP)

To use the Ibis extractor as a native tool in Claude Desktop or Cursor, register it as an MCP server.

### Steps for Claude Desktop (macOS)

**1. Install dependencies** (if not already done):
```bash
cd /path/to/ibis-pdf-extractor
pip install -r requirements.txt
```

**2. Open your Claude Desktop config file:**
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**3. Add the `ibis-extractor` block to `mcpServers`:**
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

Replace `/path/to/ibis-pdf-extractor` with the absolute path to the project root (the directory containing `mcp_server.py`). The `cwd` is required — the server imports from `api.lib` relative to the project root.

> **Using a virtual environment?** Replace `"python3"` with the full path to your venv interpreter, e.g. `"/path/to/ibis-pdf-extractor/.venv/bin/python"`.

**4. Restart Claude Desktop.**

The following tools will now be available:
- **`extract_logistics_data`** — Pass a local file path (PDF, PNG, JPG, WEBP) to extract structured JSON. Returns a typed result based on the detected document type (`UnifiedBOL`, `CartageAdvice`, or best-effort flat extraction).
- **`get_logistics_schema`** — Returns the full `UnifiedBOL` JSON schema so Claude understands the available fields.

### Steps for Cursor

Add the same block under `mcpServers` in your Cursor MCP settings (`~/.cursor/mcp.json`).

## 4. Production Considerations
- **Memory**: Minimum 1GB RAM recommended for PDF rasterization.
- **Security**: The UI uses a strict Content Security Policy (CSP). If adding external scripts, update the middleware in `api/__init__.py`.
