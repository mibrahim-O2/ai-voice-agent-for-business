"""RAG over the local knowledge base: load, chunk, embed, store, retrieve with sources."""

from .documents import Chunk, Document, chunk_documents, load_documents
from .embeddings import EmbeddingError, LocalEmbedder, OpenAIEmbedder, make_embedder
from .index import VectorIndex
from .retriever import NOT_FOUND_MESSAGE, KnowledgeBase, KnowledgeBaseError

__all__ = [
    "NOT_FOUND_MESSAGE",
    "Chunk",
    "Document",
    "EmbeddingError",
    "KnowledgeBase",
    "KnowledgeBaseError",
    "LocalEmbedder",
    "OpenAIEmbedder",
    "VectorIndex",
    "chunk_documents",
    "load_documents",
    "make_embedder",
]
