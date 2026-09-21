from pathlib import Path

import pymupdf

PDF_PATH = Path("data/eli_reg_2024_1689_oj_EN_TXT.pdf")
OUTPUT_PATH = Path("data/extracted.txt")


def extract_text(pdf_path: Path) -> str:
    """Extract text from every page of the PDF."""

    with pymupdf.open(pdf_path) as document:
        pages = []

        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text", sort=True)

            pages.append(f"\n--- PAGE {page_number} ---\n{text}")

    return "\n".join(pages)


def main():
    text = extract_text(PDF_PATH)

    OUTPUT_PATH.write_text(text, encoding="utf-8")

    print(f"Extracted text saved to: {OUTPUT_PATH}")
    print(f"Characters extracted: {len(text):,}")


if __name__ == "__main__":
    main()
