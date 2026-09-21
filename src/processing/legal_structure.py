from pathlib import Path
import json
import re
from datetime import datetime

# Document metadata


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

# Annex list markers.
#
# Examples:
#   — terrorism,
#   – terrorism,
#   - terrorism,
#   • terrorism,
#   · terrorism,
#
# The marker itself is not stored in the final item.
ANNEX_DASH_MARKER_RE = re.compile(r"(?<!\w)(?:—|–|-|•|·)\s*")

# A stronger version used to detect a dash-list item when
# several items have been collapsed onto one line.
ANNEX_DASH_ITEM_RE = re.compile(r"(?:^|\s)(—|–|-|•|·)\s*")

# Used for references such as:
#   Article 5(1)
#   Article 5(1), first subparagraph, point (h)(iii)
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

# Used when the text explicitly says "Article 6(1)(a)"
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
    r"Done\s+at\s+(.+?),\s+" r"(\d{1,2}\s+\w+\s+\d{4})\.",
    re.IGNORECASE,
)

SIGNATURE_RE = re.compile(
    r"For\s+the\s+"
    r"(European Parliament|Council)"
    r"\s+"
    r"The\s+President"
    r"\s+"
    r"([A-Z]\.\s*[A-ZÀ-ÖØ-Ý]+)",
    re.IGNORECASE,
)


# Basic helpers


def clean_line(line: str) -> str:
    """
    Remove Markdown formatting that is useful during PDF
    extraction but not required in the structural JSON.
    """
    line = line.strip()

    # Markdown heading markers
    line = re.sub(r"^#{1,6}\s*", "", line)

    # Common emphasis markers
    line = line.replace("**", "")
    line = line.replace("__", "")

    # Markdown italic markers only at the edges.
    line = re.sub(r"^[_*]+", "", line)
    line = re.sub(r"[_*]+$", "", line)

    return line.strip()


def normalize_text(text: str) -> str:
    """
    Normalize whitespace without changing legal wording.
    """
    text = text.replace("\u00a0", " ")
    text = text.replace("\u2009", " ")
    text = text.replace("\u200a", " ")
    text = text.replace("\u202f", " ")

    text = re.sub(r"\s+", " ", text)

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


# Reference extraction


def extract_references(text: str) -> list[dict]:
    """
    Extract legal references from a piece of text.

    Examples:

        Article 5(1)

        Article 5(1), first subparagraph,
        point (h)(iii)

    Result:

        {
            "type": "article",
            "target": "5",
            "paragraph": "1",
            "subparagraph": "first",
            "point": "h",
            "subpoint": "iii"
        }

    References are extracted conservatively.
    """

    references = []

    # --------------------------------------------------------
    # Chapter + Section references
    # --------------------------------------------------------

    section_matches = list(SECTION_REFERENCE_RE.finditer(text))

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

        # Do not add a generic Chapter III reference when
        # "Chapter III Section 4" was already represented.
        is_section_reference = any(
            span[0] <= match.start() < span[1] for span in section_spans
        )

        if not is_section_reference:
            references.append(
                {
                    "type": "chapter",
                    "target": chapter_number,
                }
            )

    return references


# Point parsing


def looks_like_point_sequence(text: str) -> bool:
    """
    Detect whether text contains legal points such as:

        (a) ...
        (b) ...
        (c) ...

    We require a sequence starting at (a), because references
    such as Article 6(1)(a) must NOT be treated as paragraph
    points.
    """

    matches = list(POINT_MARKER_RE.finditer(text))

    if not matches:
        return False

    first_label = matches[0].group(1).lower()

    return first_label == "a"


def split_legal_points(text: str) -> tuple[str, list[dict]]:
    """
    Split:

        However: (a) first ... (b) second ... (c) third ...

    into:

        intro
        points

    Only sequences beginning with (a) are considered.

    This prevents references such as:

        Article 6(1)(a)

    from becoming points.
    """

    matches = list(POINT_MARKER_RE.finditer(text))

    if not matches:
        return text.strip(), []

    # Only treat this as a point list if it begins with (a).
    if matches[0].group(1).lower() != "a":
        return text.strip(), []

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

        if point_text:
            point = {
                "label": label,
                "text": normalize_text(point_text),
            }

            references = extract_references(point_text)

            if references:
                point["references"] = references

            points.append(point)

    return intro, points


