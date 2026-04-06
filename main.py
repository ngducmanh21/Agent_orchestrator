"""Agent Orchestrator - Main entry point."""
import asyncio
import logging
import uvicorn

from core.config import Config
from modules.orchestrator import Orchestrator
from web.server import WebServer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def startup():
    """Initialize the orchestrator."""
    config = Config.from_env()
    orchestrator = Orchestrator(config)
    await orchestrator.initialize()
    return config, orchestrator


def main():
    """Run the application."""
    logger.info("🚀 Starting Agent Orchestrator...")

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


if __name__ == "__main__":
    main()
