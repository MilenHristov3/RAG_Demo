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

ANNEX_RE = re.compile(
    r"^ANNEX\s+([IVXLCDM]+)\s*$",
    re.IGNORECASE,
)

SECTION_RE = re.compile(
    r"^Section\s+([A-Z])\.\s*(.+)$",
    re.IGNORECASE,
)

PARAGRAPH_RE = re.compile(r"^(\d+)\.\s*(.*)$")

POINT_MARKER_RE = re.compile(
    r"\(([a-z])\)\s*",
    re.IGNORECASE,
)

ANNEX_ITEM_RE = re.compile(r"^(\d+)\.\s*(.*)$")


# Text helpers


def clean_line(line: str) -> str:
    """
    Remove Markdown formatting without changing legal wording.
    """

    line = line.strip()

    # Markdown headings
    line = re.sub(
        r"^#{1,6}\s*",
        "",
        line,
    )

    # Bold
    line = line.replace("**", "")

    # Italic
    line = line.replace("__", "")
    line = line.replace("*", "")
    line = line.replace("_", "")

    # Remove accidental trailing backtick
    line = line.rstrip("`").strip()

    return line


def normalize_text(text: str) -> str:
    """
    Normalize whitespace but preserve punctuation.
    """

    text = text.replace(
        "\u00a0",
        " ",
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def remove_list_separator(text: str) -> str:
    """
    Remove separators sometimes introduced by PDF extraction.
    """

    text = text.strip()

    text = re.sub(
        r"^[\-–—]\s*",
        "",
        text,
    )

    return text.strip()


# Structural detection


def extract_chapter(line: str) -> str | None:

    line = clean_line(line)

    match = CHAPTER_RE.match(line)

    if not match:
        return None

    return match.group(1).upper()


def extract_article(line: str) -> str | None:

    line = clean_line(line)

    match = ARTICLE_RE.match(line)

    if not match:
        return None

    return match.group(1)


def extract_annex(line: str) -> str | None:

    line = clean_line(line)

    match = ANNEX_RE.match(line)

    if not match:
        return None

    return match.group(1).upper()


def extract_section(line: str) -> tuple[str, str] | None:

    line = clean_line(line)

    match = SECTION_RE.match(line)

    if not match:
        return None

    return (
        match.group(1).upper(),
        match.group(2).strip(),
    )


def extract_paragraph(
    line: str,
) -> tuple[str, str] | None:

    line = clean_line(line)

    match = PARAGRAPH_RE.match(line)

    if not match:
        return None

    return (
        match.group(1),
        normalize_text(match.group(2)),
    )


# Legal point parsing


def looks_like_point_sequence(
    matches: list[re.Match],
) -> bool:
    """
    Decide whether "(a)", "(b)", "(c)" etc. represent
    a legal point sequence.

    We require:
        a, b, c, d ...

    This avoids incorrectly interpreting things such as:

        Article 6(1)(a)

    as paragraph points.
    """

    if not matches:
        return False

    labels = [match.group(1).lower() for match in matches]

    if labels[0] != "a":
        return False

    for index, label in enumerate(labels):

        expected = chr(ord("a") + index)

        if label != expected:
            return False

    return True


def split_legal_points(
    text: str,
) -> tuple[str, list[dict]]:
    """
    Split text containing legal points.

    Example:

        However: (a) first; (b) second; (c) third.

    returns:

        intro = "However:"

        points = [
            {
                "label": "a",
                "text": "first;"
            },
            ...
        ]

    If the text doesn't contain a valid point sequence:

        return text, []
    """

    text = normalize_text(text)

    matches = list(POINT_MARKER_RE.finditer(text))

    if not matches:
        return text, []

    if not looks_like_point_sequence(matches):
        return text, []

    intro = text[: matches[0].start()].strip()

    points = []

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


# Cross-reference extraction


def extract_references(
    text: str,
) -> list[dict]:
    """
    Extract simple internal legal references.

    Examples:

        Chapter I
        Chapter II
        Article 78
        Article 6(1)
        Article 101
        Chapter III Section 4

    This is intentionally conservative.
    """

    references = []

    # -------------------------------------------------------------------------
    # Chapter + Section
    # -------------------------------------------------------------------------

    section_pattern = re.compile(
        r"\bChapter\s+([IVXLCDM]+)\s+Section\s+(\d+)",
        re.IGNORECASE,
    )

    for match in section_pattern.finditer(text):

        references.append(
            {
                "type": "section",
                "target": (f"{match.group(1).upper()}" f"." f"{match.group(2)}"),
            }
        )

    # -------------------------------------------------------------------------
    # Chapters
    # -------------------------------------------------------------------------

    chapter_pattern = re.compile(
        r"\bChapter\s+([IVXLCDM]+)\b",
        re.IGNORECASE,
    )

    for match in chapter_pattern.finditer(text):

        chapter = match.group(1).upper()

        # Don't duplicate chapter reference when
        # it was already represented as a Section.
        already_section = any(
            ref["type"] == "section" and ref["target"].startswith(f"{chapter}.")
            for ref in references
        )

        if not already_section:

            references.append(
                {
                    "type": "chapter",
                    "target": chapter,
                }
            )

    # -------------------------------------------------------------------------
    # Articles
    # -------------------------------------------------------------------------

    article_pattern = re.compile(
        r"\bArticle\s+(\d+[A-Za-z]?)" r"(?:\((\d+[A-Za-z]?)\))?",
        re.IGNORECASE,
    )

    for match in article_pattern.finditer(text):

        target = match.group(1)

        reference = {
            "type": "article",
            "target": target,
        }

        if match.group(2):
            reference["paragraph"] = match.group(2)

        references.append(reference)

    return references


def add_reference_relations(
    references: list[dict],
    text: str,
) -> list[dict]:
    """
    Add simple semantic relations when they are explicit in the text.

    Currently handles:

        exception -> Article X

    for phrases such as:

        with the exception of Article 101
    """

    exception_pattern = re.compile(
        r"with\s+the\s+exception\s+of\s+Article\s+" r"(\d+[A-Za-z]?)",
        re.IGNORECASE,
    )

    exception_articles = {match.group(1) for match in exception_pattern.finditer(text)}

    for reference in references:

        if reference["type"] == "article" and reference["target"] in exception_articles:
            reference["relation"] = "exception"

    return references


def extract_point_references(
    text: str,
) -> list[dict]:

    references = extract_references(text)

    references = add_reference_relations(
        references,
        text,
    )

    return references


# Paragraph representation


def create_paragraph(
    index: int,
    number: str | None,
    text: str,
) -> dict:
    """
    Create a paragraph.

    Number may be None because legal documents can contain
    unnumbered paragraphs.

    If points exist:

        {
            "index": 3,
            "number": null,
            "intro": "However:",
            "points": [...]
        }

    Otherwise:

        {
            "index": 1,
            "number": null,
            "text": "..."
        }
    """

    text = normalize_text(text)

    intro, points = split_legal_points(text)

    if points:

        paragraph = {
            "index": index,
            "number": number,
            "intro": intro,
            "points": points,
        }

        return paragraph

    return {
        "index": index,
        "number": number,
        "text": text,
    }


# Article closing / signatures


def parse_closing(
    text: str,
) -> dict | None:
    """
    Parse a closing/signature block.

    Example:

        Done at Brussels, 13 June 2024.
        For the European Parliament
        The President
        R. METSOLA
        For the Council
        The President
        M. MICHEL
    """

    text = normalize_text(text)

    pattern = re.compile(
        r"Done\s+at\s+(.+?),\s+" r"(\d{1,2}\s+\w+\s+\d{4})\." r"(.*)",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return None

    place = match.group(1).strip()
    date = match.group(2).strip()

    remainder = match.group(3).strip()

    signatories = []

    signature_pattern = re.compile(
        r"For\s+the\s+"
        r"(European Parliament|Council)"
        r"\s+"
        r"The\s+President"
        r"\s+"
        r"([A-Z]\.\s*[A-ZÀ-ÖØ-Ý]+)",
        re.IGNORECASE,
    )

    for signature in signature_pattern.finditer(remainder):

        signatories.append(
            {
                "body": signature.group(1),
                "role": "President",
                "name": signature.group(2),
            }
        )

    return {
        "place": place,
        "date": date,
        "signatories": signatories,
    }


# Article parsing


def parse_article(
    lines: list[str],
    start_index: int,
) -> tuple[dict, int]:
    """
    Parse one Article.

    Supports:

        numbered paragraphs

    and:

        unnumbered paragraphs

    and:

        points (a), (b), (c)
    """

    article_number = extract_article(lines[start_index])

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

        if CHAPTER_RE.match(line):
            break

        if ARTICLE_RE.match(line):
            break

        if ANNEX_RE.match(line):
            break

        if PARAGRAPH_RE.match(line):
            break

        # Anything else immediately following Article X
        # is considered its title.
        article_title = line

        index += 1
        break

    # -------------------------------------------------------------------------
    # Collect raw paragraph blocks
    # -------------------------------------------------------------------------

    paragraph_blocks = []

    current_number = None
    current_lines = []

    def flush_current():

        nonlocal current_number
        nonlocal current_lines

        if not current_lines:
            return

        paragraph_blocks.append(
            {
                "number": current_number,
                "text": " ".join(current_lines),
            }
        )

        current_number = None
        current_lines = []

    while index < len(lines):

        line = clean_line(lines[index])

        if not line:
            index += 1
            continue

        # ---------------------------------------------------------------------
        # New chapter/article/annex
        # ---------------------------------------------------------------------

        if CHAPTER_RE.match(line):
            break

        if ARTICLE_RE.match(line):
            break

        if ANNEX_RE.match(line):
            break

        # ---------------------------------------------------------------------
        # Numbered paragraph
        # ---------------------------------------------------------------------

        paragraph = extract_paragraph(line)

        if paragraph:

            flush_current()

            current_number = paragraph[0]

            if paragraph[1]:
                current_lines.append(paragraph[1])

            index += 1

            continue

        # ---------------------------------------------------------------------
        # Otherwise continuation of current paragraph
        # ---------------------------------------------------------------------

        current_lines.append(line)

        index += 1

    flush_current()

    # -------------------------------------------------------------------------
    # Detect Article 113 closing block
    # -------------------------------------------------------------------------

    closing = None

    cleaned_blocks = []

    for block in paragraph_blocks:

        block_text = normalize_text(block["text"])

        closing_candidate = parse_closing(block_text)

        if closing_candidate:

            # Everything before "Done at..." remains legal text.
            done_match = re.search(
                r"\bDone\s+at\b",
                block_text,
                re.IGNORECASE,
            )

            before_closing = (
                block_text[: done_match.start()].strip() if done_match else block_text
            )

            if before_closing:

                cleaned_blocks.append(
                    {
                        "number": block["number"],
                        "text": before_closing,
                    }
                )

            closing = closing_candidate

        else:

            cleaned_blocks.append(block)

    # -------------------------------------------------------------------------
    # Convert paragraphs
    # -------------------------------------------------------------------------

    paragraphs = []

    for index_number, block in enumerate(
        cleaned_blocks,
        start=1,
    ):

        paragraph = create_paragraph(
            index=index_number,
            number=block["number"],
            text=block["text"],
        )

        # Add references to points
        if "points" in paragraph:

            for point in paragraph["points"]:

                references = extract_point_references(point["text"])

                if references:
                    point["references"] = references

        paragraphs.append(paragraph)

    # -------------------------------------------------------------------------
    # Article object
    # -------------------------------------------------------------------------

    article = {
        "type": "article",
        "id": f"aiact:art{article_number}",
        "number": article_number,
        "title": article_title,
        "paragraphs": paragraphs,
    }

    if closing:
        article["closing"] = closing

    return article, index


# Annex item parsing


def extract_cited_act(
    text: str,
) -> dict | None:
    """
    Extract information from citations such as:

        Directive 2006/42/EC of ... 17 May 2006
        ... on machinery (OJ L 157, 9.6.2006, p. 24)
    """

    pattern = re.compile(
        r"\b(Directive|Regulation)"
        r"\s+"
        r"(\d{4}/\d+/(?:EC|EU))"
        r"(?:\s+of\s+"
        r"(\d{1,2}\s+\w+\s+\d{4}))?"
        r"(.*)",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return None

    kind = match.group(1).lower()
    identifier = match.group(2)

    date_text = match.group(3)

    remainder = match.group(4).strip()

    short_title = None

    # Find "on ..." before OJ reference
    title_match = re.search(
        r"\bon\s+(.+?)(?=\s*\(OJ\s+)",
        remainder,
        re.IGNORECASE,
    )

    if title_match:
        short_title = title_match.group(1).strip()

    oj_reference = None

    oj_match = re.search(
        r"\((OJ\s+[^)]+)\)",
        text,
        re.IGNORECASE,
    )

    if oj_match:
        oj_reference = oj_match.group(1)

    return {
        "kind": kind,
        "identifier": identifier,
        "date": date_text,
        "short_title": short_title,
        "oj_reference": oj_reference,
    }


def parse_annex(
    lines: list[str],
    start_index: int,
) -> tuple[dict, int]:
    """
    Parse an Annex.

    Structure:

        ANNEX I
        title

        Section A. title

        1. item
        2. item
        3. item

        Section B. title

        ...
    """

    annex_number = extract_annex(lines[start_index])

    index = start_index + 1

    # -------------------------------------------------------------------------
    # Annex title
    # -------------------------------------------------------------------------

    title = None

    while index < len(lines):

        line = clean_line(lines[index])

        if not line:
            index += 1
            continue

        if SECTION_RE.match(line):
            break

        if ANNEX_RE.match(line):
            break

        title = line

        index += 1
        break

    # -------------------------------------------------------------------------
    # Sections
    # -------------------------------------------------------------------------

    sections = []

    current_section = None
    current_item = None

    def flush_item():

        nonlocal current_item

        if current_item is None:
            return

        if current_section is not None:

            current_section["items"].append(current_item)

        current_item = None

    def flush_section():

        nonlocal current_section

        flush_item()

        if current_section is not None:
            sections.append(current_section)

        current_section = None

    while index < len(lines):

        line = clean_line(lines[index])

        if not line:
            index += 1
            continue

        # ---------------------------------------------------------------------
        # Next annex
        # ---------------------------------------------------------------------

        if ANNEX_RE.match(line):
            break

        # ---------------------------------------------------------------------
        # Section
        # ---------------------------------------------------------------------

        section = extract_section(line)

        if section:

            flush_section()

            current_section = {
                "label": section[0],
                "title": section[1],
                "items": [],
            }

            index += 1

            continue

        # ---------------------------------------------------------------------
        # Numbered annex item
        # ---------------------------------------------------------------------

        item = ANNEX_ITEM_RE.match(line)

        if item and current_section is not None:

            flush_item()

            item_number = item.group(1)
            item_text = normalize_text(item.group(2))

            current_item = {
                "number": item_number,
                "text": item_text,
            }

            cited_act = extract_cited_act(item_text)

            if cited_act:
                current_item["cited_act"] = cited_act

            index += 1

            continue

        # ---------------------------------------------------------------------
        # Continuation of annex item
        # ---------------------------------------------------------------------

        if current_item is not None:

            current_item["text"] += " "
            current_item["text"] += line

            current_item["text"] = normalize_text(current_item["text"])

            # Recalculate cited act after continuation
            cited_act = extract_cited_act(current_item["text"])

            if cited_act:
                current_item["cited_act"] = cited_act

        index += 1

    flush_section()

    annex = {
        "type": "annex",
        "id": f"aiact:annex{annex_number}",
        "number": annex_number,
        "title": title,
        "sections": sections,
    }

    return annex, index


# Full document parser


def parse_legal_structure(
    markdown: str,
) -> list[dict]:
    """
    Parse the complete legal document.

    Supported top-level structures:

        Article
        Annex

    Articles may belong to chapters.

    Annexes do NOT belong to chapters.
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

            current_chapter_title = None

            index += 1

            # Find chapter title
            while index < len(lines):

                title_line = clean_line(lines[index])

                if not title_line:
                    index += 1
                    continue

                if CHAPTER_RE.match(title_line):
                    break

                if ARTICLE_RE.match(title_line):
                    break

                if ANNEX_RE.match(title_line):
                    break

                current_chapter_title = title_line

                index += 1

                break

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

            article["chapter"] = {
                "number": current_chapter_number,
                "title": current_chapter_title,
            }

            # Put chapter before number/title in the JSON
            article = reorder_article(article)

            documents.append(article)

            index = next_index

            continue

        # ---------------------------------------------------------------------
        # Annex
        # ---------------------------------------------------------------------

        annex_number = extract_annex(line)

        if annex_number:

            # IMPORTANT:
            # Annexes are NOT attached to the current chapter.
            current_chapter_number = None
            current_chapter_title = None

            annex, next_index = parse_annex(
                lines,
                index,
            )

            documents.append(annex)

            index = next_index

            continue

        index += 1

    return documents


# Article ordering


def reorder_article(
    article: dict,
) -> dict:
    """
    Produce the desired JSON field order.

    JSON object ordering is not semantically important,
    but this makes the output easier to read.
    """

    result = {
        "type": article["type"],
        "id": article["id"],
        "chapter": article["chapter"],
        "number": article["number"],
        "title": article["title"],
        "paragraphs": article["paragraphs"],
    }

    if "closing" in article:
        result["closing"] = article["closing"]

    return result


# File handling


def parse_legal_structure_file(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Read cleaned Markdown and save legal structure as JSON.
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

    article_count = sum(1 for item in structure if item.get("type") == "article")

    annex_count = sum(1 for item in structure if item.get("type") == "annex")

    print(f"Input:    {input_path}")

    print(f"Output:   {output_path}")

    print(f"Articles: {article_count}")

    print(f"Annexes:  {annex_count}")

    print("Legal structure extraction completed.")


# Main


if __name__ == "__main__":

    input_file = Path("data/extracted/eli_reg_2024_1689_oj_EN_TXT.clean.md")

    output_file = Path("data/extracted/eli_reg_2024_1689_oj_EN_TXT.structure.json")

    parse_legal_structure_file(
        input_path=input_file,
        output_path=output_file,
    )
