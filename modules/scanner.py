"""Codebase Scanner & Indexer - Scan files and index into Qdrant."""
import fnmatch
import logging
import os
from typing import AsyncGenerator, Callable, Dict, List, Optional, Tuple

from core.ai_provider import AIProvider
from core.config import Config
from core.state import AppState, FileInfo, ScanStatus
from core.vector_store import VectorStore

logger = logging.getLogger(__name__)


class Scanner:
    """Scans codebase and indexes files into Qdrant vector store."""

    def __init__(
        self,
        config: Config,
        state: AppState,
        ai_provider: AIProvider,
        vector_store: VectorStore,
    ):
        self.config = config
        self.state = state
        self.ai = ai_provider
        self.vector_store = vector_store

    def _should_ignore(self, path: str) -> bool:
        """Check if a path should be ignored."""
        basename = os.path.basename(path)
        for pattern in self.config.ignore_patterns:
            if fnmatch.fnmatch(basename, pattern):
                return True
            if fnmatch.fnmatch(path, f"*/{pattern}/*"):
                return True
            if fnmatch.fnmatch(path, f"*/{pattern}"):
                return True
        return False

    def _get_priority_tag(self, file_path: str, repo_root: str) -> str:
        """Determine priority tag for a file based on its location."""
        relative = os.path.relpath(file_path, repo_root)
        parts = relative.split(os.sep)

        for folder in self.state.repo.priority_folders or self.config.priority_folders:
            if folder in parts:
                return "CORE"

        # Check for common important patterns
        basename = os.path.basename(file_path).lower()
        important_names = [
            "app.", "main.", "index.", "server.", "config.",
            "routes.", "router.", "middleware.", "auth.",
            "database.", "db.", "schema.", "model.",
        ]
        for name in important_names:
            if basename.startswith(name):
                return "CORE"

        return "OTHER"

    def _is_supported_file(self, file_path: str) -> bool:
        """Check if file extension is supported."""
        _, ext = os.path.splitext(file_path)
        return ext.lower() in self.config.supported_extensions

    def _is_within_size_limit(self, file_path: str) -> bool:
        """Check if file is within size limit."""
        try:
            size = os.path.getsize(file_path)
            return size <= self.config.max_file_size_kb * 1024
        except OSError:
            return False

    def scan_directory(self, repo_path: str) -> List[FileInfo]:
        """Scan directory and collect all supported files."""
        files: List[FileInfo] = []

        for root, dirs, filenames in os.walk(repo_path):
            # Filter out ignored directories in-place
            dirs[:] = [d for d in dirs if not self._should_ignore(os.path.join(root, d))]

            for filename in filenames:
                file_path = os.path.join(root, filename)

                if self._should_ignore(file_path):
                    continue
                if not self._is_supported_file(file_path):
                    continue
                if not self._is_within_size_limit(file_path):
                    continue

                relative_path = os.path.relpath(file_path, repo_path)
                _, ext = os.path.splitext(file_path)

                file_info = FileInfo(
                    path=file_path,
                    relative_path=relative_path,
                    extension=ext,
                    size_bytes=os.path.getsize(file_path),
                    priority_tag=self._get_priority_tag(file_path, repo_path),
                )
                files.append(file_info)

        # Sort: CORE files first, then by path
        files.sort(key=lambda f: (0 if f.priority_tag == "CORE" else 1, f.relative_path))

        return files

    def read_file_content(self, file_path: str) -> Optional[str]:
        """Read file content safely."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            return None

    async def scan_and_index(
        self,
        on_progress: Optional[Callable] = None,
    ) -> int:
        """Scan codebase and index all files into Qdrant.
        
        Args:
            on_progress: Callback function(current, total, file_path) for progress updates
            
        Returns:
            Number of files indexed
        """
        repo_path = self.state.repo.local_path
        repo_name = self.state.repo.name

        if not repo_path or not os.path.exists(repo_path):
            raise RuntimeError("Repository not set up. Use /setup first.")

        # Update state
        self.state.repo.scan_status = ScanStatus.SCANNING
        self.state.stop_requested = False

        # Scan files
        files = self.scan_directory(repo_path)
        self.state.repo.total_files = len(files)

        priority_folders = self.state.repo.priority_folders or self.config.priority_folders
        logger.info(
            f"Found {len(files)} files. Priority folders: {priority_folders}. "
            f"Starting indexing..."
        )

        if on_progress:
            await on_progress(
                "scan_start",
                {
                    "total": len(files),
                    "priority_folders": priority_folders,
                },
            )

        # Ensure Qdrant collection exists
        await self.vector_store.ensure_collection(repo_name)

        # Index files
        self.state.repo.scan_status = ScanStatus.INDEXING
        indexed = 0

        for i, file_info in enumerate(files):
            if self.state.stop_requested:
                self.state.repo.scan_status = ScanStatus.STOPPED
                logger.info("Scan stopped by user")
                break

            self.state.repo.current_file = file_info.relative_path
            self.state.repo.scan_progress = (i + 1) / len(files) * 100

            # Read file content
            content = self.read_file_content(file_info.path)
            if content is None:
                continue

            # Generate embedding
            embedding = self.ai.get_simple_embedding(content)

            # Store in Qdrant
            try:
                await self.vector_store.upsert_file(
                    file_id=i + 1,
                    file_path=file_info.relative_path,
                    content=content,
                    embedding=embedding,
                    metadata={
                        "priority_tag": file_info.priority_tag,
                        "extension": file_info.extension,
                        "size_bytes": file_info.size_bytes,
                    },
                )
                file_info.indexed = True
                indexed += 1
            except Exception as e:
                logger.error(f"Error indexing {file_info.relative_path}: {e}")

            # Store in state
            self.state.repo.files[file_info.relative_path] = file_info
            self.state.repo.indexed_files = indexed

            if on_progress:
                await on_progress(
                    "file_indexed",
                    {
                        "current": i + 1,
                        "total": len(files),
                        "file": file_info.relative_path,
                        "priority": file_info.priority_tag,
                    },
                )

        if not self.state.stop_requested:
            self.state.repo.scan_status = ScanStatus.COMPLETED

        self.state.repo.estimated_cost = self.ai.estimated_cost

        if on_progress:
            await on_progress(
                "scan_complete",
                {"indexed": indexed, "total": len(files)},
            )

        return indexed

    async def generate_insights(
        self,
        on_progress: Optional[Callable] = None,
    ) -> int:
        """Generate AI insights for all indexed files."""
        self.state.repo.scan_status = ScanStatus.ANALYZING
        analyzed = 0

        files = list(self.state.repo.files.values())
        total = len(files)

        for i, file_info in enumerate(files):
            if self.state.stop_requested:
                break

            self.state.repo.current_file = file_info.relative_path

            content = self.read_file_content(file_info.path)
            if content is None:
                continue

            # Generate AI insight
            insight = await self.ai.analyze_file(
                file_info.relative_path,
                content,
                self.state.repo.name,
            )

            file_info.insight = insight
            file_info.indexed = True

            # Update insight in Qdrant
            file_id = list(self.state.repo.files.keys()).index(file_info.relative_path) + 1
            await self.vector_store.update_file_insight(file_id, insight)

            analyzed += 1
            self.state.repo.estimated_cost = self.ai.estimated_cost

            if on_progress:
                await on_progress(
                    "insight_generated",
                    {
                        "current": analyzed,
                        "total": total,
                        "file": file_info.relative_path,
                        "insight_preview": insight[:200],
                    },
                )

        return analyzed

    async def search_relevant_files(self, query: str, limit: int = 10) -> List[dict]:
        """Search for files relevant to a query using Qdrant."""
        query_embedding = self.ai.get_simple_embedding(query)
        results = await self.vector_store.search_similar(query_embedding, limit=limit)

        # Enrich results with full content
        enriched = []
        for r in results:
            file_path = os.path.join(self.state.repo.local_path, r["path"])
            content = self.read_file_content(file_path)
            if content:
                enriched.append({
                    "path": r["path"],
                    "content": content,
                    "score": r["score"],
                    "metadata": r["metadata"],
                })

        return enriched
