#!/usr/bin/env bash
set -euo pipefail

echo "=== Starting prospecting-mcp on port 8080 ==="
uv run python -m prospecting_mcp.server &
PROSP_PID=$!
sleep 2

echo "=== Starting sending-mcp on port 8081 ==="
PORT=8081 uv run python -m sending_mcp.server &
SEND_PID=$!
sleep 2

cleanup() {
  kill $PROSP_PID $SEND_PID 2>/dev/null || true
}
trap cleanup EXIT

MCP_SECRET=${MCP_SHARED_SECRET:-"test-secret"}

echo ""
echo "=== Smoke test: prospecting-mcp tools/list ==="
curl -s -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "X-MCP-Auth: $MCP_SECRET" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}'

echo ""
curl -s -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "X-MCP-Auth: $MCP_SECRET" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

echo ""
echo "=== Smoke test: sending-mcp tools/list ==="
curl -s -X POST http://localhost:8081/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "X-MCP-Auth: $MCP_SECRET" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}'

echo ""
curl -s -X POST http://localhost:8081/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "X-MCP-Auth: $MCP_SECRET" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

echo ""
echo "=== Auth rejection test (should 401) ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
echo "Status without auth header: $HTTP_CODE"

echo ""
echo "=== Done ==="
