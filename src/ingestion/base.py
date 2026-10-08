"""
Common interface every PDF conversion provider implements, so
converter.py can call any of them the same way without knowing which
tool/API is actually behind it.

Mirrors src/embeddings/base.py's EmbeddingProvider — same project,
same pattern, for the same reason: a user-selectable method with a
menu, a registry, and .env-driven setup.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ConversionProvider(ABC):
    """
    A provider converts one PDF into Markdown (+ optionally layout
    JSON and link metadata).

    Subclasses do their setup (reading .env, creating an API client)
    in __init__, and should raise a clear, actionable RuntimeError
    there if something required is missing (an API key, a package) —
    see providers/langchain_unstructured.py for the expected style.
    That way the error surfaces when the user picks that provider, not
    as a cryptic exception mid-batch.
    """

    id: str
    label: str

    @abstractmethod
    def convert(
        self,
        input_path: Path,
        markdown_path: Path,
        json_path: Path,
        links_path: Path,
    ) -> None:
        """Write markdown_path (required), and json_path/links_path if
        this provider is able to produce them."""
