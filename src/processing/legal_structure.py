from pathlib import Path
import json
import re
from datetime import datetime


# ============================================================
# Document metadata
# ============================================================


INSTRUMENT = {
    "celex": "32024R1689",
    "eli": "http://data.europa.eu/eli/reg/2024/1689/oj",
    "title": "Regulation (EU) 2024/1689 (AI Act)",
    "language": "EN",
    "publication_date": "2024-07-12",
}


# ============================================================
# Regular expressions
# ============================================================


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

PARAGRAPH_RE = re.compile(
    r"^(\d+)\.\s*(.*)$",
)

ANNEX_ITEM_RE = re.compile(
    r"^(\d+)\.\s*(.*)$",
)

POINT_MARKER_RE = re.compile(
    r"\(([a-z])\)\s*",
    re.IGNORECASE,
)

ANNEX_DASH_MARKER_RE = re.compile(
    r"(?<!\w)(?:—|–|-|•|·)\s*"
)

ANNEX_DASH_ITEM_RE = re.compile(
    r"(?:^|\s)(—|–|-|•|·)\s*"
)

ARTICLE_REFERENCE_RE = re.compile(
    r"\bArticle\s+"
    r"(\d+[A-Za-z]?)"
    r"(?:\((\d+)\))?"
    r"(?:\s*,?\s*(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
    r"\s+subparagraph)?"
    r"(?:\s*,?\s*point\s*\(([a-z])\))?"
    r"(?:\s*\(([ivxlcdm]+)\))?",
    re.IGNORECASE,
)

ARTICLE_SIMPLE_REFERENCE_RE = re.compile(
    r"\bArticle\s+(\d+[A-Za-z]?)"
    r"(?:\((\d+)\))?"
    r"(?:\(([a-z])\))?"
    r"(?:\(([ivxlcdm]+)\))?",
    re.IGNORECASE,
)

CHAPTER_REFERENCE_RE = re.compile(
    r"\bChapter\s+([IVXLCDM]+)",
    re.IGNORECASE,
)

SECTION_REFERENCE_RE = re.compile(
    r"\bChapter\s+([IVXLCDM]+)\s+Section\s+(\d+)",
    re.IGNORECASE,
)

DONE_AT_RE = re.compile(
    r"Done\s+at\s+(.+?),\s+"
    r"(\d{1,2}\s+\w+\s+\d{4})\.",
    re.IGNORECASE,
)

SIGNATURE_RE = re.compile(
    r"For\s+the\s+"
    r"(European Parliament|Council)"
    r"\s+The\s+President"
    r"\s+"
    r"([A-Z]\.\s*[A-ZÀ-ÖØ-Ý]+)",
    re.IGNORECASE,
)


# ============================================================
# Basic helpers
# ============================================================


def clean_line(line: str) -> str:
    """
    Remove Markdown formatting that is useful during PDF
    extraction but not required in the structural JSON.
    """

    line = line.strip()

    # Markdown heading markers
    line = re.sub(
        r"^#{1,6}\s*",
        "",
        line,
    )

    # Common emphasis markers
    line = line.replace("**", "")
    line = line.replace("__", "")

    # Markdown italic markers only at the edges.
    line = re.sub(
        r"^[_*]+",
        "",
        line,
    )

    line = re.sub(
        r"[_*]+$",
        "",
        line,
    )

    return line.strip()


def normalize_text(text: str) -> str:
    """
    Normalize whitespace without changing legal wording.
    """

    text = text.replace("\u00a0", " ")
    text = text.replace("\u2009", " ")
    text = text.replace("\u200a", " ")
    text = text.replace("\u202f", " ")

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def remove_list_separator(text: str) -> str:
    """
    Remove an accidental leading list separator.
    """

    return re.sub(
        r"^\s*(?:—|–|-|•|·)\s*",
        "",
        text,
    ).strip()


def roman_to_int(value: str) -> int:
    """
    Convert a Roman numeral to an integer.

    Used only for stable IDs such as:

        ANNEX II -> aiact:annex2
    """

    values = {
        "I": 1,
        "V": 5,
        "X": 10,
        "L": 50,
        "C": 100,
        "D": 500,
        "M": 1000,
    }

    value = value.upper()

    total = 0
    previous = 0

    for char in reversed(value):
        current = values.get(char, 0)

        if current < previous:
            total -= current
        else:
            total += current

        previous = current

    return total


