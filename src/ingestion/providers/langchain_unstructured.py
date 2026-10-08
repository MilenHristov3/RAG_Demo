"""
Option 2: PDF conversion via LangChain.

LangChain itself is an orchestration library, not a conversion API, so
"via LangChain" here means LangChain's own PDF loader that calls a
hosted API: langchain_community.document_loaders.UnstructuredAPIFileLoader,
which sends the PDF to Unstructured's hosted document-parsing API and
gets back structured elements (title, narrative text, list item,
table, ...) per page.

Required in .env:
    UNSTRUCTURED_API_KEY

Optional in .env:
    UNSTRUCTURED_API_URL   (defaults to Unstructured's public hosted API)

Missing key/package is raised as RuntimeError from __init__, same
convention as src/embeddings/providers/*.py — it surfaces as a clear
message when this provider is selected, not a traceback mid-batch.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.ingestion.base import ConversionProvider

DEFAULT_API_URL = "https://api.unstructuredapp.io/general/v0/general"


class LangChainConversionProvider(ConversionProvider):
    id = "langchain"
    label = "LangChain (PDF loader, via the Unstructured API)"

    def __init__(self) -> None:
        load_dotenv()

        self.api_key = os.getenv("UNSTRUCTURED_API_KEY")
        self.api_url = os.getenv("UNSTRUCTURED_API_URL", DEFAULT_API_URL)

        if not self.api_key:
            raise RuntimeError(
                "UNSTRUCTURED_API_KEY is not set. Add it to your .env file "
                "(copy .env.example to .env and fill it in). "
                "Get a key at: https://unstructured.io/api-key"
            )

        try:
            from langchain_community.document_loaders import (
                UnstructuredAPIFileLoader,
            )
        except ImportError as exc:
            raise RuntimeError(
                "The 'langchain-community' and 'unstructured-client' "
                "packages are required for this provider. Install them "
                "with: pip install langchain-community unstructured-client"
            ) from exc

        self._loader_cls = UnstructuredAPIFileLoader

    def convert(
        self,
        input_path: Path,
        markdown_path: Path,
        json_path: Path,
        links_path: Path,
    ) -> None:
        print(f"Reading PDF via LangChain (Unstructured API): {input_path}")

        loader = self._loader_cls(
            file_path=str(input_path),
            api_key=self.api_key,
            url=self.api_url,
            strategy="hi_res",
        )

        documents = loader.load()

        if not documents:
            raise RuntimeError(
                f"LangChain/Unstructured returned no content for {input_path}."
            )

        # UnstructuredAPIFileLoader returns one Document per element by
        # default (title, narrative text, list item, table, ...), each
        # with page_number in its metadata. Join them back in order,
        # one blank-line-separated block per element — downstream
        # steps (cleaner.py, structure.py) only need plain text with
        # paragraph breaks, not real Markdown markup.
        markdown_parts = [doc.page_content for doc in documents]
        markdown = "\n\n".join(
            part for part in markdown_parts if part and part.strip()
        )

        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")

        # Layout JSON: keep whatever structure Unstructured gave us
        # (element type, page number, coordinates if available) rather
        # than pymupdf4llm's own JSON shape — the two are not the same
        # format. Nothing downstream currently reads this file, same
        # role as provider 1's json_path: inspection/debugging only.
        elements = [
            {"text": doc.page_content, "metadata": doc.metadata}
            for doc in documents
        ]
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(elements, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Unstructured's API does not return link coordinates the way
        # PyMuPDF does (see pdf_parser.extract_links) — write an empty,
        # clearly-labelled file instead of silently omitting it, so
        # it's obvious this is a provider limitation, not a bug.
        links_path.parent.mkdir(parents=True, exist_ok=True)
        links_path.write_text(
            json.dumps(
                {
                    "note": (
                        "Link extraction is not available via the "
                        "LangChain/Unstructured conversion method."
                    ),
                    "links": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print(f"Markdown:  {markdown_path}")
        print(f"JSON:      {json_path}")
        print(f"Elements:  {len(documents)}")
        print("PDF conversion completed (LangChain / Unstructured API).")
