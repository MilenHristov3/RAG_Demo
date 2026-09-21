from pathlib import Path

from .pdf_parser import convert_pdf

SOURCE_DIR = Path("data/source")
OUTPUT_DIR = Path("data/extracted")


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


def main():
    file_type = choose_file_type()

    if file_type in ("", "exit"):
        print("Exiting.")
        return

    input_path = choose_file(file_type)

    if input_path is None:
        return

    print()
    print(f"Selected: {input_path}")

    if file_type == "pdf":
        convert_pdf_file(input_path)

    else:
        print(f"\n{file_type.upper()} parser is not implemented yet.")
        print("We'll add it next.")


if __name__ == "__main__":
    main()