# ============================================================
# Reference extraction
# ============================================================


def extract_references(text: str) -> list[dict]:
    """
    Extract legal references from a piece of text.
    """

    references = []

    # --------------------------------------------------------
    # Chapter + Section references
    # --------------------------------------------------------

    section_matches = list(
        SECTION_REFERENCE_RE.finditer(text)
    )

    section_spans = []

    for match in section_matches:
        chapter_number = match.group(1).upper()
        section_number = match.group(2)

        references.append(
            {
                "type": "section",
                "target": f"{chapter_number}.{section_number}",
            }
        )

        section_spans.append(match.span())

    # --------------------------------------------------------
    # Article references
    # --------------------------------------------------------

    for match in ARTICLE_REFERENCE_RE.finditer(text):
        article_number = match.group(1)
        paragraph = match.group(2)
        subparagraph = match.group(3)
        point = match.group(4)
        subpoint = match.group(5)

        reference = {
            "type": "article",
            "target": article_number,
        }

        if paragraph:
            reference["paragraph"] = paragraph

        if subparagraph:
            reference["subparagraph"] = subparagraph.lower()

        if point:
            reference["point"] = point.lower()

        if subpoint:
            reference["subpoint"] = subpoint.lower()

        references.append(reference)

    # --------------------------------------------------------
    # Chapter references
    # --------------------------------------------------------

    for match in CHAPTER_REFERENCE_RE.finditer(text):
        chapter_number = match.group(1).upper()

        is_section_reference = any(
            span[0] <= match.start() < span[1]
            for span in section_spans
        )

        if not is_section_reference:
            references.append(
                {
                    "type": "chapter",
                    "target": chapter_number,
                }
            )

    return references


# ============================================================
# Point parsing
# ============================================================


def looks_like_point_sequence(text: str) -> bool:
    """
    Detect whether text contains a legal point sequence:

        (a) ...
        (b) ...
        (c) ...

    The sequence must begin with (a).
    """

    matches = list(
        POINT_MARKER_RE.finditer(text)
    )

    if not matches:
        return False

    return matches[0].group(1).lower() == "a"


def get_sequential_point_matches(
    text: str,
) -> list[re.Match]:
    """
    Return a genuine sequential legal point sequence.

    Example:

        (a) ...
        (b) ...
        (c) ...

    Only a sequence beginning with (a) is accepted.

    This is important because references such as:

        Article 6(1)(a)

    must not be interpreted as list points.
    """

    matches = list(
        POINT_MARKER_RE.finditer(text)
    )

    if not matches:
        return []

    valid_matches = []

    for match in matches:
        label = match.group(1).lower()

        if not valid_matches:
            if label == "a":
                valid_matches.append(match)

            continue

        previous_label = (
            valid_matches[-1]
            .group(1)
            .lower()
        )

        expected = chr(
            ord(previous_label) + 1
        )

        if label == expected:
            valid_matches.append(match)
        else:
            break

    return valid_matches


def split_legal_points(
    text: str,
) -> tuple[str, list[dict]]:
    """
    Split:

        However: (a) first ... (b) second ... (c) third ...

    into:

        intro
        points

    Only sequential point lists beginning with (a)
    are considered.
    """

    matches = get_sequential_point_matches(text)

    if not matches:
        return text.strip(), []

    intro = text[
        : matches[0].start()
    ].strip()

    points = []

    for index, match in enumerate(matches):
        label = match.group(1).lower()

        start = match.end()

        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(text)

        point_text = text[
            start:end
        ].strip()

        if not point_text:
            continue

        point = {
            "label": label,
            "text": normalize_text(point_text),
        }

        references = extract_references(
            point_text
        )

        if references:
            point["references"] = references

        points.append(point)

    return intro, points


# ============================================================
# Paragraph parsing
# ============================================================


