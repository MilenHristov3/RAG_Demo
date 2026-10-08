"""
Option 1: the project's original PDF conversion — PyMuPDF +
PyMuPDF4LLM, running locally, no API key or network access needed.

This is a thin wrapper: src/ingestion/pdf_parser.py is unchanged, so
anyone calling convert_pdf() directly keeps working exactly as before.
"""

from __future__ import annotations

from pathlib import Path

from src.ingestion.base import ConversionProvider
from src.ingestion.pdf_parser import convert_pdf


class PyMuPDFConversionProvider(ConversionProvider):
    id = "pymupdf"
    label = "Current solution (PyMuPDF / PyMuPDF4LLM)"

    def convert(
        self,
        input_path: Path,
        markdown_path: Path,
        json_path: Path,
        links_path: Path,
    ) -> None:
        convert_pdf(
            input_path=input_path,
            markdown_path=markdown_path,
            json_path=json_path,
            links_path=links_path,
        )