# Paragraph parsing


def extract_paragraph(
    block: str,
    index: int,
) -> dict:
    """
    Parse a paragraph block.

    Important:
    We never invent a paragraph number.

    If the source has no explicit number:

        "number": None

    but we still maintain:

        "index": 1
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
            paragraph["intro"] = normalize_text(intro)

        paragraph["points"] = points
    else:
        paragraph["text"] = normalize_text(body)

    return paragraph


# Closing / signatures


def parse_closing(text: str) -> tuple[str, dict | None]:
    """
    Extract the formal closing block from an article.

    Example:

        Done at Brussels, 13 June 2024.

        For the European Parliament
        The President
        R. METSOLA

        For the Council
        The President
        M. MICHEL
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

    remaining = text[: match.start()].strip()

    after_done = text[match.end() :].strip()

    signature_matches = list(SIGNATURE_RE.finditer(after_done))

    for signature_match in signature_matches:
        body = signature_match.group(1)
        name = normalize_text(signature_match.group(2))

        closing["signatories"].append(
            {
                "body": body,
                "role": "President",
                "name": name,
            }
        )

    return remaining, closing


# Article parsing


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

    # --------------------------------------------------------
    # Find article title.
    # --------------------------------------------------------

    body_lines = []

    title = None

    for line in lines:
        line = clean_line(line)

        if not line:
            continue

        # If the title has not been found yet, the first
        # non-empty line is treated as the article title.
        if title is None:
            title = normalize_text(line)
            continue

        body_lines.append(line)

    if title:
        article["title"] = title

    # --------------------------------------------------------
    # Join body.
    # --------------------------------------------------------

    body = normalize_text(" ".join(body_lines))

    # --------------------------------------------------------
    # Closing.
    # --------------------------------------------------------

    body, closing = parse_closing(body)

    # --------------------------------------------------------
    # Paragraph splitting.
    #
    # Numbered paragraphs:
    #
    #   1. ...
    #   2. ...
    #
    # If there are no numbered paragraphs, preserve the
    # existing unnumbered behavior.
    # --------------------------------------------------------

    numbered_matches = list(
        re.finditer(
            r"(?:^|\s)(\d+)\.\s+",
            body,
        )
    )

    paragraphs = []

    if numbered_matches:
        blocks = []

        for index, match in enumerate(numbered_matches):
            start = match.start()

            if match.group(0).startswith(" "):
                start += 1

            content_start = match.end()

            if index + 1 < len(numbered_matches):
                end = numbered_matches[index + 1].start()
            else:
                end = len(body)

            paragraph_number = match.group(1)

            paragraph_text = body[content_start:end].strip()

            blocks.append(f"{paragraph_number}. {paragraph_text}")

        for index, block in enumerate(blocks, start=1):
            paragraphs.append(
                extract_paragraph(
                    block,
                    index,
                )
            )

    else:
        # ----------------------------------------------------
        # Unnumbered article body.
        #
        # Existing behavior is preserved, but we additionally
        # handle a common legal pattern:
        #
        #   Sentence.
        #   Sentence.
        #   However:
        #   (a) ...
        #   (b) ...
        #   Sentence after points.
        #
        # This is particularly important for Article 113.
        # ----------------------------------------------------

        paragraphs = parse_unnumbered_article_body(body)

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

    The function is intentionally conservative.

    It recognizes the common pattern:

        sentence.
        sentence.
        However:
        (a) ...
        (b) ...
        (c) ...
        sentence after points.

    It does not invent paragraph numbers.
    """

    body = normalize_text(body)

    if not body:
        return []

    # --------------------------------------------------------
    # Locate a point sequence.
    # --------------------------------------------------------

    point_matches = list(POINT_MARKER_RE.finditer(body))

    valid_point_matches = []

    if point_matches:
        for match in point_matches:
            label = match.group(1).lower()

            if not valid_point_matches:
                if label == "a":
                    valid_point_matches.append(match)
            else:
                previous_label = valid_point_matches[-1].group(1).lower()

                expected = chr(ord(previous_label) + 1)

                if label == expected:
                    valid_point_matches.append(match)
                else:
                    break

    # --------------------------------------------------------
    # If no real point sequence exists, the whole body is one
    # unnumbered paragraph.
    # --------------------------------------------------------

    if not valid_point_matches:
        return [
            {
                "index": 1,
                "number": None,
                "text": body,
            }
        ]

    # --------------------------------------------------------
    # Text before the point sequence.
    # --------------------------------------------------------

    before_points = body[: valid_point_matches[0].start()].strip()

    # Text after the point sequence.
    last_point_end = len(body)

    # Find where the final recognized point ends.
    final_match = valid_point_matches[-1]

    after_last_point = body[final_match.end() :]

    # --------------------------------------------------------
    # If the final point was followed by another point-like
    # reference, do not treat it as post-point text.
    #
    # At this stage the sequence has already been validated.
    # --------------------------------------------------------

    point_entries = []

    for index, match in enumerate(valid_point_matches):
        start = match.end()

        if index + 1 < len(valid_point_matches):
            end = valid_point_matches[index + 1].start()
        else:
            end = len(body)

        point_text = body[start:end].strip()

        point_entries.append(
            {
                "label": match.group(1).lower(),
                "text": normalize_text(point_text),
            }
        )

    # --------------------------------------------------------
    # The last point may contain a sentence that belongs to a
    # following unnumbered paragraph.
    #
    # For the current legal document, we recognize a strong
    # boundary:
    #
    #   ;
    #   This Regulation shall ...
    #
    # However, we avoid aggressive sentence splitting because
    # legal sentences must not be arbitrarily divided.
    # --------------------------------------------------------

    paragraphs = []

    # If there is clear text before the first point, it becomes
    # paragraph 1.
    if before_points:
        intro_text = normalize_text(before_points)

        # "However:" belongs with the point paragraph rather
        # than becoming a standalone paragraph.
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
                        "index": len(paragraphs) + 1,
                        "number": None,
                        "text": prefix_without_however,
                    }
                )

            point_paragraph = {
                "index": len(paragraphs) + 1,
                "number": None,
                "intro": "However:",
                "points": point_entries,
            }

            paragraphs.append(point_paragraph)

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

    # --------------------------------------------------------
    # Important special case:
    #
    # Article 113 contains text after the point sequence:
    #
    #   This Regulation shall be binding ...
    #
    # It must become a separate paragraph.
    #
    # We only split when the remaining text is clearly a new
    # sentence rather than continuation of the final point.
    # --------------------------------------------------------

    trailing = normalize_text(after_last_point)

    if trailing:
        # Remove the point text from the final point when
        # there is an obvious new legal sentence after it.
        #
        # This is deliberately conservative.
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
            # Usually the final point ends with ';' and the
            # following paragraph begins with a new sentence.
            point_part = trailing[: boundary_match.start() + 1].strip()

            following_part = trailing[boundary_match.start() + 1 :].strip()

            if point_part:
                point_entries[-1]["text"] = normalize_text(
                    point_entries[-1]["text"] + " " + point_part
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
            # No safe boundary detected, so keep the text with
            # the final point.
            if point_entries:
                point_entries[-1]["text"] = normalize_text(
                    point_entries[-1]["text"] + " " + trailing
                )

    # --------------------------------------------------------
    # Rebuild indexes after optional insertion.
    # --------------------------------------------------------

    for index, paragraph in enumerate(
        paragraphs,
        start=1,
    ):
        paragraph["index"] = index

    return paragraphs


# Annex list-item parsing


def split_dash_list_items(text: str) -> list[dict]:
    """
    Split an unnumbered legal list introduced by dash/dot
    markers.

    Supported markers:

        —
        –
        -
        •
        ·

    Example:

        — terrorism,
        — trafficking in human beings,
        — rape,

    becomes:

        [
            {"index": 1, "label": None, "text": "terrorism,"},
            {"index": 2, "label": None, "text": "trafficking in human beings,"},
            {"index": 3, "label": None, "text": "rape,"}
        ]

    It also handles PDF extraction where the entire list has
    been collapsed onto one line.
    """

    text = normalize_text(text)

    if not text:
        return []

    matches = list(ANNEX_DASH_ITEM_RE.finditer(text))

    if not matches:
        return []

    items = []

    for index, match in enumerate(matches):
        start = match.end()

        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(text)

        item_text = text[start:end].strip()

        if not item_text:
            continue

        items.append(
            {
                "index": len(items) + 1,
                "label": None,
                "text": normalize_text(item_text),
            }
        )

    return items


def parse_annex_references(
    intro: str,
) -> list[dict]:
    """
    Extract references from an annex introduction.

    This is intentionally generic because `intro` + `references`
    can occur in other legal structures too.
    """

    return extract_references(intro)


# Cited act parsing


def extract_cited_act(
    text: str,
) -> dict | None:
    """
    Extract a cited EU legal act from annex item text.

    Example:

        Directive 2006/42/EC of the European Parliament
        and of the Council of 17 May 2006 on machinery
        (OJ L 157, 9.6.2006, p. 24);

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

    match = pattern.search(normalize_text(text))

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

        # Avoid accidentally capturing large text blocks.
        if len(short_title) <= 120:
            cited_act["short_title"] = short_title

    oj_reference = match.group(7)

    if oj_reference:
        cited_act["oj_reference"] = oj_reference.strip()

    return cited_act