def extract_paragraph(
    block: str,
    index: int,
) -> dict:
    """
    Parse a paragraph block.

    We never invent a paragraph number.
    """

    block = normalize_text(block)

    match = PARAGRAPH_RE.match(block)

    if match:
        number = match.group(1)
        body = match.group(2).strip()
    else:
        number = None
        body = block

    paragraph = {
        "index": index,
        "number": number,
    }

    intro, points = split_legal_points(body)

    if points:
        if intro:
            paragraph["intro"] = normalize_text(
                intro
            )

        paragraph["points"] = points

    else:
        paragraph["text"] = normalize_text(
            body
        )

    return paragraph


# ============================================================
# Closing / signatures
# ============================================================


def parse_closing(
    text: str,
) -> tuple[str, dict | None]:
    """
    Extract the formal closing block from an article.
    """

    match = DONE_AT_RE.search(text)

    if not match:
        return text, None

    place = match.group(1).strip()
    date_text = match.group(2).strip()

    try:
        date = (
            datetime.strptime(
                date_text,
                "%d %B %Y",
            )
            .date()
            .isoformat()
        )
    except ValueError:
        date = date_text

    closing = {
        "place": place,
        "date": date,
        "signatories": [],
    }

    remaining = text[
        : match.start()
    ].strip()

    after_done = text[
        match.end():
    ].strip()

    signature_matches = list(
        SIGNATURE_RE.finditer(
            after_done
        )
    )

    for signature_match in signature_matches:
        body = signature_match.group(1)
        name = normalize_text(
            signature_match.group(2)
        )

        closing["signatories"].append(
            {
                "body": body,
                "role": "President",
                "name": name,
            }
        )

    return remaining, closing


# ============================================================
# Article parsing
# ============================================================


def parse_article(
    lines: list[str],
    article_number: str,
    chapter: dict | None,
) -> dict:
    """
    Parse an Article block.

    Existing behavior is preserved:
        - numbered paragraphs
        - unnumbered paragraphs
        - legal points
        - closing/signatures
    """

    article = {
        "type": "article",
        "id": f"aiact:art{article_number}",
        "number": article_number,
    }

    if chapter:
        article["chapter"] = chapter

    body_lines = []

    title = None

    for line in lines:
        line = clean_line(line)

        if not line:
            continue

        if title is None:
            title = normalize_text(line)
            continue

        body_lines.append(line)

    if title:
        article["title"] = title

    body = normalize_text(
        " ".join(body_lines)
    )

    body, closing = parse_closing(body)

    numbered_matches = list(
        re.finditer(
            r"(?:^|\s)(\d+)\.\s+",
            body,
        )
    )

    paragraphs = []

    if numbered_matches:
        blocks = []

        for index, match in enumerate(
            numbered_matches
        ):
            start = match.start()

            if match.group(0).startswith(" "):
                start += 1

            content_start = match.end()

            if index + 1 < len(
                numbered_matches
            ):
                end = numbered_matches[
                    index + 1
                ].start()
            else:
                end = len(body)

            paragraph_number = match.group(1)

            paragraph_text = body[
                content_start:end
            ].strip()

            blocks.append(
                f"{paragraph_number}. "
                f"{paragraph_text}"
            )

        for index, block in enumerate(
            blocks,
            start=1,
        ):
            paragraphs.append(
                extract_paragraph(
                    block,
                    index,
                )
            )

    else:
        paragraphs = (
            parse_unnumbered_article_body(
                body
            )
        )

    if paragraphs:
        article["paragraphs"] = paragraphs

    if closing:
        article["closing"] = closing

    return article


