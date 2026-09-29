import argparse
import sys
from pathlib import Path
import re

# Allow `python src/processing/cleaner.py` to import the shared
# metadata helper even when run as a loose script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.docmeta import list_source_stems  # noqa: E402

EXTRACTED_DIR = Path("data/extracted")


def normalize_unicode_whitespace(text: str) -> str:
    """
    Normalize common Unicode whitespace characters.

    We intentionally do not modify legal punctuation or wording.
    """

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Non-breaking space
    text = text.replace("\u00a0", " ")

    # Thin space
    text = text.replace("\u2009", " ")

    # Hair space
    text = text.replace("\u200a", " ")

    # Narrow no-break space
    text = text.replace("\u202f", " ")

    return text


def normalize_line_whitespace(text: str) -> str:
    """
    Remove unnecessary whitespace at the end of lines
    while preserving line structure.
    """

    lines = text.splitlines()

    lines = [line.rstrip() for line in lines]

    return "\n".join(lines)


def normalize_superscripts(text: str) -> str:
    """
    Convert HTML superscript tags to their text content.

    Example:

        <sup>8</sup>

    becomes:

        8

    The PDF link itself is preserved separately in links.json.
    """

    return re.sub(
        r"<sup>\s*(.*?)\s*</sup>",
        r"\1",
        text,
        flags=re.DOTALL,
    )


def remove_empty_markdown_lines(text: str) -> str:
    """
    Remove lines containing only empty Markdown markers.
    """

    lines = text.splitlines()

    cleaned = []

    for line in lines:

        stripped = line.strip()

        if stripped in {
            "**",
            "__",
            "*",
            "_",
        }:
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


def collapse_excessive_blank_lines(text: str) -> str:
    """
    Replace 3+ consecutive blank lines with one blank line.
    """

    return re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )


def clean_markdown(text: str) -> str:
    """
    Main Markdown cleaning pipeline.

    Important:
    This function is intentionally conservative.

    It should NOT:
        - remove legal numbering
        - change article numbers
        - change paragraph numbers
        - remove legal references
        - split legal points
        - detect chapters/articles/annexes

    Those tasks belong to legal_structure.py.
    """

    text = normalize_unicode_whitespace(text)

    text = normalize_line_whitespace(text)

    text = normalize_superscripts(text)

    text = remove_empty_markdown_lines(text)

    text = collapse_excessive_blank_lines(text)

    return text.strip()


def clean_markdown_file(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Read raw Markdown, clean it, and save a separate file.
    """

    text = input_path.read_text(encoding="utf-8")

    cleaned_text = clean_markdown(text)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        cleaned_text,
        encoding="utf-8",
    )

    print(f"Input:   {input_path}")
    print(f"Output:  {output_path}")
    print("Cleaning completed.")


def run_for_stem(stem: str, extracted_dir: Path = EXTRACTED_DIR) -> None:
    """Clean the raw Markdown for a single document stem."""

    input_path = extracted_dir / f"{stem}.md"
    output_path = extracted_dir / f"{stem}.clean.md"

    if not input_path.exists():
        print(
            f"SKIP {stem}: no extracted Markdown at {input_path} "
            "(run converter.py / pdf_parser.py first)."
        )
        return

    clean_markdown_file(
        input_path=input_path,
        output_path=output_path,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Conservatively clean raw extracted Markdown."
    )

    parser.add_argument(
        "--stem",
        help=(
            "Document stem, e.g. 'eli_reg_2024_1689_oj_EN_TXT'. "
            "Reads data/extracted/<stem>.md, "
            "writes data/extracted/<stem>.clean.md."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every document stem found in data/source/.",
    )
    parser.add_argument(
        "--extracted-dir",
        default=str(EXTRACTED_DIR),
        help="Directory holding *.md input / *.clean.md output.",
    )

    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    extracted_dir = Path(args.extracted_dir)

    if args.all:
        stems = list_source_stems()

        if not stems:
            print("No documents found in data/source/.")

        for stem in stems:
            run_for_stem(stem, extracted_dir)

    elif args.stem:
        run_for_stem(args.stem, extracted_dir)

    else:
        build_arg_parser().error("Provide --stem <name> or --all.")
