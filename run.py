import uvicorn
from dotenv import load_dotenv
load_dotenv()

import uvicorn

if __name__ == "__main__":
    # Port 5002: the MCP server owns 8000. Start the MCP server first
    # (python -m mcp_server.server) so config/prompts are reachable.
    uvicorn.run(
        app="app.main:app",
        host="127.0.0.1",
        port=5002,
        reload=True,
    )