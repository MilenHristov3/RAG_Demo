"""
Turn any *.structure.json (legal or generic — both now share the same
"elements[].blocks[]" shape, see legal_structure.py / generic_structure.py)
into flat, retrieval-sized chunks.

One chunk per block, except:
  - a "table" block's rows are split one chunk per row (a row is
    usually the natural retrieval unit, e.g. one button, one line item).
  - consecutive short "paragraph"/"list" blocks in the same element are
    merged up to --max-chars, so a run of one-line paragraphs doesn't
    each become a tiny, low-context chunk.

Every chunk carries citation metadata: doc_id, title, element id/type/
number/title, and (for generic elements) the section path — enough to
point a user back to "AI Act, Article 5" or "Nuvita manual, Cleaning +
Safety > Deep cleaning" regardless of which parser produced it.

Usage:
    python -m src.processing.chunker --stem <name>
    python -m src.processing.chunker --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.docmeta import list_source_stems  # noqa: E402

EXTRACTED_DIR = Path("data/extracted")
MAX_CHARS = 1200


def table_row_to_text(row: dict) -> str:
    if "key" in row and "value" in row:
        return f"{row['key']}: {row['value']}"

    return "; ".join(f"{k}: {v}" for k, v in row.items() if v)


def block_to_text(block: dict) -> str | None:
    if block["type"] == "paragraph":
        return block.get("text") or None

    if block["type"] == "list":
        marker = "-" if not block.get("ordered") else None
        lines = [
            f"{marker} {item}" if marker else item
            for item in block.get("items", [])
        ]
        return "\n".join(lines) if lines else None

    return None  # tables are handled row-by-row in chunk_element()


def chunk_element(element: dict, instrument: dict) -> list[dict]:
    # instrument (structure.json's top-level "instrument" block) never
    # carries doc_id itself (see DocumentMetadata.as_instrument()) — it's
    # only baked into every element/block id as the prefix before ":".
    doc_id = element["id"].split(":", 1)[0]

    base_meta = {
        "doc_id": doc_id,
        "doc_title": instrument.get("title"),
        "element_id": element["id"],
        "element_type": element.get("type", "section"),
        "element_number": element.get("number"),
        "element_title": element.get("title"),
    }

    if element.get("path"):
        base_meta["section_path"] = element["path"]

    if element.get("chapter"):
        base_meta["chapter"] = element["chapter"]

    chunks: list[dict] = []
    buffer_text: list[str] = []
    buffer_ids: list[str] = []

    def flush() -> None:
        if not buffer_text:
            return

        text = "\n\n".join(buffer_text)
        chunks.append(
            {
                **base_meta,
                "chunk_id": f"{element['id']}#{len(chunks) + 1}",
                "block_ids": list(buffer_ids),
                "text": text,
            }
        )
        buffer_text.clear()
        buffer_ids.clear()

    for block in element.get("blocks", []):
        if block["type"] == "table":
            flush()

            for row_index, row in enumerate(block.get("rows", []), start=1):
                row_text = table_row_to_text(row)

                if not row_text:
                    continue

                chunks.append(
                    {
                        **base_meta,
                        "chunk_id": f"{block['id']}.r{row_index}",
                        "block_ids": [block["id"]],
                        "text": row_text,
                    }
                )

            continue

        text = block_to_text(block)

        if not text:
            continue

        current_len = sum(len(t) for t in buffer_text)

        if buffer_text and current_len + len(text) > MAX_CHARS:
            flush()

        buffer_text.append(text)
        buffer_ids.append(block["id"])

    flush()

    return chunks


def chunk_structure_file(input_path: Path, output_path: Path) -> int:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    instrument = data.get("instrument", {})

    chunks = []

    for element in data.get("elements", []):
        chunks.extend(chunk_element(element, instrument))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks),
        encoding="utf-8",
    )

    return len(chunks)


def run_for_stem(stem: str, extracted_dir: Path = EXTRACTED_DIR) -> None:
    input_path = extracted_dir / f"{stem}.structure.json"
    output_path = extracted_dir / f"{stem}.chunks.jsonl"

    if not input_path.exists():
        print(
            f"SKIP {stem}: no structure file at {input_path} "
            "(run structure.py first)."
        )
        return

    count = chunk_structure_file(input_path, output_path)

    print(f"Input:   {input_path}")
    print(f"Output:  {output_path}")
    print(f"Chunks:  {count}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chunk a structured document (legal or generic) for retrieval."
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