def parse_unnumbered_article_body(
    body: str,
) -> list[dict]:
    """
    Parse article text where the source does not provide
    explicit paragraph numbers.
    """

    body = normalize_text(body)

    if not body:
        return []

    valid_point_matches = (
        get_sequential_point_matches(
            body
        )
    )

    if not valid_point_matches:
        return [
            {
                "index": 1,
                "number": None,
                "text": body,
            }
        ]

    before_points = body[
        : valid_point_matches[0].start()
    ].strip()

    final_match = valid_point_matches[-1]

    after_last_point = body[
        final_match.end():
    ]

    point_entries = []

    for index, match in enumerate(
        valid_point_matches
    ):
        start = match.end()

        if index + 1 < len(
            valid_point_matches
        ):
            end = valid_point_matches[
                index + 1
            ].start()
        else:
            end = len(body)

        point_text = body[
            start:end
        ].strip()

        point_entries.append(
            {
                "label": match.group(1).lower(),
                "text": normalize_text(
                    point_text
                ),
            }
        )

    paragraphs = []

    if before_points:
        intro_text = normalize_text(
            before_points
        )

        if re.search(
            r"(?:^|\s)However:\s*$",
            intro_text,
            re.IGNORECASE,
        ):
            prefix_without_however = re.sub(
                r"\s*However:\s*$",
                "",
                intro_text,
                flags=re.IGNORECASE,
            ).strip()

            if prefix_without_however:
                paragraphs.append(
                    {
                        "index": 1,
                        "number": None,
                        "text": prefix_without_however,
                    }
                )

            paragraphs.append(
                {
                    "index": len(paragraphs) + 1,
                    "number": None,
                    "intro": "However:",
                    "points": point_entries,
                }
            )

        else:
            paragraphs.append(
                {
                    "index": 1,
                    "number": None,
                    "text": intro_text,
                }
            )

            paragraphs.append(
                {
                    "index": 2,
                    "number": None,
                    "points": point_entries,
                }
            )

    else:
        paragraphs.append(
            {
                "index": 1,
                "number": None,
                "points": point_entries,
            }
        )

    trailing = normalize_text(
        after_last_point
    )

    if trailing:
        boundary_match = re.search(
            r"(?:;\s*)"
            r"(This Regulation\b|"
            r"The Commission\b|"
            r"The Member States\b|"
            r"Member States\b)",
            trailing,
            re.IGNORECASE,
        )

        if boundary_match:
            point_part = trailing[
                : boundary_match.start() + 1
            ].strip()

            following_part = trailing[
                boundary_match.start() + 1:
            ].strip()

            if point_part:
                point_entries[-1]["text"] = (
                    normalize_text(
                        point_entries[-1]["text"]
                        + " "
                        + point_part
                    )
                )

            if following_part:
                paragraphs.append(
                    {
                        "index": len(paragraphs) + 1,
                        "number": None,
                        "text": following_part,
                    }
                )

        else:
            if point_entries:
                point_entries[-1]["text"] = (
                    normalize_text(
                        point_entries[-1]["text"]
                        + " "
                        + trailing
                    )
                )

    for index, paragraph in enumerate(
        paragraphs,
        start=1,
    ):
        paragraph["index"] = index

    return paragraphs


# ============================================================
# Annex list-item parsing
# ============================================================


def split_dash_list_items(
    text: str,
) -> list[dict]:
    """
    Split an unnumbered legal list introduced by dash/dot
    markers.
    """

    text = normalize_text(text)

    if not text:
        return []

    matches = list(
        ANNEX_DASH_ITEM_RE.finditer(
            text
        )
    )

    if not matches:
        return []

    items = []

    for index, match in enumerate(
        matches
    ):
        start = match.end()

        if index + 1 < len(matches):
            end = matches[
                index + 1
            ].start()
        else:
            end = len(text)

        item_text = text[
            start:end
        ].strip()

        if not item_text:
            continue

        items.append(
            {
                "index": len(items) + 1,
                "label": None,
                "text": normalize_text(
                    item_text
                ),
            }
        )

    return items


def parse_annex_references(
    intro: str,
) -> list[dict]:
    """
    Extract references from an annex introduction.
    """

    return extract_references(intro)


# ============================================================
# Cited act parsing
# ============================================================


