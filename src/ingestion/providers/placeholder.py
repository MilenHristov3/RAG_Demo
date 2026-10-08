"""
Stands in for conversion options 3-5 until they're specified. It's
listed in the menu (so the user can see the slot exists) but raises a
clear error if actually selected, rather than silently doing nothing
or crashing with an unrelated traceback.
"""

from __future__ import annotations

from pathlib import Path

from src.ingestion.base import ConversionProvider


class PlaceholderConversionProvider(ConversionProvider):
    def __init__(self, number: int) -> None:
        self.id = f"option{number}"
        self.label = f"Option {number} — not yet specified"

    def convert(
        self,
        input_path: Path,
        markdown_path: Path,
        json_path: Path,
        links_path: Path,
    ) -> None:
        raise NotImplementedError(
            f"{self.label} has no implementation yet. Say which PDF "
            "conversion tool/API this option should use, and it'll be "
            "added the same way as 'pymupdf' and 'langchain' (a new "
            "file in src/ingestion/providers/, registered in "
            "src/ingestion/registry.py)."
        )
