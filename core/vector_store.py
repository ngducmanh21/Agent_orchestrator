"""Vector Store - Qdrant integration for codebase indexing."""
import logging
import time
from typing import List, Optional, Dict

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from core.config import Config

logger = logging.getLogger(__name__)


class VectorStore:
    """Manages vector storage in Qdrant for codebase indexing."""

    def __init__(self, config: Config):
        self.config = config
        self.client: Optional[QdrantClient] = None
        self.collection_name = config.collection_name
        self._connected = False

    async def connect(self, retries: int = 5, delay: float = 2.0) -> bool:
        """Connect to Qdrant with retry logic."""
        for attempt in range(retries):
            try:
                self.client = QdrantClient(
                    host=self.config.qdrant_host,
                    port=self.config.qdrant_port,
                    timeout=10,
                )
                # Test connection
                self.client.get_collections()
                self._connected = True
                logger.info(f"Connected to Qdrant at {self.config.qdrant_host}:{self.config.qdrant_port}")
                return True
            except Exception as e:
                logger.warning(f"Qdrant connection attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(delay)

        logger.error("Failed to connect to Qdrant after all retries")
        return False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.client is not None

    async def ensure_collection(self, repo_name: str) -> str:
        """Ensure a collection exists for the given repo."""
        collection = f"{self.collection_name}_{repo_name}".replace("-", "_").replace("/", "_")

        if not self.is_connected:
            raise RuntimeError("Not connected to Qdrant")

        try:
            self.client.get_collection(collection)
            logger.info(f"Collection '{collection}' already exists")
        except (UnexpectedResponse, Exception):
            logger.info(f"Creating collection '{collection}'")
            self.client.create_collection(
                collection_name=collection,
                vectors_config=qmodels.VectorParams(
                    size=self.config.embedding_dim,
                    distance=qmodels.Distance.COSINE,
                ),
            )

        self.collection_name = collection
        return collection

    async def upsert_file(
        self,
        file_id: int,
        file_path: str,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict] = None,
    ):
        """Upsert a file's embedding into Qdrant."""
        if not self.is_connected:
            raise RuntimeError("Not connected to Qdrant")

        payload = {
            "file_path": file_path,
            "content_preview": content[:2000],
            "content_length": len(content),
            "indexed_at": time.time(),
        }
        if metadata:
            payload.update(metadata)

        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                qmodels.PointStruct(
                    id=file_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )

    async def search_similar(
        self,
        query_embedding: List[float],
        limit: int = 10,
        score_threshold: float = 0.3,
    ) -> List[Dict]:
        """Search for similar files by embedding."""
        if not self.is_connected:
            return []

        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=limit,
                score_threshold=score_threshold,
            )

            return [
                {
                    "id": r.id,
                    "score": r.score,
                    "path": r.payload.get("file_path", ""),
                    "content": r.payload.get("content_preview", ""),
                    "metadata": r.payload,
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def get_all_indexed_files(self) -> List[Dict]:
        """Get all indexed files from collection."""
        if not self.is_connected:
            return []

        try:
            result = self.client.scroll(
                collection_name=self.collection_name,
                limit=10000,
                with_payload=True,
                with_vectors=False,
            )

            return [
                {
                    "id": point.id,
                    "path": point.payload.get("file_path", ""),
                    "content_length": point.payload.get("content_length", 0),
                    "indexed_at": point.payload.get("indexed_at", 0),
                    "priority_tag": point.payload.get("priority_tag", "OTHER"),
                    "insight": point.payload.get("insight", ""),
                }
                for point in result[0]
            ]
        except Exception as e:
            logger.error(f"Error getting indexed files: {e}")
            return []

    async def update_file_insight(self, file_id: int, insight: str):
        """Update a file's AI insight in Qdrant."""
        if not self.is_connected:
            return

        try:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"insight": insight},
                points=[file_id],
            )
        except Exception as e:
            logger.error(f"Error updating insight for file {file_id}: {e}")

    async def delete_collection(self, collection_name: Optional[str] = None):
        """Delete a collection."""
        if not self.is_connected:
            return

        name = collection_name or self.collection_name
        try:
            self.client.delete_collection(name)
            logger.info(f"Deleted collection '{name}'")
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")

    async def get_collection_info(self) -> Optional[Dict]:
        """Get collection info."""
        if not self.is_connected:
            return None

        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.value,
            }
        except Exception as e:
            logger.error(f"Error getting collection info: {e}")
            return None
