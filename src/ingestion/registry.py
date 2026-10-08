"""
The list of PDF conversion providers offered to the user, in the order
they're displayed. Mirrors src/embeddings/registry.py's pattern: each
entry is a lightweight spec, not the provider itself — the actual
class (and its imports: pymupdf, langchain_community, ...) is only
loaded when that provider is selected, via `factory()`. This means
picking "pymupdf" doesn't require langchain_community to be installed,
and vice versa, and an unimplemented placeholder option doesn't need
any package at all.

To add a real implementation for option 3/4/5 later: write a new class
in providers/ (copy providers/langchain_unstructured.py as a
template), then replace that option's `factory` below with one that
imports and returns it — nothing else in this file, converter.py, or
the CLI needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.ingestion.base import ConversionProvider


@dataclass
class ProviderSpec:
    id: str
    label: str
    factory: Callable[[], "ConversionProvider"]
    implemented: bool = True


def _load_pymupdf() -> "ConversionProvider":
    from src.ingestion.providers.pymupdf_direct import PyMuPDFConversionProvider

    return PyMuPDFConversionProvider()


def _load_langchain() -> "ConversionProvider":
    from src.ingestion.providers.langchain_unstructured import (
        LangChainConversionProvider,
    )

    return LangChainConversionProvider()


def _load_placeholder(number: int) -> Callable[[], "ConversionProvider"]:
    def factory() -> "ConversionProvider":
        from src.ingestion.providers.placeholder import PlaceholderConversionProvider

        return PlaceholderConversionProvider(number)

    return factory


PROVIDERS: list[ProviderSpec] = [
    ProviderSpec(
        id="pymupdf",
        label="Current solution (PyMuPDF / PyMuPDF4LLM, local, no API key)",
        factory=_load_pymupdf,
    ),
    ProviderSpec(
        id="langchain",
        label="LangChain (PDF loader, via the Unstructured API)",
        factory=_load_langchain,
    ),
    ProviderSpec(
        id="option3",
        label="Option 3 — not yet specified",
        factory=_load_placeholder(3),
        implemented=False,
    ),
    ProviderSpec(
        id="option4",
        label="Option 4 — not yet specified",
        factory=_load_placeholder(4),
        implemented=False,
    ),
    ProviderSpec(
        id="option5",
        label="Option 5 — not yet specified",
        factory=_load_placeholder(5),
        implemented=False,
    ),
]


def get_provider_spec(provider_id: str) -> ProviderSpec:
    for spec in PROVIDERS:
        if spec.id == provider_id:
            return spec

    known = ", ".join(p.id for p in PROVIDERS)
    raise ValueError(f"Unknown provider '{provider_id}'. Known providers: {known}")
