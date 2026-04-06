"""Lightweight MCP (Model Context Protocol) server library.

Implements the MCP JSON-RPC 2.0 protocol over stdio transport.
Compatible with VS Code extensions (Cline, Cursor, etc.).
"""
import asyncio
import json
import logging
import sys
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPServerLib:
    """Minimal MCP server implementation using stdio transport."""

    def __init__(self, name: str, version: str, description: str = ""):
        self.name = name
        self.version = version
        self.description = description
        self._tools: Dict[str, dict] = {}
        self._tool_handlers: Dict[str, Callable] = {}
        self._resources: Dict[str, dict] = {}
        self._resource_handlers: Dict[str, Callable] = {}

    def tool(self, name: str, description: str, parameters: dict = None):
        """Decorator to register a tool."""
        def decorator(func):
            schema = {"type": "object", "properties": {}, "required": []}
            if parameters:
                for pname, pdef in parameters.items():
                    schema["properties"][pname] = {
                        "type": pdef.get("type", "string"),
                        "description": pdef.get("description", ""),
                    }
                    if "items" in pdef:
                        schema["properties"][pname]["items"] = pdef["items"]
                    if "default" not in pdef:
                        schema["required"].append(pname)
            if not schema["required"]:
                del schema["required"]

            self._tools[name] = {
                "name": name,
                "description": description,
                "inputSchema": schema,
            }
            self._tool_handlers[name] = func
            return func
        return decorator

    def resource(self, uri: str, name: str, description: str = ""):
        """Decorator to register a resource."""
        def decorator(func):
            self._resources[uri] = {
                "uri": uri,
                "name": name,
                "description": description,
                "mimeType": "application/json",
            }
            self._resource_handlers[uri] = func
            return func
        return decorator

    async def _handle_request(self, msg: dict) -> dict:
        """Handle a single JSON-RPC request."""
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                    },
                    "serverInfo": {
                        "name": self.name,
                        "version": self.version,
                    },
                }
                return self._response(msg_id, result)

            elif method == "notifications/initialized":
                return None  # No response for notifications

            elif method == "ping":
                return self._response(msg_id, {})

            elif method == "tools/list":
                return self._response(msg_id, {"tools": list(self._tools.values())})

            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                handler = self._tool_handlers.get(tool_name)
                if not handler:
                    return self._error(msg_id, -32601, f"Unknown tool: {tool_name}")

                try:
                    result = await handler(**arguments)
                    return self._response(msg_id, {
                        "content": [{"type": "text", "text": str(result)}],
                        "isError": False,
                    })
                except Exception as e:
                    logger.error(f"Tool error [{tool_name}]: {e}", exc_info=True)
                    return self._response(msg_id, {
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                        "isError": True,
                    })

            elif method == "resources/list":
                return self._response(msg_id, {"resources": list(self._resources.values())})

            elif method == "resources/read":
                uri = params.get("uri", "")
                handler = self._resource_handlers.get(uri)
                if not handler:
                    return self._error(msg_id, -32601, f"Unknown resource: {uri}")
                try:
                    content = await handler()
                    return self._response(msg_id, {
                        "contents": [{"uri": uri, "mimeType": "application/json", "text": content}]
                    })
                except Exception as e:
                    return self._error(msg_id, -32603, str(e))

            else:
                if msg_id is not None:
                    return self._error(msg_id, -32601, f"Method not found: {method}")
                return None  # Unknown notification, ignore

        except Exception as e:
            logger.error(f"Request error: {e}", exc_info=True)
            if msg_id is not None:
                return self._error(msg_id, -32603, str(e))
            return None

    def _response(self, msg_id, result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _error(self, msg_id, code, message):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    async def run_stdio(self):
        """Run the MCP server using stdio transport."""
        logger.info(f"MCP Server '{self.name}' v{self.version} starting (stdio)")
        logger.info(f"Registered {len(self._tools)} tools, {len(self._resources)} resources")

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

        async def send(msg: dict):
            data = json.dumps(msg)
            line = data + "\n"
            writer.write(line.encode("utf-8"))
            await writer.drain()

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line = line.decode("utf-8").strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {line[:100]}")
                    continue

                response = await self._handle_request(msg)
                if response:
                    await send(response)

        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("MCP Server shutting down")
        except Exception as e:
            logger.error(f"MCP Server error: {e}", exc_info=True)
        finally:
            logger.info("MCP Server stopped")
