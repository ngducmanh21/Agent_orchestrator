"""Configuration management for the Agent Orchestrator."""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """Application configuration."""
    # AI Provider
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    ai_model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096

    # Server
    host: str = "0.0.0.0"
    port: int = 8888

    # Qdrant
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    collection_name: str = "codebase"
    embedding_dim: int = 1024  # Voyage/Claude embedding dimension

    # Paths
    data_dir: str = "/app/data"
    repos_dir: str = "/app/data/repos"
    indexes_dir: str = "/app/data/indexes"

    # Scanning
    priority_folders: list = field(default_factory=lambda: [
        "src", "core", "components", "lib", "domain"
    ])
    ignore_patterns: list = field(default_factory=lambda: [
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        "dist", "build", ".next", ".nuxt", "vendor",
        "*.min.js", "*.min.css", "*.map", "*.lock",
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    ])
    max_file_size_kb: int = 500
    supported_extensions: list = field(default_factory=lambda: [
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
        ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".hpp",
        ".vue", ".svelte", ".html", ".css", ".scss", ".sass",
        ".json", ".yaml", ".yml", ".toml", ".xml",
        ".sql", ".graphql", ".proto", ".md",
        ".sh", ".bash", ".zsh", ".dockerfile",
    ])

    @classmethod
    def from_env(cls) -> "Config":
        """Create config from environment variables."""
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
            ai_model=os.getenv("AI_MODEL", "claude-sonnet-4-20250514"),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8888")),
            qdrant_host=os.getenv("QDRANT_HOST", "qdrant"),
            qdrant_port=int(os.getenv("QDRANT_PORT", "6333")),
            data_dir=os.getenv("DATA_DIR", "/app/data"),
            repos_dir=os.getenv("REPOS_DIR", "/app/data/repos"),
            indexes_dir=os.getenv("INDEXES_DIR", "/app/data/indexes"),
        )