# Annex parsing


def parse_annex(
    lines: list[str],
    annex_number: str,
) -> dict:
    """
    Parse an Annex.

    Existing numbered-section behavior remains supported.

    Additional behavior:

        Annex II
        Title
        Intro:
        — item
        — item
        — item

    becomes:

        {
          "type": "annex",
          "id": "aiact:annex2",
          "number": "II",
          "title": "...",
          "intro": "...",
          "references": [...],
          "items": [...]
        }

    Annexes with sections continue to use:

        sections: [...]

    """

    annex_id_number = roman_to_int(annex_number)

    annex = {
        "type": "annex",
        "id": f"aiact:annex{annex_id_number}",
        "number": annex_number,
    }

    cleaned_lines = [clean_line(line) for line in lines if clean_line(line)]

    if not cleaned_lines:
        return annex

    # --------------------------------------------------------
    # Annex title
    # --------------------------------------------------------

    annex["title"] = normalize_text(cleaned_lines[0])

    remaining_lines = cleaned_lines[1:]

    # --------------------------------------------------------
    # First check for Section-based annexes.
    #
    # This preserves the existing Annex I behavior.
    # --------------------------------------------------------

    section_indexes = []

    for index, line in enumerate(remaining_lines):
        if SECTION_RE.match(line):
            section_indexes.append(index)

    if section_indexes:
        sections = []

        for section_index, start in enumerate(section_indexes):
            end = (
                section_indexes[section_index + 1]
                if section_index + 1 < len(section_indexes)
                else len(remaining_lines)
            )

            section_lines = remaining_lines[start:end]

            section_match = SECTION_RE.match(section_lines[0])

            if not section_match:
                continue

            label = section_match.group(1).upper()
            section_title = normalize_text(section_match.group(2))

            section = {
                "label": label,
                "title": section_title,
                "items": [],
            }

            item_lines = section_lines[1:]

            # Existing numbered items
            section_text = normalize_text(" ".join(item_lines))

            item_matches = list(
                re.finditer(
                    r"(?:^|\s)(\d+)\.\s+",
                    section_text,
                )
            )

            for item_index, match in enumerate(item_matches):
                if item_index + 1 < len(item_matches):
                    end_position = item_matches[item_index + 1].start()
                else:
                    end_position = len(section_text)

                item_text = section_text[match.end() : end_position].strip()

                item = {
                    "number": match.group(1),
                    "text": normalize_text(item_text),
                }

                cited_act = extract_cited_act(item["text"])

                if cited_act:
                    item["cited_act"] = cited_act

                section["items"].append(item)

            sections.append(section)

        annex["sections"] = sections

        return annex

    # --------------------------------------------------------
    # No sections.
    #
    # This is where Annex II lives.
    #
    # We support:
    #
    #   title
    #   intro
    #   references
    #   dash/dot list
    #
    # while preserving other existing annex behavior.
    # --------------------------------------------------------

    remaining_text = normalize_text(" ".join(remaining_lines))

    if not remaining_text:
        return annex

    # --------------------------------------------------------
    # Detect the beginning of an unnumbered dash/dot list.
    # --------------------------------------------------------

    list_matches = list(ANNEX_DASH_ITEM_RE.finditer(remaining_text))

    if list_matches:
        intro = remaining_text[: list_matches[0].start()].strip()

        list_text = remaining_text[list_matches[0].start() :].strip()

        if intro:
            annex["intro"] = normalize_text(intro)

            references = parse_annex_references(intro)

            if references:
                annex["references"] = references

        items = split_dash_list_items(list_text)

        if items:
            annex["items"] = items

        return annex

    # --------------------------------------------------------
    # Existing numbered-item behavior for annexes without
    # sections.
    # --------------------------------------------------------

    numbered_matches = list(
        re.finditer(
            r"(?:^|\s)(\d+)\.\s+",
            remaining_text,
        )
    )

    if numbered_matches:
        items = []

        for index, match in enumerate(numbered_matches):
            if index + 1 < len(numbered_matches):
                end = numbered_matches[index + 1].start()
            else:
                end = len(remaining_text)

            item_text = remaining_text[match.end() : end].strip()

            item = {
                "number": match.group(1),
                "text": normalize_text(item_text),
            }

            cited_act = extract_cited_act(item["text"])

            if cited_act:
                item["cited_act"] = cited_act

            items.append(item)

        if items:
            annex["items"] = items

        return annex

    # --------------------------------------------------------
    # If neither a dash-list nor numbered list exists, retain
    # the text rather than silently losing it.
    # --------------------------------------------------------

    annex["text"] = remaining_text

    return annex


