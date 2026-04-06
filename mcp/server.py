"""MCP Server - Expose coding agent tools to VS Code via Model Context Protocol.

This server runs as a stdio-based MCP server that VS Code (Cline/Cursor) can connect to.
It provides tools for:
- Reading/writing/editing/deleting files in indexed projects
- Semantic search on the knowledge base (Qdrant)
- AI-powered Q&A about the codebase
- Listing files and running commands
- Managing indexed projects
"""
import asyncio
import fnmatch
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

# Add parent dir to path so we can import core modules
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Import server_lib from same package (relative import when run as module,
# absolute when run directly)
try:
    from .server_lib import MCPServerLib
except ImportError:
    from server_lib import MCPServerLib

from core.config import Config
from core.ai_provider import AIProvider
from core.vector_store import VectorStore

logger = logging.getLogger(__name__)


class CodingAgentMCPServer:
    """MCP Server that acts as a coding agent with knowledge base."""

    def __init__(self):
        self.config = Config.from_env()
        self.ai = AIProvider(self.config)
        self.vector_store = VectorStore(self.config)
        self.server = MCPServerLib(
            name="agent-orchestrator",
            version="1.0.0",
            description="Internal Coding Agent - Knowledge Base + File Operations for VS Code",
        )
        self._setup_tools()
        self._setup_resources()

    def _get_repos_dir(self) -> str:
        """Get the repos directory path."""
        return self.config.repos_dir

    def _get_project_path(self, project_name: str) -> str:
        """Get full path for a project."""
        repos_dir = self._get_repos_dir()
        path = os.path.join(repos_dir, project_name)
        # Security: prevent path traversal
        real_path = os.path.realpath(path)
        real_repos = os.path.realpath(repos_dir)
        if not real_path.startswith(real_repos):
            raise ValueError(f"Invalid project name: {project_name}")
        return path

    def _list_projects(self) -> List[str]:
        """List all indexed projects."""
        repos_dir = self._get_repos_dir()
        if not os.path.exists(repos_dir):
            return []
        return [
            d for d in os.listdir(repos_dir)
            if os.path.isdir(os.path.join(repos_dir, d)) and not d.startswith(".")
        ]

    def _resolve_file_path(self, project_name: str, file_path: str) -> str:
        """Resolve and validate a file path within a project."""
        project_dir = self._get_project_path(project_name)
        full_path = os.path.join(project_dir, file_path)
        # Security: prevent path traversal
        real_path = os.path.realpath(full_path)
        real_project = os.path.realpath(project_dir)
        if not real_path.startswith(real_project):
            raise ValueError(f"Path traversal detected: {file_path}")
        return full_path

    # ==================== TOOL DEFINITIONS ====================

    def _setup_tools(self):
        """Register all available tools."""

        # --- Project Management ---
        @self.server.tool(
            name="list_projects",
            description="List all indexed projects in the knowledge base. Returns project names that can be used with other tools.",
        )
        async def list_projects() -> str:
            projects = self._list_projects()
            if not projects:
                return "No projects indexed yet. Use the Admin UI to setup and scan a project first."
            result = "📂 Indexed Projects:\n"
            for p in projects:
                project_path = self._get_project_path(p)
                file_count = sum(1 for _, _, files in os.walk(project_path) for _ in files)
                result += f"  - **{p}** ({file_count} files)\n"
            return result

        @self.server.tool(
            name="delete_project",
            description="Delete an indexed project and its data from the knowledge base.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project to delete",
                },
                "delete_vectors": {
                    "type": "boolean",
                    "description": "Also delete vector embeddings from Qdrant (default: true)",
                    "default": True,
                },
            },
        )
        async def delete_project(project_name: str, delete_vectors: bool = True) -> str:
            project_path = self._get_project_path(project_name)
            if not os.path.exists(project_path):
                return f"❌ Project '{project_name}' not found."

            # Delete files
            shutil.rmtree(project_path)

            # Delete vectors from Qdrant
            if delete_vectors:
                try:
                    connected = await self.vector_store.connect(retries=2)
                    if connected:
                        collection = f"codebase_{project_name}".replace("-", "_").replace("/", "_")
                        await self.vector_store.delete_collection(collection)
                except Exception as e:
                    logger.warning(f"Could not delete vectors: {e}")

            return f"✅ Project '{project_name}' deleted successfully."

        @self.server.tool(
            name="get_project_structure",
            description="Get the directory tree structure of a project. Useful for understanding the project layout before making changes.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum depth to traverse (default: 3)",
                    "default": 3,
                },
                "show_files": {
                    "type": "boolean",
                    "description": "Show files in addition to directories (default: true)",
                    "default": True,
                },
            },
        )
        async def get_project_structure(
            project_name: str, max_depth: int = 3, show_files: bool = True
        ) -> str:
            project_path = self._get_project_path(project_name)
            if not os.path.exists(project_path):
                return f"❌ Project '{project_name}' not found."

            ignore = {
                "node_modules", ".git", "__pycache__", ".venv", "venv",
                "dist", "build", ".next", ".nuxt", "vendor",
                ".idea", ".vscode", ".DS_Store",
            }

            lines = [f"📁 {project_name}/"]
            def _tree(path, prefix, depth):
                if depth > max_depth:
                    return
                try:
                    entries = sorted(os.listdir(path))
                except PermissionError:
                    return
                dirs = [e for e in entries if os.path.isdir(os.path.join(path, e)) and e not in ignore and not e.startswith(".")]
                files = [e for e in entries if os.path.isfile(os.path.join(path, e))] if show_files else []

                items = [(d, True) for d in dirs] + [(f, False) for f in files]
                for i, (name, is_dir) in enumerate(items):
                    is_last = i == len(items) - 1
                    connector = "└── " if is_last else "├── "
                    if is_dir:
                        lines.append(f"{prefix}{connector}📂 {name}/")
                        extension = "    " if is_last else "│   "
                        _tree(os.path.join(path, name), prefix + extension, depth + 1)
                    else:
                        lines.append(f"{prefix}{connector}{name}")

            _tree(project_path, "", 1)
            return "\n".join(lines[:500])  # Limit output

        # --- File Operations ---
        @self.server.tool(
            name="read_file",
            description="Read the contents of a file from an indexed project. Use this to examine code before making changes.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project",
                },
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file within the project",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line number (1-based, optional)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line number (1-based, inclusive, optional)",
                },
            },
        )
        async def read_file(
            project_name: str,
            file_path: str,
            start_line: int = None,
            end_line: int = None,
        ) -> str:
            full_path = self._resolve_file_path(project_name, file_path)
            if not os.path.exists(full_path):
                return f"❌ File not found: {file_path}"
            if not os.path.isfile(full_path):
                return f"❌ Not a file: {file_path}"

            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()

                if start_line or end_line:
                    start = max(1, start_line or 1) - 1
                    end = min(len(lines), end_line or len(lines))
                    selected = lines[start:end]
                    numbered = [f"{i+start+1:4d} | {line}" for i, line in enumerate(selected)]
                    header = f"📄 {file_path} (lines {start+1}-{end} of {len(lines)})\n"
                else:
                    numbered = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]
                    header = f"📄 {file_path} ({len(lines)} lines)\n"

                return header + "".join(numbered)
            except Exception as e:
                return f"❌ Error reading file: {e}"

        @self.server.tool(
            name="write_file",
            description="Write content to a file in the project. Creates the file if it doesn't exist, overwrites if it does. Creates parent directories automatically.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project",
                },
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file within the project",
                },
                "content": {
                    "type": "string",
                    "description": "Full content to write to the file",
                },
            },
        )
        async def write_file(project_name: str, file_path: str, content: str) -> str:
            full_path = self._resolve_file_path(project_name, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            existed = os.path.exists(full_path)

            try:
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                action = "Updated" if existed else "Created"
                return f"✅ {action}: {file_path} ({len(content)} bytes)"
            except Exception as e:
                return f"❌ Error writing file: {e}"

        @self.server.tool(
            name="edit_file",
            description="Edit a file using search/replace blocks. Each block finds exact text and replaces it. More precise than overwriting the whole file.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project",
                },
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file within the project",
                },
                "edits": {
                    "type": "array",
                    "description": "List of {search, replace} objects. Each 'search' string is found and replaced with 'replace' string.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "search": {"type": "string", "description": "Exact text to find"},
                            "replace": {"type": "string", "description": "Text to replace with"},
                        },
                    },
                },
            },
        )
        async def edit_file(project_name: str, file_path: str, edits: list) -> str:
            full_path = self._resolve_file_path(project_name, file_path)
            if not os.path.exists(full_path):
                return f"❌ File not found: {file_path}"

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()

                original = content
                applied = 0
                failed = []

                for i, edit in enumerate(edits):
                    search = edit.get("search", "")
                    replace = edit.get("replace", "")
                    if search in content:
                        content = content.replace(search, replace, 1)
                        applied += 1
                    else:
                        failed.append(i + 1)

                if applied > 0:
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(content)

                result = f"✅ Applied {applied}/{len(edits)} edits to {file_path}"
                if failed:
                    result += f"\n⚠️ Failed edits (search text not found): {failed}"
                return result
            except Exception as e:
                return f"❌ Error editing file: {e}"

        @self.server.tool(
            name="delete_file",
            description="Delete a file or empty directory from the project.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project",
                },
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file or directory to delete",
                },
            },
        )
        async def delete_file(project_name: str, file_path: str) -> str:
            full_path = self._resolve_file_path(project_name, file_path)
            if not os.path.exists(full_path):
                return f"❌ Not found: {file_path}"

            try:
                if os.path.isfile(full_path):
                    os.remove(full_path)
                    return f"✅ Deleted file: {file_path}"
                elif os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                    return f"✅ Deleted directory: {file_path}"
            except Exception as e:
                return f"❌ Error deleting: {e}"

        # --- Search & Intelligence ---
        @self.server.tool(
            name="search_codebase",
            description="Semantic search across the indexed knowledge base using Qdrant vector search. Finds files relevant to a natural language query.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project to search in",
                },
                "query": {
                    "type": "string",
                    "description": "Natural language search query (e.g., 'authentication logic', 'database models')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of results (default: 10)",
                    "default": 10,
                },
            },
        )
        async def search_codebase(project_name: str, query: str, limit: int = 10) -> str:
            try:
                connected = await self.vector_store.connect(retries=2)
                if not connected:
                    return "❌ Cannot connect to Qdrant. Make sure it's running."

                collection = f"codebase_{project_name}".replace("-", "_").replace("/", "_")
                self.vector_store.collection_name = collection

                query_embedding = self.ai.get_simple_embedding(query)
                results = await self.vector_store.search_similar(query_embedding, limit=limit)

                if not results:
                    return f"No results found for: '{query}'. Make sure the project is indexed via Admin UI."

                output = f"🔍 Search results for: '{query}'\n\n"
                for i, r in enumerate(results, 1):
                    output += f"**{i}. {r['path']}** (score: {r['score']:.3f})\n"
                    preview = r.get("content", "")[:200].replace("\n", " ")
                    output += f"   {preview}...\n\n"

                return output
            except Exception as e:
                return f"❌ Search error: {e}"

        @self.server.tool(
            name="grep_search",
            description="Search for a regex pattern across files in a project. Like grep but with context.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project",
                },
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "file_glob": {
                    "type": "string",
                    "description": "File glob pattern to filter (e.g., '*.py', '*.js'). Default: all files.",
                    "default": "*",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default: 50)",
                    "default": 50,
                },
            },
        )
        async def grep_search(
            project_name: str, pattern: str, file_glob: str = "*", max_results: int = 50
        ) -> str:
            project_path = self._get_project_path(project_name)
            if not os.path.exists(project_path):
                return f"❌ Project '{project_name}' not found."

            ignore_dirs = {
                "node_modules", ".git", "__pycache__", ".venv", "venv",
                "dist", "build", ".next", "vendor",
            }

            try:
                regex = re.compile(pattern)
            except re.error as e:
                return f"❌ Invalid regex: {e}"

            matches = []
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if d not in ignore_dirs]
                for fname in files:
                    if file_glob != "*" and not fnmatch.fnmatch(fname, file_glob):
                        continue
                    fpath = os.path.join(root, fname)
                    rel_path = os.path.relpath(fpath, project_path)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            for lineno, line in enumerate(f, 1):
                                if regex.search(line):
                                    matches.append((rel_path, lineno, line.rstrip()))
                                    if len(matches) >= max_results:
                                        break
                    except (PermissionError, IsADirectoryError):
                        continue
                    if len(matches) >= max_results:
                        break

            if not matches:
                return f"No matches found for pattern: '{pattern}'"

            output = f"🔍 Found {len(matches)} matches for `{pattern}`:\n\n"
            current_file = None
            for fpath, lineno, line in matches:
                if fpath != current_file:
                    current_file = fpath
                    output += f"\n**{fpath}**:\n"
                output += f"  {lineno:4d} | {line}\n"

            return output

        @self.server.tool(
            name="ask_about_code",
            description="Ask an AI question about the codebase. Uses semantic search to find relevant files, then answers using AI with that context.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project",
                },
                "question": {
                    "type": "string",
                    "description": "Question about the codebase (e.g., 'How does authentication work?')",
                },
            },
        )
        async def ask_about_code(project_name: str, question: str) -> str:
            try:
                connected = await self.vector_store.connect(retries=2)
                if not connected:
                    return "❌ Cannot connect to Qdrant."

                collection = f"codebase_{project_name}".replace("-", "_").replace("/", "_")
                self.vector_store.collection_name = collection

                # Semantic search for context
                query_embedding = self.ai.get_simple_embedding(question)
                results = await self.vector_store.search_similar(query_embedding, limit=10)

                if not results:
                    return "❌ No indexed data found. Index the project via Admin UI first."

                # Enrich with full file content
                project_path = self._get_project_path(project_name)
                context_files = []
                for r in results:
                    fpath = os.path.join(project_path, r["path"])
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        context_files.append({"path": r["path"], "content": content})
                    except Exception:
                        continue

                # Ask AI
                answer = await self.ai.ask_codebase(question, context_files)
                return answer
            except Exception as e:
                return f"❌ Error: {e}"

        # --- Terminal ---
        @self.server.tool(
            name="run_command",
            description="Run a shell command in the project directory. Use for build, test, lint, etc.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project (command runs in project root)",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30)",
                    "default": 30,
                },
            },
        )
        async def run_command(project_name: str, command: str, timeout: int = 30) -> str:
            project_path = self._get_project_path(project_name)
            if not os.path.exists(project_path):
                return f"❌ Project '{project_name}' not found."

            # Security: block dangerous commands
            dangerous = ["rm -rf /", "mkfs", "dd if=", ":(){:|:&};:"]
            for d in dangerous:
                if d in command:
                    return f"❌ Blocked dangerous command: {command}"

            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                output = ""
                if result.stdout:
                    output += f"**stdout:**\n```\n{result.stdout[-5000:]}\n```\n"
                if result.stderr:
                    output += f"**stderr:**\n```\n{result.stderr[-2000:]}\n```\n"
                output += f"\n**Exit code:** {result.returncode}"
                return output or "Command completed with no output."
            except subprocess.TimeoutExpired:
                return f"❌ Command timed out after {timeout}s"
            except Exception as e:
                return f"❌ Error: {e}"

        # --- List files with filtering ---
        @self.server.tool(
            name="list_files",
            description="List files in a project directory with optional filtering.",
            parameters={
                "project_name": {
                    "type": "string",
                    "description": "Name of the project",
                },
                "directory": {
                    "type": "string",
                    "description": "Relative directory path (default: project root)",
                    "default": ".",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '*.py')",
                    "default": "*",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "List recursively (default: false)",
                    "default": False,
                },
            },
        )
        async def list_files(
            project_name: str,
            directory: str = ".",
            pattern: str = "*",
            recursive: bool = False,
        ) -> str:
            full_dir = self._resolve_file_path(project_name, directory)
            if not os.path.exists(full_dir):
                return f"❌ Directory not found: {directory}"
            if not os.path.isdir(full_dir):
                return f"❌ Not a directory: {directory}"

            ignore_dirs = {
                "node_modules", ".git", "__pycache__", ".venv", "venv",
                "dist", "build",
            }

            files = []
            if recursive:
                for root, dirs, filenames in os.walk(full_dir):
                    dirs[:] = [d for d in dirs if d not in ignore_dirs]
                    for fname in filenames:
                        if fnmatch.fnmatch(fname, pattern):
                            rel = os.path.relpath(os.path.join(root, fname), self._get_project_path(project_name))
                            files.append(rel)
            else:
                for entry in sorted(os.listdir(full_dir)):
                    full_entry = os.path.join(full_dir, entry)
                    if os.path.isdir(full_entry) and entry not in ignore_dirs:
                        files.append(f"📂 {entry}/")
                    elif os.path.isfile(full_entry) and fnmatch.fnmatch(entry, pattern):
                        size = os.path.getsize(full_entry)
                        files.append(f"   {entry} ({size:,} bytes)")

            if not files:
                return f"No files found matching pattern '{pattern}' in {directory}"

            output = f"📂 {project_name}/{directory} ({len(files)} items):\n"
            output += "\n".join(files[:200])
            return output

    # ==================== RESOURCE DEFINITIONS ====================

    def _setup_resources(self):
        """Register MCP resources (read-only data sources)."""

        @self.server.resource(
            uri="orchestrator://projects",
            name="Indexed Projects",
            description="List of all indexed projects in the knowledge base",
        )
        async def projects_resource() -> str:
            projects = self._list_projects()
            return json.dumps({"projects": projects}, indent=2)

        @self.server.resource(
            uri="orchestrator://status",
            name="System Status",
            description="Current status of the Agent Orchestrator",
        )
        async def status_resource() -> str:
            projects = self._list_projects()
            qdrant_ok = False
            try:
                qdrant_ok = await self.vector_store.connect(retries=1)
            except Exception:
                pass

            return json.dumps({
                "projects": projects,
                "project_count": len(projects),
                "qdrant_connected": qdrant_ok,
                "ai_available": self.ai.is_available,
                "ai_model": self.config.ai_model,
            }, indent=2)

    async def run(self):
        """Run the MCP server (stdio transport)."""
        await self.server.run_stdio()


def main():
    """Entry point for MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # MCP uses stdout for protocol, logs go to stderr
    )
    server = CodingAgentMCPServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
