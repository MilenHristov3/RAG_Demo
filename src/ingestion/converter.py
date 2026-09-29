import argparse
import sys
from pathlib import Path

from .pdf_parser import convert_pdf

# Allow `python src/ingestion/converter.py` to import the shared
# metadata helper even when run as a loose script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.docmeta import list_source_stems, meta_path  # noqa: E402

SOURCE_DIR = Path("data/source")
OUTPUT_DIR = Path("data/extracted")

SUPPORTED_TYPES = {"pdf", "html", "txt", "docx", "xml"}


def choose_file_type() -> str:
    print()
    print("Select input file type:")
    print("1. PDF")
    print("2. HTML")
    print("3. TXT")
    print("4. DOCX")
    print("5. XML")
    print("0. Exit")
    print()

    choice = input("Enter choice: ").strip()

    file_types = {
        "1": "pdf",
        "2": "html",
        "3": "txt",
        "4": "docx",
        "5": "xml",
        "0": "exit",
    }

    return file_types.get(choice, "")


def choose_file(extension: str) -> Path | None:
    files = sorted(SOURCE_DIR.glob(f"*.{extension}"))

    if not files:
        print(f"\nNo .{extension} files found in " f"{SOURCE_DIR}/")
        return None

    print()
    print(f"Available {extension.upper()} files:")

    for index, file in enumerate(files, start=1):
        print(f"{index}. {file.name}")

    print()

    choice = input("Select file: ").strip()

    try:
        index = int(choice) - 1
        return files[index]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return None


def convert_pdf_file(input_path: Path) -> None:
    stem = input_path.stem

    markdown_path = OUTPUT_DIR / f"{stem}.md"
    json_path = OUTPUT_DIR / f"{stem}.json"
    links_path = OUTPUT_DIR / f"{stem}.links.json"

    convert_pdf(
        input_path=input_path,
        markdown_path=markdown_path,
        json_path=json_path,
        links_path=links_path,
    )

    warn_if_no_metadata(input_path.stem)


def warn_if_no_metadata(stem: str) -> None:
    """
    Remind the user to add data/source/<stem>.meta.json.

    Without it, downstream steps (legal_structure.py) fall back to a
    placeholder doc_id derived from the filename, which works but is
    not a citable, stable identifier.
    """

    path = meta_path(stem)

    if not path.exists():
        print()
        print(
            f"NOTE: no metadata file at {path}. "
            "Create it (doc_id, title, celex, source_url, ...) before "
            "running structure.py — see src/common/docmeta.py."
        )


def convert_file_by_type(input_path: Path, file_type: str) -> None:
    if file_type == "pdf":
        convert_pdf_file(input_path)
    else:
        print(f"\n{file_type.upper()} parser is not implemented yet.")
        print("We'll add it next.")


def run_batch() -> None:
    """Convert every supported source file in data/source/."""

    stems = list_source_stems()

    if not stems:
        print("No documents found in data/source/.")
        return

    for stem in stems:
        matches = [
            f
            for f in SOURCE_DIR.glob(f"{stem}.*")
            if f.suffix.lstrip(".").lower() in SUPPORTED_TYPES
        ]

        if not matches:
            print(f"SKIP {stem}: no supported source file (.pdf/.html/.txt/.docx/.xml).")
            continue

        input_path = matches[0]
        file_type = input_path.suffix.lstrip(".").lower()

        print()
        print(f"Converting: {input_path}")

        convert_file_by_type(input_path, file_type)


def run_interactive() -> None:
    file_type = choose_file_type()

    if file_type in ("", "exit"):
        print("Exiting.")
        return

    input_path = choose_file(file_type)

    if input_path is None:
        return

    print()
    print(f"Selected: {input_path}")

    convert_file_by_type(input_path, file_type)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a raw source document into Markdown/JSON. "
            "Runs interactively when no arguments are given."
        )
    )

    parser.add_argument(
        "--file",
        help="Path to a single file under data/source/ to convert (non-interactive).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Convert every supported file found in data/source/.",
    )

    return parser


def main():
    args = build_arg_parser().parse_args()

    if args.all:
        run_batch()
    elif args.file:
        input_path = Path(args.file)

        if not input_path.exists():
            print(f"ERROR: file not found: {input_path}")
            return

        file_type = input_path.suffix.lstrip(".").lower()
        convert_file_by_type(input_path, file_type)
    else:
        run_interactive()


if __name__ == "__main__":
    main()