def extract_cited_act(
    text: str,
) -> dict | None:
    """
    Extract a cited EU legal act from annex item text.
    """

    pattern = re.compile(
        r"\b"
        r"(Directive|Regulation|Decision)"
        r"\s+"
        r"(\d{4}/\d+/(?:EC|EU|EEC|EURATOM))"
        r"(?:"
        r".*?"
        r"\b"
        r"(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|"
        r"August|September|October|November|December)"
        r"\s+"
        r"(\d{4})"
        r")?"
        r"(?:"
        r".*?"
        r"\bon\s+"
        r"([^;]+?)"
        r")?"
        r"(?:"
        r"\s*\("
        r"(OJ\s+[^)]+)"
        r"\)"
        r")?"
        r"$",
        re.IGNORECASE,
    )

    match = pattern.search(
        normalize_text(text)
    )

    if not match:
        return None

    kind = match.group(1).lower()
    identifier = match.group(2)

    cited_act = {
        "kind": kind,
        "identifier": identifier,
    }

    day = match.group(3)
    month = match.group(4)
    year = match.group(5)

    if day and month and year:
        try:
            date = (
                datetime.strptime(
                    f"{day} {month} {year}",
                    "%d %B %Y",
                )
                .date()
                .isoformat()
            )

            cited_act["date"] = date

        except ValueError:
            pass

    short_title = match.group(6)

    if short_title:
        short_title = short_title.strip()

        if len(short_title) <= 120:
            cited_act["short_title"] = (
                short_title
            )

    oj_reference = match.group(7)

    if oj_reference:
        cited_act["oj_reference"] = (
            oj_reference.strip()
        )

    return cited_act


# ============================================================
# Generic nested numbered-item detection
# ============================================================


def find_numbered_items(
    text: str,
) -> list[re.Match]:
    """
    Find numbered legal items such as:

        1. ...
        2. ...
        3. ...

    The numbering is detected independently of the Annex
    number or document-specific content.
    """

    return list(
        re.finditer(
            r"(?:^|\s)(\d+)\.\s+",
            text,
        )
    )


def split_nested_subpoints(
    text: str,
) -> tuple[str, list[dict]]:
    """
    Detect a genuine nested legal point sequence:

        (a) ...
        (b) ...
        (c) ...

    Returns:

        prefix,
        subpoints

    The sequence must begin with (a) and continue
    sequentially.
    """

    text = normalize_text(text)

    matches = get_sequential_point_matches(text)

    if not matches:
        return text, []

    prefix = text[
        :matches[0].start()
    ].strip()

    subpoints = []

    for index, match in enumerate(matches):

        start = match.end()

        if index + 1 < len(matches):
            end = matches[
                index + 1
            ].start()
        else:
            end = len(text)

        subpoint_text = text[
            start:end
        ].strip()

        if not subpoint_text:
            continue

        subpoint = {
            "label": match.group(1).lower(),
            "text": normalize_text(
                subpoint_text
            ),
        }

        references = extract_references(
            subpoint_text
        )

        if references:
            subpoint["references"] = references

        subpoints.append(subpoint)

    return prefix, subpoints


def split_subpoint_note(
    text: str,
) -> tuple[str, str | None]:
    """
    Detect an explanatory exception/note belonging to
    a legal subpoint.

    Examples:

        This shall not include ...

        This shall not apply ...

        This does not include ...

        This does not apply ...

        except that ...

        except where ...

        provided that ...

        unless ...
    """

    text = normalize_text(text)

    note_pattern = re.compile(
        r"\s+("
        r"This shall not include\b.*"
        r"|This shall not apply\b.*"
        r"|This does not include\b.*"
        r"|This does not apply\b.*"
        r"|except that\b.*"
        r"|except where\b.*"
        r"|provided that\b.*"
        r"|unless\b.*"
        r")",
        re.IGNORECASE,
    )

    match = note_pattern.search(text)

    if not match:
        return text, None

    main_text = text[
        :match.start()
    ].strip()

    note_text = match.group(1).strip()

    if not main_text:
        return text, None

    return (
        normalize_text(main_text),
        normalize_text(note_text),
    )


