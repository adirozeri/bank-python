# Standalone image for the MCP config/prompts server. Independent of the LangGraph app image
# so it can be built, versioned, and deployed on its own. The config + prompt files are baked
# in — this service is their sole owner.
#
# Build from the repo root:  docker build -f mcp_server/Dockerfile -t bank-mcp .
FROM python:3.12-slim

WORKDIR /srv

COPY mcp_server/requirements.txt ./mcp_server/requirements.txt
RUN pip install --no-cache-dir -r mcp_server/requirements.txt

# Code + config/ + prompts/ all bundled in the image.
COPY mcp_server/ ./mcp_server/

EXPOSE 8000
ENV MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8000

CMD ["python", "-m", "mcp_server.server"]
