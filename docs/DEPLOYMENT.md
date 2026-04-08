# Deployment Guide: Ibis BOL Extractor

This guide covers deploying the Ibis platform to production environments in the 2026 stack.

## 1. Vercel Deployment (Serverless)

The repository is configured for Vercel out of the box using the `api/index.py` proxy.

### Steps:
1. Connect your GitHub repository to Vercel.
2. Add the following **Environment Variables**:
   - `GEMINI_API_KEY`: Your Google AI Studio API Key.
3. Deploy. Vercel will automatically detect the `vercel.json` and serve the FastAPI backend.

## 2. Docker / Cloud Deployment (Persistent)

For high-volume persistent workloads, a standard FastAPI container is recommended.

### Prerequisites:
- Python 3.10+
- `poppler-utils` (Required for `pdf2image`)

### Manual Start:
```bash
# Set API Key
export GEMINI_API_KEY="your_key_here"

# Install Dependencies
pip install -r requirements.txt

# Start Server
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000
```

## 3. Agentic Deployment (MCP)

To use the Ibis extractor as a native tool in **Claude Desktop** or **Cursor**, register it as an MCP server.

### Steps for Claude Desktop:
1. Open your Claude Desktop config file:
   `~/Library/Application\ Support/Claude/claude_desktop_config.json`
2. Add the Ibis server to the `mcpServers` block:
```json
{
  "mcpServers": {
    "ibis-extractor": {
      "command": "python3",
      "args": ["/absolute/path/to/ibis-pdf-extractor/mcp_server.py"],
      "env": {
        "GEMINI_API_KEY": "your_api_key_here"
      }
    }
  }
}
```
3. Restart Claude Desktop. You will now see the `Ibis Logistics Extractor` in the tool icon.

## 4. Production Considerations
- **Memory**: Ensure the instance has at least 1GB of RAM for high-DPI PDF rasterization.
- **Timeout**: Set the gateway timeout to at least 60s, as Vision-LLM extraction can take 5-15s per multi-page document.
