#!/bin/bash
# Run MCP Server via Docker container.
# This script is meant to be called by VS Code MCP clients (Cline/Cursor).
# It uses docker run with stdin/stdout pipe (stdio transport).
#
# Usage in MCP config:
#   "command": "/path/to/agent_orchestrator/mcp/run_mcp_docker.sh"
#
# Prerequisites:
#   - Docker must be running
#   - docker-compose up qdrant (or the full stack) must be running
#   - Image must be built: docker compose build orchestrator

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Build image if not exists
docker image inspect agent-orchestrator >/dev/null 2>&1 || \
  docker compose -f "$SCRIPT_DIR/docker-compose.yml" build orchestrator >/dev/null 2>&1

# Run MCP server with stdio (interactive, no TTY, remove on exit)
# Connect to host network so it can reach Qdrant on localhost:6333
# Mount repos directory for file operations
exec docker run --rm -i \
  --network host \
  --name agent-mcp-$$ \
  -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
  -e ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-}" \
  -e AI_MODEL="${AI_MODEL:-claude-sonnet-4-20250514}" \
  -e QDRANT_HOST="${QDRANT_HOST:-localhost}" \
  -e QDRANT_PORT="${QDRANT_PORT:-6333}" \
  -e REPOS_DIR="/app/data/repos" \
  -v "$SCRIPT_DIR/data/repos:/app/data/repos" \
  -v "$SCRIPT_DIR/data/indexes:/app/data/indexes" \
  agent-orchestrator \
  python main.py --mcp
