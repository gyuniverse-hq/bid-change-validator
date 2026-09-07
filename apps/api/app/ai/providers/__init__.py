"""Runtime provider adapters for the AI integration package.

Providers are intentionally isolated from Backend services/configuration. Importing
this package must not require an external SDK; concrete providers use lazy imports
when an actual network call is made.
"""

from .embeddings import Embedder, OpenAIEmbedder, ngram_vectors, similarity_matrix
from .openai import OpenAINarrator, OpenAIStructuredExtractor

__all__ = [
    "OpenAIStructuredExtractor",
    "OpenAINarrator",
    "OpenAIEmbedder",
    "Embedder",
    "ngram_vectors",
    "similarity_matrix",
]
