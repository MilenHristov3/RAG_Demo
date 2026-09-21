from pathlib import Path
import json
import re

# Instrument metadata


INSTRUMENT = {
    "celex": "32024R1689",
    "eli": "http://data.europa.eu/eli/reg/2024/1689/oj",
    "title": "Regulation (EU) 2024/1689 (AI Act)",
    "language": "EN",
    "publication_date": "2024-07-12",
}


# Regular expressions


CHAPTER_RE = re.compile(
    r"^CHAPTER\s+([IVXLCDM]+)\s*$",
    re.IGNORECASE,
)

ARTICLE_RE = re.compile(
    r"^Article\s+(\d+[A-Za-z]?)\s*$",
    re.IGNORECASE,
)

PARAGRAPH_RE = re.compile(r"^(\d+)\.\s*(.*)$")

# A legal point such as:
#
# (a) text
# (b) text
# (c) text
#
POINT_MARKER_RE = re.compile(
    r"\(([a-z])\)\s*",
    re.IGNORECASE,
)


# Text cleaning helpers


def clean_line(line: str) -> str:
    """
    Clean Markdown formatting from one line.

    Examples:

        "# Article 1"          -> "Article 1"
        "## **Subject matter**" -> "Subject matter"
        "# _Article 1_"        -> "Article 1"
    """

    line = line.strip()

    # Remove Markdown heading markers
    line = re.sub(r"^#{1,6}\s*", "", line)

    # Remove bold markers
    line = line.replace("**", "")

    # Remove italic markers
    line = line.replace("__", "")
    line = line.replace("*", "")
    line = line.replace("_", "")

    # Remove accidental trailing backticks
    line = line.rstrip("`").strip()

    return line


def normalize_text(text: str) -> str:
    """
    Normalize whitespace inside legal text.
    """

    text = text.replace("\u00a0", " ")

    # Collapse repeated whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def remove_list_separator(text: str) -> str:
    """
    Remove separators introduced by PDF extraction.

    Examples:

        "- (b) text" -> "(b) text"
        "– text"     -> "text"
    """

    text = text.strip()

    text = re.sub(
        r"^[\-–—]\s*",
        "",
        text,
    )

    return text.strip()


# Structure detection


def extract_chapter(line: str) -> str | None:
    """
    Extract chapter number.

    Example:

        CHAPTER I

    returns:

        I
    """

    line = clean_line(line)

    match = CHAPTER_RE.match(line)

    if not match:
        return None

    return match.group(1).upper()


def extract_article(line: str) -> str | None:
    """
    Extract article number.

    Example:

        Article 1

    returns:

        1
    """

    line = clean_line(line)

    match = ARTICLE_RE.match(line)

    if not match:
        return None

    return match.group(1)


def extract_paragraph(line: str) -> tuple[str, str] | None:
    """
    Extract paragraph number and initial text.

    Example:

        2. This Regulation lays down:

    returns:

        ("2", "This Regulation lays down:")
    """

    line = clean_line(line)

    match = PARAGRAPH_RE.match(line)

    if not match:
        return None

    number = match.group(1)
    text = normalize_text(match.group(2))

    return number, text


# Point parsing


def split_points(text: str) -> tuple[str, list[dict]]:
    """
    Detect legal points inside a text block.

    Example:

        This Regulation lays down:
        (a) harmonised rules;
        (b) prohibitions;
        (c) requirements;

    returns:

        intro:
            "This Regulation lays down:"

        points:
            [
                {
                    "label": "a",
                    "text": "harmonised rules;"
                },
                {
                    "label": "b",
                    "text": "prohibitions;"
                },
                {
                    "label": "c",
                    "text": "requirements;"
                }
            ]

    If there are no legal points, returns:

        text, []

    This is important because ordinary paragraphs must remain ordinary
    paragraphs.
    """

    text = normalize_text(text)

    matches = list(POINT_MARKER_RE.finditer(text))

    # No "(a)", "(b)", etc.
    if not matches:
        return text, []

    # -------------------------------------------------------------------------
    # Determine whether these are really legal points.
    #
    # We only treat the markers as points if they appear to form a sequence:
    #
    # (a) ...
    # (b) ...
    #
    # This prevents random references such as:
    #
    # "see Article 5(a)"
    #
    # from becoming legal points.
    # -------------------------------------------------------------------------

    labels = [match.group(1).lower() for match in matches]

    # Expected sequence starts with "a"
    if labels[0] != "a":
        return text, []

    # Check sequential ordering:
    #
    # a, b, c, d...
    expected = [chr(ord("a") + i) for i in range(len(labels))]

    if labels != expected:
        return text, []

    # -------------------------------------------------------------------------
    # Everything before "(a)" is paragraph introduction.
    # -------------------------------------------------------------------------

    intro = text[: matches[0].start()].strip()

    points = []

    # -------------------------------------------------------------------------
    # Extract each point's text.
    # -------------------------------------------------------------------------

    for index, match in enumerate(matches):

        label = match.group(1).lower()

        start = match.end()

        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(text)

        point_text = text[start:end].strip()

        point_text = remove_list_separator(point_text)

        point_text = normalize_text(point_text)

        points.append(
            {
                "label": label,
                "text": point_text,
            }
        )

    return intro, points


# Paragraph handling


def create_paragraph(
    number: str,
    text: str,
) -> dict:
    """
    Create a paragraph object.

    The function decides whether the paragraph is:

        1. A normal paragraph

    or:

        2. An introductory paragraph containing legal points.
    """

    text = normalize_text(text)

    intro, points = split_points(text)

    # -------------------------------------------------------------------------
    # Paragraph contains points
    # -------------------------------------------------------------------------

    if points:

        paragraph = {
            "number": number,
            "intro": intro,
            "points": points,
        }

        return paragraph

    # -------------------------------------------------------------------------
    # Ordinary paragraph
    # -------------------------------------------------------------------------

    paragraph = {
        "number": number,
        "text": text,
    }

    return paragraph


