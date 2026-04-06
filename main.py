"""Agent Orchestrator - Main entry point.

Supports two modes:
  - Web UI mode (default): python main.py
  - MCP Server mode: python main.py --mcp
"""
import asyncio
import logging
import sys

from core.config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,  # Use stderr so MCP mode can use stdout for protocol
)
logger = logging.getLogger(__name__)


async def startup():
    """Initialize the orchestrator for Web UI mode."""
    from modules.orchestrator import Orchestrator
    config = Config.from_env()
    orchestrator = Orchestrator(config)
    await orchestrator.initialize()
    return config, orchestrator


def run_web():
    """Run the Web UI server."""
    import uvicorn
    from web.server import WebServer

    logger.info("🚀 Starting Agent Orchestrator (Web UI mode)...")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    config, orchestrator = loop.run_until_complete(startup())
    web_server = WebServer(config, orchestrator)

    logger.info(f"🌐 Web UI: http://0.0.0.0:{config.port}")
    logger.info(f"📡 Qdrant: {config.qdrant_host}:{config.qdrant_port}")
    logger.info(f"🤖 AI Model: {config.ai_model}")

    uvicorn.run(
        web_server.app,
        host="0.0.0.0",
        port=config.port,
        log_level="info",
    )


def run_mcp():
    """Run the MCP Server (stdio transport for VS Code integration)."""
    from mcp.server import main as mcp_main
    logger.info("🔌 Starting Agent Orchestrator (MCP Server mode)...")
    mcp_main()


def main():
    """Run the application in the appropriate mode."""
    if "--mcp" in sys.argv:
        run_mcp()
    else:
        run_web()


if __name__ == "__main__":
    main()
