# Deployment Guide: Ibis BOL Extractor

This guide covers deploying the Ibis platform to production and agentic environments in the 2026 stack.

## 1. Vercel Deployment (Serverless)

The repository is configured for Vercel out-of-the-box using the consolidated structure.

### Steps:
1. Connect your GitHub repository to Vercel.
2. Add the following Environment Variables:
   - GEMINI_API_KEY: Your Google AI Studio API Key.
3. Deploy. Vercel will automatically detect the vercel.json and serve the FastAPI backend through the /api/extract.py handler.

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
python3 -m uvicorn api.extract:app --host 0.0.0.0 --port 8000
```

## 3. Agentic Deployment (MCP)

To use the Ibis extractor as a native tool in Claude Desktop or Cursor, register it as an MCP server.

### Steps for Claude Desktop:
1. Open your Claude Desktop config file:
   ~/Library/Application Support/Claude/claude_desktop_config.json
2. Add the Ibis server to the mcpServers block.
3. Restart Claude Desktop. The ibis-extractor tools will now be available for document analysis.

## 4. Production Considerations
- **Memory**: Minimum 1GB RAM recommended for PDF rasterization.
- **Security**: The UI uses a strict Content Security Policy (CSP). If adding external scripts, update the middleware in /api/extract.py.
