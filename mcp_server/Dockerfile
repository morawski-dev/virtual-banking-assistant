FROM python:3.12-slim

WORKDIR /app

# Install dependencies: MCP SDK + aiohttp for calling mock_cb
RUN pip install --no-cache-dir "mcp[cli]>=1.9" aiohttp

COPY mcp_server/ /app/mcp_server/

EXPOSE 8001

CMD ["python", "-m", "mcp_server.server"]