# Chapter parsing


def extract_chapter(
    number: str,
    title: str | None,
) -> dict:
    chapter = {
        "number": number.upper(),
    }

    if title:
        chapter["title"] = normalize_text(title)

    return chapter


# Document structure parsing


def parse_document(
    markdown: str,
) -> list[dict]:
    """
    Parse the complete Markdown document into legal elements.

    The parser recognizes:

        CHAPTER
        Article
        ANNEX

    Existing article and annex behavior is preserved.
    """

    raw_lines = markdown.splitlines()

    # --------------------------------------------------------
    # Normalize lines.
    # --------------------------------------------------------

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

        chapter_match = CHAPTER_RE.match(line)

        if chapter_match:
            chapter_number = chapter_match.group(1).upper()

            chapter_title = None

            if (
                index + 1 < len(lines)
                and not CHAPTER_RE.match(lines[index + 1])
                and not ARTICLE_RE.match(lines[index + 1])
                and not ANNEX_RE.match(lines[index + 1])
            ):
                chapter_title = lines[index + 1]
                index += 1

            current_chapter = extract_chapter(
                chapter_number,
                chapter_title,
            )

            index += 1
            continue

        # ----------------------------------------------------
        # Article
        # ----------------------------------------------------

        article_match = ARTICLE_RE.match(line)

        if article_match:
            article_number = article_match.group(1)

            article_lines = []

            index += 1

            while index < len(lines):
                next_line = lines[index]

                if CHAPTER_RE.match(next_line):
                    break

                if ARTICLE_RE.match(next_line):
                    break

                if ANNEX_RE.match(next_line):
                    break

                article_lines.append(next_line)

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

        annex_match = ANNEX_RE.match(line)

        if annex_match:
            annex_number = annex_match.group(1).upper()

            annex_lines = []

            index += 1

            while index < len(lines):
                next_line = lines[index]

                if CHAPTER_RE.match(next_line):
                    break

                if ARTICLE_RE.match(next_line):
                    break

                if ANNEX_RE.match(next_line):
                    break

                annex_lines.append(next_line)

                index += 1

            annex = parse_annex(
                annex_lines,
                annex_number,
            )

            elements.append(annex)

            continue

        index += 1

    return elements


# File handling


def parse_structure_file(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Read cleaned Markdown, parse legal structure,
    and save JSON.
    """

    markdown = input_path.read_text(encoding="utf-8")

    elements = parse_document(markdown)

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
    print(f"Elements parsed: {len(elements)}")
    print("Legal structure extraction completed.")


# Main


if __name__ == "__main__":
    input_file = Path("data/extracted/eli_reg_2024_1689_oj_EN_TXT.clean.md")

    output_file = Path("data/extracted/eli_reg_2024_1689_oj_EN_TXT.structure.json")

    parse_structure_file(
        input_path=input_file,
        output_path=output_file,
    )