# Article parsing


def parse_article(
    lines: list[str],
    start_index: int,
) -> tuple[dict, int]:
    """
    Parse one complete article.

    Returns:

        article, next_index
    """

    article_line = clean_line(lines[start_index])

    article_number = extract_article(article_line)

    if article_number is None:
        raise ValueError(f"Expected Article at line {start_index}: {article_line}")

    index = start_index + 1

    # -------------------------------------------------------------------------
    # Article title
    # -------------------------------------------------------------------------

    article_title = None

    while index < len(lines):

        line = clean_line(lines[index])

        if not line:
            index += 1
            continue

        # Stop if another article/chapter starts
        if CHAPTER_RE.match(line):
            break

        if ARTICLE_RE.match(line):
            break

        # Stop when paragraph starts
        if PARAGRAPH_RE.match(line):
            break

        article_title = line

        index += 1

        break

    # -------------------------------------------------------------------------
    # Paragraphs
    # -------------------------------------------------------------------------

    paragraphs = []

    current_paragraph_number = None
    current_paragraph_text = []

    while index < len(lines):

        line = clean_line(lines[index])

        if not line:
            index += 1
            continue

        # ---------------------------------------------------------------------
        # New chapter
        # ---------------------------------------------------------------------

        if CHAPTER_RE.match(line):
            break

        # ---------------------------------------------------------------------
        # New article
        # ---------------------------------------------------------------------

        if ARTICLE_RE.match(line):
            break

        # ---------------------------------------------------------------------
        # New paragraph
        # ---------------------------------------------------------------------

        paragraph = extract_paragraph(line)

        if paragraph:

            # Save previous paragraph
            if current_paragraph_number is not None:

                paragraph_object = create_paragraph(
                    number=current_paragraph_number,
                    text=" ".join(current_paragraph_text),
                )

                paragraphs.append(paragraph_object)

            # Start new paragraph
            current_paragraph_number = paragraph[0]

            current_paragraph_text = []

            if paragraph[1]:
                current_paragraph_text.append(paragraph[1])

            index += 1

            continue

        # ---------------------------------------------------------------------
        # Continuation of current paragraph
        # ---------------------------------------------------------------------

        if current_paragraph_number is not None:

            current_paragraph_text.append(line)

        index += 1

    # -------------------------------------------------------------------------
    # Save final paragraph
    # -------------------------------------------------------------------------

    if current_paragraph_number is not None:

        paragraph_object = create_paragraph(
            number=current_paragraph_number,
            text=" ".join(current_paragraph_text),
        )

        paragraphs.append(paragraph_object)

    # -------------------------------------------------------------------------
    # Create article object
    # -------------------------------------------------------------------------

    article = {
        "number": article_number,
        "title": article_title,
        "paragraphs": paragraphs,
    }

    return article, index


# Chapter parsing


def parse_chapter_title(
    lines: list[str],
    start_index: int,
) -> tuple[str | None, int]:
    """
    Extract the chapter title.

    Example:

        CHAPTER I
        GENERAL PROVISIONS

    returns:

        "GENERAL PROVISIONS"
    """

    index = start_index

    while index < len(lines):

        line = clean_line(lines[index])

        if not line:
            index += 1
            continue

        # Do not consume another chapter/article as a title
        if CHAPTER_RE.match(line):
            return None, index

        if ARTICLE_RE.match(line):
            return None, index

        title = line

        return title, index + 1

    return None, index


# Full regulation parser


def parse_legal_structure(
    markdown: str,
) -> list[dict]:
    """
    Parse the complete legal document.

    Output hierarchy:

        instrument
            chapter
                article
                    paragraphs
                        points
    """

    lines = markdown.splitlines()

    documents = []

    current_chapter_number = None
    current_chapter_title = None

    index = 0

    while index < len(lines):

        line = clean_line(lines[index])

        if not line:
            index += 1
            continue

        # ---------------------------------------------------------------------
        # Chapter
        # ---------------------------------------------------------------------

        chapter_number = extract_chapter(line)

        if chapter_number:

            current_chapter_number = chapter_number

            current_chapter_title, next_index = parse_chapter_title(
                lines,
                index + 1,
            )

            index = next_index

            continue

        # ---------------------------------------------------------------------
        # Article
        # ---------------------------------------------------------------------

        article_number = extract_article(line)

        if article_number:

            article, next_index = parse_article(
                lines,
                index,
            )

            document = {
                "instrument": INSTRUMENT,
                "chapter": {
                    "number": current_chapter_number,
                    "title": current_chapter_title,
                },
                "article": article,
            }

            documents.append(document)

            index = next_index

            continue

        index += 1

    return documents


# File handling


def parse_legal_structure_file(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Read cleaned Markdown and write structured legal JSON.
    """

    markdown = input_path.read_text(encoding="utf-8")

    structure = parse_legal_structure(markdown)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            structure,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Input:    {input_path}")
    print(f"Output:   {output_path}")
    print(f"Articles: {len(structure)}")
    print("Legal structure extraction completed.")


# Main


if __name__ == "__main__":

    input_file = Path("data/extracted/eli_reg_2024_1689_oj_EN_TXT.clean.md")

    output_file = Path("data/extracted/eli_reg_2024_1689_oj_EN_TXT.structure.json")

    parse_legal_structure_file(
        input_path=input_file,
        output_path=output_file,
    )