def split_category_heading(
    prefix: str,
) -> tuple[str, str | None]:
    """
    Split the text before the first subpoint into:

        category
        intro

    Examples:

        Biometrics, in so far as their use is permitted
        under relevant Union or national law:

    becomes:

        category:
            Biometrics

        intro:
            Biometrics, in so far as their use is permitted
            under relevant Union or national law:

    Another example:

        Education and vocational training:

    becomes:

        category:
            Education and vocational training

        intro:
            Education and vocational training:

    This is generic and does not depend on Annex III.
    """

    prefix = normalize_text(prefix)

    if not prefix:
        return "", None

    without_colon = prefix.rstrip(":").strip()

    # --------------------------------------------------------
    # Heading with a qualification.
    #
    # Example:
    #
    # Biometrics, in so far as ...
    # --------------------------------------------------------

    comma_match = re.match(
        r"^([^,]+),\s+(.+)$",
        without_colon,
    )

    if comma_match:

        category = normalize_text(
            comma_match.group(1)
        )

        # Avoid interpreting long ordinary prose as a
        # category merely because it contains a comma.
        if len(category.split()) <= 12:
            return (
                category,
                normalize_text(prefix),
            )

    # --------------------------------------------------------
    # Simple heading ending in a colon.
    #
    # Example:
    #
    # Education and vocational training:
    # --------------------------------------------------------

    if prefix.endswith(":"):

        return (
            without_colon,
            normalize_text(prefix),
        )

    # --------------------------------------------------------
    # No obvious heading structure.
    # --------------------------------------------------------

    return (
        without_colon,
        None,
    )


def parse_nested_numbered_item(
    number: str,
    body: str,
) -> dict:
    """
    Parse one numbered legal item.

    Possible result:

        {
            "number": "1",
            "category": "...",
            "intro": "...",
            "subpoints": [...]
        }

    or:

        {
            "number": "2",
            "category": "...",
            "text": "...",
            "subpoints": []
        }

    No Annex-specific knowledge is used.
    """

    body = normalize_text(body)

    item = {
        "number": number,
    }

    if not body:
        return item

    # --------------------------------------------------------
    # Does this numbered item contain a real nested
    # (a), (b), (c) sequence?
    # --------------------------------------------------------

    prefix, subpoints = (
        split_nested_subpoints(body)
    )

    if subpoints:

        category, intro = (
            split_category_heading(prefix)
        )

        if category:
            item["category"] = category

        if intro:
            item["intro"] = intro

        cleaned_subpoints = []

        for subpoint in subpoints:

            main_text, note = (
                split_subpoint_note(
                    subpoint["text"]
                )
            )

            subpoint["text"] = main_text

            if note:
                subpoint["note"] = note

            cleaned_subpoints.append(
                subpoint
            )

        item["subpoints"] = (
            cleaned_subpoints
        )

        return item

    # --------------------------------------------------------
    # No nested subpoints.
    #
    # Detect:
    #
    #     Category: description
    #
    # Example:
    #
    #     Critical infrastructure: AI systems...
    # --------------------------------------------------------

    colon_match = re.match(
        r"^([^:]{1,150}):\s*(.+)$",
        body,
    )

    if colon_match:

        category = normalize_text(
            colon_match.group(1)
        )

        description = normalize_text(
            colon_match.group(2)
        )

        item["category"] = category

        item["text"] = normalize_text(
            f"{category}: {description}"
        )

        item["subpoints"] = []

        references = extract_references(
            body
        )

        if references:
            item["references"] = references

        cited_act = extract_cited_act(
            body
        )

        if cited_act:
            item["cited_act"] = cited_act

        return item

    # --------------------------------------------------------
    # Plain numbered item.
    # --------------------------------------------------------

    item["text"] = body

    item["subpoints"] = []

    references = extract_references(
        body
    )

    if references:
        item["references"] = references

    cited_act = extract_cited_act(
        body
    )

    if cited_act:
        item["cited_act"] = cited_act

    return item


def parse_generic_nested_numbered_items(
    text: str,
) -> list[dict]:
    """
    Parse numbered legal items and automatically detect
    nested subpoints.

    This function is completely generic.

    It does not know:

        - which Annex it is parsing
        - which document it is parsing
        - which categories exist

    It simply detects the structure present in the text.
    """

    text = normalize_text(text)

    numbered_matches = (
        find_numbered_items(text)
    )

    if not numbered_matches:
        return []

    items = []

    for index, match in enumerate(
        numbered_matches
    ):

        if index + 1 < len(
            numbered_matches
        ):
            end = numbered_matches[
                index + 1
            ].start()
        else:
            end = len(text)

        body = text[
            match.end():end
        ].strip()

        if not body:
            continue

        item = parse_nested_numbered_item(
            match.group(1),
            body,
        )

        items.append(item)

    return items


