"""Shared document retrieval primitives for grounded product experiences."""

from .store import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_INDEX_VERSION,
    DocumentChunkHit,
    DocumentChunkMetadata,
    DocumentChunkRecord,
    VersionFaissIndex,
    build_notice_version_records,
    create_openai_embeddings,
    version_index_directory,
)

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_INDEX_VERSION",
    "DocumentChunkHit",
    "DocumentChunkMetadata",
    "DocumentChunkRecord",
    "VersionFaissIndex",
    "build_notice_version_records",
    "create_openai_embeddings",
    "version_index_directory",
]
