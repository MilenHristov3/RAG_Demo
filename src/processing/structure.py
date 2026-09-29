"""
Single entry point for the structuring step.

Picks the right structure extractor per document:

    legal   -> legal_structure.py   (Chapter / Article / Annex)
    generic -> generic_structure.py (sections, lists, tables)

Decision order:
  1. "structure_type": "legal" | "generic" in data/source/<stem>.meta.json
  2. "source_type" in the legal set below (regulation, directive, ...)
  3. Auto-detect: >= 3 "Article <n>" heading lines in the cleaned text
  4. Otherwise generic

Usage:
    python -m src.processing.structure --stem <name>
    python -m src.processing.structure --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.docmeta import (  # noqa: E402
    DocumentMetadata,
    list_source_stems,
    load_metadata,
)
from src.processing import generic_structure, legal_structure  # noqa: E402

EXTRACTED_DIR = Path("data/extracted")

LEGAL_SOURCE_TYPES = {
    "regulation",
    "directive",
    "decision",
    "legal",
    "law",
    "act",
}


def resolve_structure_type(
    metadata: DocumentMetadata,
    clean_md: Path,
) -> str:
    explicit = metadata.extra.get("structure_type")

    if explicit in {"legal", "generic"}:
        return explicit

    if (metadata.source_type or "").lower() in LEGAL_SOURCE_TYPES:
        return "legal"

    if clean_md.exists():
        text = clean_md.read_text(encoding="utf-8")
        article_lines = sum(
            1
            for line in text.splitlines()
            if legal_structure.ARTICLE_RE.match(
                legal_structure.clean_line(line)
            )
        )

        if article_lines >= 3:
            return "legal"

    return "generic"


def run_for_stem(stem: str, extracted_dir: Path = EXTRACTED_DIR) -> None:
    metadata = load_metadata(stem)
    clean_md = extracted_dir / f"{stem}.clean.md"

    structure_type = resolve_structure_type(metadata, clean_md)

    print(f"[{stem}] structure type: {structure_type}")

    if structure_type == "legal":
        legal_structure.run_for_stem(stem, extracted_dir)
    else:
        generic_structure.run_for_stem(stem, extracted_dir)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Structure a cleaned document (legal or generic)."
    )
    parser.add_argument("--stem", help="Document stem.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every document stem found in data/source/.",
    )
    parser.add_argument("--extracted-dir", default=str(EXTRACTED_DIR))
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    extracted_dir = Path(args.extracted_dir)

    if args.all:
        for stem in list_source_stems():
            run_for_stem(stem, extracted_dir)
    elif args.stem:
        run_for_stem(args.stem, extracted_dir)
    else:
        build_arg_parser().error("Provide --stem <name> or --all.")
