"""
Generic structure extraction for NON-legal documents
(product manuals, job descriptions, guides, reports, ...).

Counterpart of legal_structure.py: reads data/extracted/<stem>.clean.md
and writes data/extracted/<stem>.structure.json, using the same
{"instrument": ..., "elements": [...]} envelope so downstream steps
(chunker/embedder) can treat every document the same way.

Model
-----
Markdown headings (#, ##, ...) open *sections*. Each section holds
ordered *blocks*:

    {"type": "paragraph", "text": "..."}
    {"type": "list", "ordered": true|false, "items": ["...", ...]}
    {"type": "table", "kind": "key_value", "rows": [{"key": .., "value": ..}]}
    {"type": "table", "kind": "table", "columns": [..], "rows": [{col: val}]}

Tables are normalised because PDF->Markdown tables come in several
shapes (see parse_table). Every table row ends up self-contained, so a
chunker can turn one row into one retrievable record.

Usage:
    python -m src.processing.generic_structure --stem <name>
    python -m src.processing.generic_structure --all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.docmeta import (  # noqa: E402
    DocumentMetadata,
    list_source_stems,
    load_metadata,
)

EXTRACTED_DIR = Path("data/extracted")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
ORDERED_ITEM_RE = re.compile(r"^\d+[.)]\s+(.*\S)\s*$")
UNORDERED_ITEM_RE = re.compile(r"^[-*•·]\s+(.*\S)\s*$")
TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
PICTURE_TEXT_RE = re.compile(
    r"<!--\s*Start of picture text\s*-->.*?<!--\s*End of picture text\s*-->",
    re.DOTALL,
)


# ============================================================
# Text helpers
# ============================================================


def strip_markdown(text: str) -> str:
    """
    Remove inline Markdown/HTML noise from PDF extraction.

    PDF extractors often drop the spaces around bold runs
    ("shows**E0**and will", "cup —**maximum**"), so a bold run glued
    to neighbouring text gets a space instead of being fused to it.
    """

    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)

    def unbold(match: re.Match) -> str:
        before = text[match.start() - 1] if match.start() > 0 else ""
        after = text[match.end()] if match.end() < len(text) else ""

        prefix = " " if before and not before.isspace() and before not in "([{\"'" else ""
        suffix = " " if after and not after.isspace() and after not in ".,;:!?)]}\"'" else ""

        return f"{prefix}{match.group(1)}{suffix}"

    text = re.sub(r"\*\*(.+?)\*\*", unbold, text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def is_bold(cell: str) -> bool:
    cell = cell.strip()
    return len(cell) > 4 and cell.startswith("**") and cell.endswith("**")


# ============================================================
# Tables
# ============================================================


def parse_table(lines: list[str]) -> dict | None:
    """
    Normalise a Markdown table. Three shapes are recognised:

    1. Paired grid (e.g. a "button map"): bold label rows alternate
       with plain description rows, several labels per row.
       -> key_value, one row per (label, description).
    2. Key/value list: 2 columns, first column always bold. The
       extractor mislabels the first data row as a header; it is kept
       as data. -> key_value.
    3. Ordinary table with a real header row.
       -> table, columns + one dict per row.
    """

    rows: list[list[str]] = []

    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]

        if all(TABLE_SEPARATOR_CELL_RE.match(c) for c in cells):
            continue

        rows.append(cells)

    if not rows:
        return None

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    bold = [[is_bold(c) for c in r] for r in rows]

    paired = (
        len(rows) >= 2
        and len(rows) % 2 == 0
        and all(all(b) for b in bold[0::2])
        and not any(any(b) for b in bold[1::2])
    )

    if paired:
        records = []

        for r in range(0, len(rows), 2):
            for c in range(width):
                key = strip_markdown(rows[r][c])
                value = strip_markdown(rows[r + 1][c])

                if key:
                    records.append({"key": key, "value": value})

        return {"type": "table", "kind": "key_value", "rows": records}

    if width == 2 and all(b[0] for b in bold):
        records = [
            {
                "key": strip_markdown(r[0]),
                "value": strip_markdown(r[1]),
            }
            for r in rows
        ]

        return {"type": "table", "kind": "key_value", "rows": records}

    columns = []

    for index, cell in enumerate(rows[0], start=1):
        name = strip_markdown(cell) or f"col{index}"

        while name in columns:
            name = f"{name}_{index}"

        columns.append(name)

    records = [
        {col: strip_markdown(cell) for col, cell in zip(columns, r)}
        for r in rows[1:]
    ]

    return {
        "type": "table",
        "kind": "table",
        "columns": columns,
        "rows": records,
    }


# ============================================================
# Blocks (paragraphs, lists, tables) inside one section
# ============================================================


def parse_blocks(lines: list[str]) -> list[dict]:
    blocks: list[dict] = []
    paragraph: list[str] = []
    current_list: dict | None = None
    last_was_item = False
    index = 0

    def flush_paragraph() -> None:
        nonlocal paragraph

        if paragraph:
            text = strip_markdown(" ".join(paragraph))

            if text:
                blocks.append({"type": "paragraph", "text": text})

            paragraph = []

    def flush_list() -> None:
        nonlocal current_list

        if current_list and current_list["items"]:
            blocks.append(current_list)

        current_list = None

    while index < len(lines):
        line = lines[index].strip()

        if not line:
            flush_paragraph()
            last_was_item = False
            index += 1
            continue

        if line.startswith("|"):
            flush_paragraph()
            flush_list()
            last_was_item = False

            table_lines = []

            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1

            table = parse_table(table_lines)

            if table:
                blocks.append(table)

            continue

        ordered = ORDERED_ITEM_RE.match(line)
        unordered = UNORDERED_ITEM_RE.match(line)

        if ordered or unordered:
            flush_paragraph()

            is_ordered = bool(ordered)

            if current_list is None or current_list["ordered"] != is_ordered:
                flush_list()
                current_list = {
                    "type": "list",
                    "ordered": is_ordered,
                    "items": [],
                }

            item = (ordered or unordered).group(1)
            current_list["items"].append(strip_markdown(item))
            last_was_item = True
            index += 1
            continue

        if current_list is not None and last_was_item:
            # Wrapped continuation of the previous list item.
            current_list["items"][-1] = strip_markdown(
                current_list["items"][-1] + " " + line
            )
        else:
            flush_list()
            paragraph.append(line)

        index += 1

    flush_paragraph()
    flush_list()

    return blocks


# ============================================================
# Sections
# ============================================================


def parse_document(markdown: str, id_prefix: str) -> tuple[list[dict], int]:
    """
    Split Markdown into sections. Returns (elements, discarded_figures).

    Heading levels from PDF extractors are not always consistent, so the
    section path is built with a level stack: a heading pops every
    section at the same or a deeper level before being pushed.
    """

    markdown, discarded = PICTURE_TEXT_RE.subn("", markdown)

    sections: list[dict] = []
    stack: list[tuple[int, str]] = []
    current: dict | None = None
    body: list[str] = []

    def close_section() -> None:
        if current is None:
            return

        blocks = parse_blocks(body)

        if not blocks:
            return

        current["blocks"] = blocks

        for number, block in enumerate(blocks, start=1):
            block["id"] = f"{current['id']}.b{number}"

        sections.append(current)

    for line in markdown.splitlines():
        heading = HEADING_RE.match(line.strip())

        if heading:
            close_section()

            level = len(heading.group(1))
            title = strip_markdown(heading.group(2))

            while stack and stack[-1][0] >= level:
                stack.pop()

            stack.append((level, title))

            current = {
                "id": f"{id_prefix}:sec{len(sections) + 1}",
                "type": "section",
                "level": level,
                "title": title,
                "path": [t for _, t in stack],
            }
            body = []
            continue

        if current is None:
            # Text before any heading.
            current = {
                "id": f"{id_prefix}:sec{len(sections) + 1}",
                "type": "section",
                "level": 0,
                "title": "",
                "path": [],
            }
            body = []

        body.append(line)

    close_section()

    return sections, discarded


# ============================================================
# File handling
# ============================================================


def parse_structure_file(
    input_path: Path,
    output_path: Path,
    metadata: DocumentMetadata,
) -> None:
    markdown = input_path.read_text(encoding="utf-8")

    elements, discarded = parse_document(markdown, metadata.doc_id)

    output = {
        "instrument": metadata.as_instrument(),
        "structure_type": "generic",
        "elements": elements,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    block_count = sum(len(s["blocks"]) for s in elements)

    print(f"Input:   {input_path}")
    print(f"Output:  {output_path}")
    print(f"Doc ID:  {metadata.doc_id}")
    print(f"Sections: {len(elements)}  Blocks: {block_count}")

    if discarded:
        print(f"Discarded {discarded} image-text (OCR noise) block(s).")

    print("Generic structure extraction completed.")


def run_for_stem(stem: str, extracted_dir: Path = EXTRACTED_DIR) -> None:
    metadata = load_metadata(stem)

    input_path = extracted_dir / f"{stem}.clean.md"
    output_path = extracted_dir / f"{stem}.structure.json"

    if not input_path.exists():
        print(
            f"SKIP {stem}: no cleaned Markdown at {input_path} "
            "(run cleaner.py first)."
        )
        return

    parse_structure_file(input_path, output_path, metadata)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract sections, lists and tables from a cleaned "
            "non-legal Markdown document into structured JSON."
        )
    )
    parser.add_argument("--stem", help="Document stem, e.g. 'my_manual'.")
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