# ============================================================
# Annex parsing
# ============================================================


def parse_annex(
    lines: list[str],
    annex_number: str,
) -> dict:
    """
    Parse an Annex.

    Supported structures:

        1. Section-based annexes
        2. Dash/dot lists
        3. Numbered lists
        4. Numbered lists with nested (a), (b), (c)
           subpoints
        5. Notes/exceptions attached to subpoints

    The parser is generic and does not contain
    Annex-specific logic.
    """

    annex_id_number = roman_to_int(
        annex_number
    )

    annex = {
        "type": "annex",
        "id": f"aiact:annex{annex_id_number}",
        "number": annex_number,
    }

    cleaned_lines = [
        clean_line(line)
        for line in lines
        if clean_line(line)
    ]

    if not cleaned_lines:
        return annex

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    annex["title"] = normalize_text(
        cleaned_lines[0]
    )

    remaining_lines = cleaned_lines[1:]

    if not remaining_lines:
        return annex

    # --------------------------------------------------------
    # Section-based Annex
    #
    # Preserve existing behavior.
    # --------------------------------------------------------

    section_indexes = []

    for index, line in enumerate(
        remaining_lines
    ):
        if SECTION_RE.match(line):
            section_indexes.append(index)

    if section_indexes:

        sections = []

        for section_index, start in enumerate(
            section_indexes
        ):

            if (
                section_index + 1
                < len(section_indexes)
            ):
                end = section_indexes[
                    section_index + 1
                ]
            else:
                end = len(
                    remaining_lines
                )

            section_lines = (
                remaining_lines[
                    start:end
                ]
            )

            section_match = (
                SECTION_RE.match(
                    section_lines[0]
                )
            )

            if not section_match:
                continue

            label = section_match.group(
                1
            ).upper()

            section_title = normalize_text(
                section_match.group(2)
            )

            section = {
                "label": label,
                "title": section_title,
                "items": [],
            }

            item_text = normalize_text(
                " ".join(
                    section_lines[1:]
                )
            )

            section_items = (
                parse_generic_nested_numbered_items(
                    item_text
                )
            )

            if section_items:
                section["items"] = (
                    section_items
                )

            sections.append(section)

        annex["sections"] = sections

        return annex

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Check numbered structure BEFORE checking dash lists.
    #
    # This is the key fix.
    #
    # Annex III is:
    #
    #     intro
    #     1. ...
    #     2. ...
    #     3. ...
    #
    # We must identify the "1." boundary first.
    # --------------------------------------------------------

    remaining_text = normalize_text(
        " ".join(remaining_lines)
    )

    numbered_matches = (
        find_numbered_items(
            remaining_text
        )
    )

    if numbered_matches:

        first_numbered_match = (
            numbered_matches[0]
        )

        # ----------------------------------------------------
        # Everything before the first numbered item is the
        # actual annex introduction.
        # ----------------------------------------------------

        intro = remaining_text[
            :first_numbered_match.start()
        ].strip()

        if intro:

            annex["intro"] = normalize_text(
                intro
            )

            references = (
                parse_annex_references(
                    intro
                )
            )

            if references:
                annex["references"] = (
                    references
                )

        # ----------------------------------------------------
        # Parse the numbered items.
        # ----------------------------------------------------

        numbered_text = remaining_text[
            first_numbered_match.start():
        ]

        items = (
            parse_generic_nested_numbered_items(
                numbered_text
            )
        )

        if items:
            annex["items"] = items

        return annex

    # --------------------------------------------------------
    # No numbered structure.
    #
    # Now check dash/dot lists.
    # --------------------------------------------------------

    list_matches = list(
        ANNEX_DASH_ITEM_RE.finditer(
            remaining_text
        )
    )

    if list_matches:

        intro = remaining_text[
            :list_matches[0].start()
        ].strip()

        list_text = remaining_text[
            list_matches[0].start():
        ].strip()

        if intro:

            annex["intro"] = normalize_text(
                intro
            )

            references = (
                parse_annex_references(
                    intro
                )
            )

            if references:
                annex["references"] = (
                    references
                )

        items = split_dash_list_items(
            list_text
        )

        if items:
            annex["items"] = items

        return annex

    # --------------------------------------------------------
    # No recognized list structure.
    #
    # Preserve the text rather than dropping it.
    # --------------------------------------------------------

    annex["text"] = remaining_text

    return annex


