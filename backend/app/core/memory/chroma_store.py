"""Vector memory for semantic recall using ChromaDB."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import Settings

logger = logging.getLogger(__name__)


class ChromaMemory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: chromadb.PersistentClient | None = None
        self._collection = None

    def init(self) -> None:
        path = str(self._settings.chroma_persist)
        self._settings.chroma_persist.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="jarvis_memory",
            metadata={"hnsw:space": "cosine"},
        )

    def add_text(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        if not self._collection:
            self.init()
        assert self._collection is not None
        doc_id = str(uuid.uuid4())
        meta = metadata or {}
        self._collection.add(documents=[text], metadatas=[meta], ids=[doc_id])
        return doc_id

    def query(self, text: str, n: int = 5) -> list[dict[str, Any]]:
        if not self._collection:
            self.init()
        assert self._collection is not None
        res = self._collection.query(query_texts=[text], n_results=n)
        out: list[dict[str, Any]] = []
        docs = res.get("documents") or [[]]
        metas = res.get("metadatas") or [[]]
        dists = res.get("distances") or [[]]
        for i, doc in enumerate(docs[0]):
            out.append(
                {
                    "text": doc,
                    "metadata": metas[0][i] if metas and metas[0] else {},
                    "distance": dists[0][i] if dists and dists[0] else None,
                }
            )
        return out
