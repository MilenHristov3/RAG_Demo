from pathlib import Path
import json
import re

"""legal_structure.py produce structured legal units, but not chunk them yet."""

# Regular expressions


CHAPTER_RE = re.compile(
    r"^CHAPTER\s+([IVXLCDM]+)\s*$",
    re.IGNORECASE,
)

ARTICLE_RE = re.compile(
    r"^Article\s+(\d+[a-zA-Z]?)\s*$",
    re.IGNORECASE,
)

PARAGRAPH_RE = re.compile(
    r"^(\d+)\.\s*(.*)$"
)

POINT_RE = re.compile(
    r"^\(([a-z]+)\)\s*(.*)$"
)

SUBPOINT_RE = re.compile(
    r"^\(([ivxlcdm]+)\)\s*(.*)$",
    re.IGNORECASE,
)



# Helpers


def clean_line(line: str) -> str:
    """
    Remove Markdown formatting that can interfere with legal structure
    detection.

    Examples:

        "# Article 1"          -> "Article 1"
        "## **GENERAL**"       -> "GENERAL"
        "# _Article 1_"        -> "Article 1"
    """

    line = line.strip()

    # Remove Markdown heading markers
    line = re.sub(r"^#{1,6}\s*", "", line)

    # Remove bold / italic Markdown markers
    line = line.replace("**", "")
    line = line.replace("__", "")
    line = line.replace("*", "")
    line = line.replace("_", "")

    return line.strip()


def is_chapter(line: str) -> bool:
    return CHAPTER_RE.match(clean_line(line)) is not None


def is_article(line: str) -> bool:
    return ARTICLE_RE.match(clean_line(line)) is not None


def is_paragraph(line: str) -> bool:
    return PARAGRAPH_RE.match(clean_line(line)) is not None


def is_point(line: str) -> bool:
    return POINT_RE.match(clean_line(line)) is not None


def extract_chapter(line: str) -> str | None:
    """
    Return normalized chapter identifier.

    Example:
        CHAPTER I -> CHAPTER I
    """

    line = clean_line(line)

    match = CHAPTER_RE.match(line)

    if not match:
        return None

    return f"CHAPTER {match.group(1).upper()}"


def extract_article(line: str) -> str | None:
    """
    Return normalized article identifier.

    Example:
        Article 1 -> Article 1
        Article 27a -> Article 27a
    """

    line = clean_line(line)

    match = ARTICLE_RE.match(line)

    if not match:
        return None

    return f"Article {match.group(1)}"


def extract_paragraph(line: str) -> tuple[int, str] | None:
    """
    Extract paragraph number and initial text.

    Example:

        1. The purpose of this Regulation...

    becomes:

        (1, "The purpose of this Regulation...")
    """

    line = clean_line(line)

    match = PARAGRAPH_RE.match(line)

    if not match:
        return None

    number = int(match.group(1))
    text = match.group(2).strip()

    return number, text


def extract_point(line: str) -> tuple[str, str] | None:
    """
    Extract a legal point.

    Example:

        (a) harmonised rules...

    becomes:

        ("a", "harmonised rules...")
    """

    line = clean_line(line)

    match = POINT_RE.match(line)

    if not match:
        return None

    identifier = match.group(1)
    text = match.group(2).strip()

    return identifier, text



# Legal structure parser


def parse_legal_structure(markdown: str) -> list[dict]:
    """
    Parse cleaned Markdown into legal structural units.

    Current hierarchy:

        Chapter
            Article
                Paragraph
                    Point

    The function deliberately does not perform chunking yet.
    """

    lines = markdown.splitlines()

    records = []

    current_chapter = None
    current_chapter_title = None

    current_article = None
    current_article_title = None

    current_paragraph = None
    current_point = None

    current_text = []

    def flush_record():
        """
        Save the current legal unit before moving to a new unit.
        """

        nonlocal current_text
        nonlocal current_paragraph
        nonlocal current_point

        if not current_text:
            return

        text = " ".join(
            part.strip()
            for part in current_text
            if part.strip()
        ).strip()

        if not text:
            current_text = []
            return

        record = {
            "chapter": current_chapter,
            "chapter_title": current_chapter_title,
            "article": current_article,
            "article_title": current_article_title,
            "paragraph": current_paragraph,
            "point": current_point,
            "text": text,
        }

        records.append(record)

        current_text = []

    for raw_line in lines:

        line = clean_line(raw_line)

        if not line:
            continue

        
        # CHAPTER
        

        chapter = extract_chapter(line)

        if chapter:
            flush_record()

            current_chapter = chapter
            current_chapter_title = None

            current_article = None
            current_article_title = None

            current_paragraph = None
            current_point = None

            continue

        
        # ARTICLE
        

        article = extract_article(line)

        if article:
            flush_record()

            current_article = article
            current_article_title = None

            current_paragraph = None
            current_point = None

            continue

        
        # PARAGRAPH
        

        paragraph = extract_paragraph(line)

        if paragraph:
            flush_record()

            current_paragraph = paragraph[0]
            current_point = None

            # If paragraph contains text on same line,
            # start collecting it.
            if paragraph[1]:
                current_text.append(paragraph[1])

            continue

        
        # POINT
        

        point = extract_point(line)

        if point:
            flush_record()

            current_point = point[0]

            if point[1]:
                current_text.append(point[1])

            continue

        
        # TITLE DETECTION
        

        if current_article and current_article_title is None:
            current_article_title = line
            continue

        if current_chapter and current_chapter_title is None:
            current_chapter_title = line
            continue

        
        # NORMAL LEGAL TEXT
        

        current_text.append(line)

    # Flush final record
    flush_record()

    return records



# File handling


def parse_legal_structure_file(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Read cleaned Markdown, extract legal structure,
    and save the result as JSON.
    """

    markdown = input_path.read_text(
        encoding="utf-8"
    )

    records = parse_legal_structure(markdown)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            records,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Input:   {input_path}")
    print(f"Output:  {output_path}")
    print(f"Records: {len(records)}")
    print("Legal structure extraction completed.")



# Main


if __name__ == "__main__":

    input_file = Path(
        "data/extracted/eli_reg_2024_1689_oj_EN_TXT.clean.md" #TODO change it to have option to choose file eventually or to accept file name and to keep it
    )

    output_file = Path(
        "data/extracted/eli_reg_2024_1689_oj_EN_TXT.structure.json"
    )

    parse_legal_structure_file(
        input_path=input_file,
        output_path=output_file,
    )