# ============================================================
# Chapter parsing
# ============================================================


def extract_chapter(
    number: str,
    title: str | None,
) -> dict:

    chapter = {
        "number": number.upper(),
    }

    if title:
        chapter["title"] = normalize_text(
            title
        )

    return chapter


# ============================================================
# Document structure parsing
# ============================================================


def parse_document(
    markdown: str,
) -> list[dict]:
    """
    Parse the complete Markdown document into legal elements.

    The parser recognizes:

        CHAPTER
        Article
        ANNEX
    """

    raw_lines = markdown.splitlines()

    lines = []

    for line in raw_lines:
        cleaned = clean_line(line)

        if cleaned:
            lines.append(cleaned)

    elements = []

    current_chapter = None

    index = 0

    while index < len(lines):
        line = lines[index]

        # ----------------------------------------------------
        # Chapter
        # ----------------------------------------------------

        chapter_match = CHAPTER_RE.match(
            line
        )

        if chapter_match:
            chapter_number = (
                chapter_match.group(1).upper()
            )

            chapter_title = None

            if (
                index + 1 < len(lines)
                and not CHAPTER_RE.match(
                    lines[index + 1]
                )
                and not ARTICLE_RE.match(
                    lines[index + 1]
                )
                and not ANNEX_RE.match(
                    lines[index + 1]
                )
            ):
                chapter_title = lines[
                    index + 1
                ]

                index += 1

            current_chapter = (
                extract_chapter(
                    chapter_number,
                    chapter_title,
                )
            )

            index += 1
            continue

        # ----------------------------------------------------
        # Article
        # ----------------------------------------------------

        article_match = ARTICLE_RE.match(
            line
        )

        if article_match:
            article_number = (
                article_match.group(1)
            )

            article_lines = []

            index += 1

            while index < len(lines):
                next_line = lines[index]

                if CHAPTER_RE.match(
                    next_line
                ):
                    break

                if ARTICLE_RE.match(
                    next_line
                ):
                    break

                if ANNEX_RE.match(
                    next_line
                ):
                    break

                article_lines.append(
                    next_line
                )

                index += 1

            article = parse_article(
                article_lines,
                article_number,
                current_chapter,
            )

            elements.append(article)

            continue

        # ----------------------------------------------------
        # Annex
        # ----------------------------------------------------

        annex_match = ANNEX_RE.match(
            line
        )

        if annex_match:
            annex_number = (
                annex_match.group(1).upper()
            )

            annex_lines = []

            index += 1

            while index < len(lines):
                next_line = lines[index]

                if CHAPTER_RE.match(
                    next_line
                ):
                    break

                if ARTICLE_RE.match(
                    next_line
                ):
                    break

                if ANNEX_RE.match(
                    next_line
                ):
                    break

                annex_lines.append(
                    next_line
                )

                index += 1

            annex = parse_annex(
                annex_lines,
                annex_number,
            )

            elements.append(annex)

            continue

        index += 1

    return elements


# ============================================================
# File handling
# ============================================================


def parse_structure_file(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Read cleaned Markdown, parse legal structure,
    and save JSON.
    """

    markdown = input_path.read_text(
        encoding="utf-8"
    )

    elements = parse_document(
        markdown
    )

    output = {
        "instrument": INSTRUMENT,
        "elements": elements,
    }

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Input:   {input_path}")
    print(f"Output:  {output_path}")
    print(
        f"Elements parsed: {len(elements)}"
    )
    print(
        "Legal structure extraction completed."
    )


# ============================================================
# Main
# ============================================================


if __name__ == "__main__":

    input_file = Path(
        "data/extracted/"
        "eli_reg_2024_1689_oj_EN_TXT.clean.md"
    )

    output_file = Path(
        "data/extracted/"
        "eli_reg_2024_1689_oj_EN_TXT.structure.json"
    )

    parse_structure_file(
        input_path=input_file,
        output_path=output_file,
    )