import argparse
import sys
from pathlib import Path
import json
import re
from datetime import datetime

# Allow `python src/processing/legal_structure.py` to import the
# shared metadata module even though it's run as a loose script
# rather than as part of the `src` package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.docmeta import (  # noqa: E402
    DocumentMetadata,
    load_metadata,
    list_source_stems,
)
from src.processing.generic_structure import parse_table  # noqa: E402

EXTRACTED_DIR = Path("data/extracted")

# A control character used as a placeholder for a Markdown table while
# the surrounding text goes through clean_line()/normalize_text(). It
# cannot occur in real document text, and survives clean_line() intact
# (no '#', '*' or leading/trailing whitespace to strip), so a table's
# position among chapters/articles/annexes is preserved until
# parse_article()/parse_annex() pull the real table block back out.
TABLE_PLACEHOLDER_RE = re.compile(r"^\x00TABLE(\d+)\x00$")


# ============================================================
# Document metadata
#
# NOTE: this used to be a hardcoded AI-Act-only constant here.
# Document identity (title/celex/eli/id prefix/...) is now supplied
# per-document via data/source/<stem>.meta.json and passed into
# parse_document()/parse_structure_file() — see src/common/docmeta.py.
# ============================================================


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

# A nested sub-list inside a point (e.g. "(h) ... following: (i) ...;
# (ii) ...;") uses lower-case roman numerals. "(i)" alone is
# indistinguishable from the single letter "i" by regex, and can even
# coincidentally be the alphabetically-expected next top-level letter
# (e.g. straight after point "(h)"). It is only recognisable as a
# nested list's *start* by what follows it: a genuine top-level point
# is never followed shortly after by "(ii)" (two-letter parenthesised
# roman numerals never occur as top-level point markers in this
# document's convention). Used to keep such a match out of the
# top-level sequence in get_sequential_point_matches() below.
ROMAN_SUBLIST_CONTINUATION_RE = re.compile(
    r"\((ii|iii|iv|vi{1,3}|ix|xi{1,3})\)",
    re.IGNORECASE,
)


def _starts_roman_sublist(text: str, after: int, window: int = 400) -> bool:
    return bool(
        ROMAN_SUBLIST_CONTINUATION_RE.search(text[after : after + window])
    )


# A nested list's own markers, once correctly separated from the outer
# a/b/c/... sequence above, need their own parser: roman numerals
# don't start at "a" (POINT_MARKER_RE / get_sequential_point_matches
# only recognise sequences starting at "a"), they start at "i".
ROMAN_POINT_MARKER_RE = re.compile(
    r"\((i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii)\)\s*",
    re.IGNORECASE,
)

ROMAN_NUMERAL_SEQUENCE = [
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii",
]


def get_sequential_roman_matches(text: str) -> list[re.Match]:
    """Same idea as get_sequential_point_matches(), for a nested
    roman-numeral sub-list: "(i) ... (ii) ... (iii) ...". Only a run
    starting at (i) and incrementing through the roman sequence
    counts; anything else is skipped, not treated as a break."""

    matches = list(ROMAN_POINT_MARKER_RE.finditer(text))

    if not matches:
        return []

    valid_matches: list[re.Match] = []

    for match in matches:
        label = match.group(1).lower()

        if not valid_matches:
            if label == "i":
                valid_matches.append(match)

            continue

        previous_label = valid_matches[-1].group(1).lower()
        previous_index = ROMAN_NUMERAL_SEQUENCE.index(previous_label)

        expected = (
            ROMAN_NUMERAL_SEQUENCE[previous_index + 1]
            if previous_index + 1 < len(ROMAN_NUMERAL_SEQUENCE)
            else None
        )

        if expected and label == expected:
            valid_matches.append(match)

    return valid_matches


def split_nested_roman_subpoints(text: str) -> tuple[str, list[dict]]:
    """Roman-numeral counterpart of split_nested_subpoints()."""

    text = normalize_text(text)
    matches = get_sequential_roman_matches(text)

    if not matches:
        return text, []

    prefix = text[: matches[0].start()].strip()
    subpoints = []

    for index, match in enumerate(matches):
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )

        subpoint_text = text[start:end].strip()

        if not subpoint_text:
            continue

        subpoint = {
            "label": match.group(1).lower(),
            "text": normalize_text(subpoint_text),
        }

        references = extract_references(subpoint_text)

        if references:
            subpoint["references"] = references

        subpoints.append(subpoint)

    return prefix, subpoints


def split_nested_subpoints_any(text: str) -> tuple[str, list[dict]]:
    """
    Try a lettered nested sub-list first ("(a) ... (b) ..."), then a
    roman-numeral one ("(i) ... (ii) ..."), which is the other marker
    convention this document uses for a point's own nested list.
    Returns whichever actually found subpoints.
    """

    prefix, subpoints = split_nested_subpoints(text)

    if subpoints:
        return prefix, subpoints

    return split_nested_roman_subpoints(text)

# The PDF->Markdown conversion sometimes renders a point marker as a
# Markdown bullet, e.g. "- (b) prohibitions ...", even though the
# source PDF has no such bullet (only the first point in a sequence,
# "(a) ...", is spared). Left in place, that leading "- " sits right
# before POINT_MARKER_RE's match and gets sliced onto the END of the
# *previous* point's text instead of being dropped, e.g. "...Union; -"
# where the source just says "...Union;". Stripped before point
# splitting runs, on the joined body text.
BULLET_BEFORE_POINT_RE = re.compile(
    r"[-\u2013\u2014\u2022\u00b7]\s+(?=\([a-zA-Z0-9]+\)\s)"
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

    Also drops a spurious Markdown bullet inserted by the PDF->Markdown
    conversion directly before a point marker (see BULLET_BEFORE_POINT_RE)
    — this is conversion noise, not legal wording, and left in place it
    gets sliced onto the end of the *previous* point's text by
    split_legal_points() below.
    """

    text = text.replace("\u00a0", " ")
    text = text.replace("\u2009", " ")
    text = text.replace("\u200a", " ")
    text = text.replace("\u202f", " ")

    text = BULLET_BEFORE_POINT_RE.sub("", text)

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

        ANNEX II -> <doc_id>:annex2
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

        is_ambiguous_roman_start = (
            label in ("i", "v", "x")
            and _starts_roman_sublist(text, match.end())
        )

        if label == expected and not is_ambiguous_roman_start:
            valid_matches.append(match)

        # Otherwise, do NOT break — just skip this match. A point can
        # contain its own nested sub-list, e.g.
        # "(h) ... following: (i) ...; (ii) ...". Two things can go
        # wrong if a nested marker isn't a genuine continuation:
        #   - its label doesn't match `expected` at all (e.g. a
        #     nested "(i)" appearing right after point "(c)", where
        #     "(d)" is expected), or
        #   - its label *does* coincidentally match `expected` (e.g.
        #     "(i)" straight after point "(h)"), but it's followed
        #     shortly by "(ii)", which never happens for a genuine
        #     top-level point in this document's convention.
        # Either way, skipping it (instead of aborting the whole scan)
        # lets the real continuation — wherever it occurs — still be
        # found, and leaves the nested marker to be re-detected as a
        # sub-list inside the *containing* point's own text by
        # split_legal_points() below, instead of being lost or
        # truncating everything after it.

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
        }

        # A point can itself introduce a nested roman-numeral sub-list
        # (see ROMAN_SUBLIST_CONTINUATION_RE): "(h) ... following:
        # (i) ...; (ii) ...". get_sequential_point_matches() above
        # keeps such nested markers out of the *outer* a/b/c/...
        # sequence, so they end up here, inside this point's own
        # sliced text — recurse into it the same way an Annex's
        # numbered item detects its own nested subpoints (see
        # split_nested_subpoints / parse_nested_numbered_item).
        nested_prefix, subpoints = split_nested_subpoints_any(
            point_text
        )

        if subpoints:
            point["text"] = normalize_text(nested_prefix)
            point["subpoints"] = subpoints
        else:
            point["text"] = normalize_text(point_text)

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
# Embedded Markdown tables
#
# A legal document is not always pure prose: an Annex can carry a
# genuine table (e.g. a list of items in tabular form). Tables are
# pulled out of the raw Markdown *before* clean_line()/normalize_text()
# run (which would destroy row/column structure and bold markers),
# replaced with a placeholder line, and spliced back in as proper
# "table" blocks once parse_article()/parse_annex() reach them.
# ============================================================


def extract_tables_from_markdown(
    raw_lines: list[str],
) -> tuple[list[str], dict[int, dict]]:
    """
    Replace every run of Markdown table lines ("| ... |") in
    `raw_lines` with a single placeholder line, using the same
    `parse_table` normalization as generic_structure.py (paired
    grids, key/value pairs, ordinary header+rows).

    Returns (lines_with_placeholders, {placeholder_id: table_block}).
    """

    tables: dict[int, dict] = {}
    out_lines: list[str] = []
    counter = 0
    index = 0

    while index < len(raw_lines):
        line = raw_lines[index]

        if line.strip().startswith("|"):
            block_lines = []

            while index < len(raw_lines) and raw_lines[index].strip().startswith("|"):
                block_lines.append(raw_lines[index])
                index += 1

            table = parse_table(block_lines)

            if table:
                counter += 1
                tables[counter] = table
                out_lines.append(f"\x00TABLE{counter}\x00")

            continue

        out_lines.append(line)
        index += 1

    return out_lines, tables


def pop_table_blocks(
    lines: list[str],
    tables: dict[int, dict],
) -> tuple[list[str], list[dict]]:
    """
    Remove placeholder lines from `lines`, returning the remaining
    lines plus the referenced table blocks, in document order.

    Table blocks are appended at the end of an Article's/Annex's
    other blocks rather than spliced back into their exact position:
    the surrounding text is joined into one string for paragraph/point
    parsing, and a table doesn't parse as legal prose. For a legal
    element this ordering loss is minor (tables are rare inside
    Articles/Annexes and usually stand alone); a document that is
    mostly tabular should go through the generic structure path
    instead (see src/processing/structure.py), which preserves order.
    """

    remaining = []
    found: list[dict] = []

    for line in lines:
        match = TABLE_PLACEHOLDER_RE.match(line.strip())

        if match:
            table = tables.get(int(match.group(1)))

            if table:
                found.append(table)

            continue

        remaining.append(line)

    return remaining, found


# ============================================================
# Unified block output
#
# Both legal elements (Article/Annex, parsed below into
# paragraphs/points/items/sections) and generic elements (see
# generic_structure.py, parsed into paragraph/list/table blocks
# directly) end up exposing the *same* "blocks" field:
#
#     [{"type": "paragraph", "text": ...},
#      {"type": "list", "ordered": bool, "items": [...]},
#      {"type": "table", "kind": ..., "rows": [...]}]
#
# so a chunker can walk elements/blocks the same way regardless of
# which parser produced them. This section only adapts the *existing*
# legal parse tree (paragraphs/points/items/sections/closing, built by
# parse_article/parse_annex below, unchanged) into that shape; it does
# not reparse anything.
# ============================================================


def _item_label(node: dict) -> str | None:
    if node.get("number") is not None:
        return f"{node['number']}."

    if node.get("label"):
        return f"({node['label']})"

    return None


def _node_text(node: dict) -> str:
    """
    The descriptive text of a point/item/section node. Different
    parsers in this file name it differently depending on structure
    (a plain point: "text"; an annex numbered item: "category" —
    see parse_nested_numbered_item() below; a dash/section intro:
    "intro"), so every reader of a node's text goes through here
    instead of picking one key and silently dropping the others.
    """

    return node.get("text") or node.get("category") or node.get("intro") or ""


def _render_item_text(node: dict) -> str:
    label = _item_label(node)
    text = _node_text(node)

    if node.get("note"):
        text = f"{text} ({node['note']})" if text else str(node["note"])

    return f"{label} {text}".strip() if label else text


def _has_nested_structure(node: dict) -> bool:
    return any(
        node.get(key)
        for key in ("items", "points", "subpoints", "sections")
    )


def _blocks_from_item_list(nodes: list[dict]) -> list[dict]:
    """A list of point/item dicts -> one list block, or, if any item
    has its own nested structure, a header + nested blocks per item."""

    if not nodes:
        return []

    if not any(_has_nested_structure(n) for n in nodes):
        ordered = any(n.get("number") is not None for n in nodes)
        items = [_render_item_text(n) for n in nodes]
        items = [i for i in items if i]

        return (
            [{"type": "list", "ordered": ordered, "items": items}]
            if items
            else []
        )

    blocks = []

    for node in nodes:
        blocks.extend(_blocks_from_node(node))

    return blocks


def _blocks_from_node(node: dict) -> list[dict]:
    """
    A single item/section/paragraph dict -> its blocks, recursively.

    A node with nested content (points/items/subpoints/sections) gets a
    header paragraph (label + title/intro) followed by its children's
    blocks. A leaf node (no nested content) — even one sitting next to
    siblings that *do* have nested content, e.g. a numbered list where
    only some items have subpoints — gets a single paragraph with its
    label and its own text; that text must not be dropped here just
    because a sibling has children.
    """

    blocks = []
    label = _item_label(node)
    has_nested = _has_nested_structure(node)

    if has_nested:
        header_bits = [b for b in (label, node.get("title"), _node_text(node)) if b]

        if header_bits:
            blocks.append({"type": "paragraph", "text": " ".join(header_bits)})
    elif node.get("title") and not _node_text(node):
        # A leaf with a heading but no body text of its own (e.g. an
        # empty section/point that was only ever a label + title).
        bits = [b for b in (label, node.get("title")) if b]

        if bits:
            blocks.append({"type": "paragraph", "text": " ".join(bits)})
    else:
        # Plain leaf item: _render_item_text() already prepends the
        # label ("1." / "(a)") to node["text"].
        text = _render_item_text(node)

        if text.strip():
            blocks.append({"type": "paragraph", "text": text})

    for key in ("points", "items", "subpoints"):
        if node.get(key):
            blocks.extend(_blocks_from_item_list(node[key]))

    if node.get("sections"):
        for section in node["sections"]:
            blocks.extend(_blocks_from_node(section))

    return blocks


def legal_element_to_blocks(element: dict) -> list[dict]:
    """
    Convert an already-parsed Article or Annex dict (as built by
    parse_article()/parse_annex()) into the common block list.
    """

    blocks = []

    if element.get("intro"):
        blocks.append({"type": "paragraph", "text": element["intro"]})

    if element.get("text"):
        blocks.append({"type": "paragraph", "text": element["text"]})

    for paragraph in element.get("paragraphs", []):
        label = f"{paragraph['number']}." if paragraph.get("number") else None

        if paragraph.get("text"):
            text = paragraph["text"]
            blocks.append(
                {
                    "type": "paragraph",
                    "text": f"{label} {text}".strip() if label else text,
                }
            )
        elif paragraph.get("intro"):
            text = paragraph["intro"]
            blocks.append(
                {
                    "type": "paragraph",
                    "text": f"{label} {text}".strip() if label else text,
                }
            )

        if paragraph.get("points"):
            blocks.extend(_blocks_from_item_list(paragraph["points"]))

    if element.get("items"):
        blocks.extend(_blocks_from_item_list(element["items"]))

    for section in element.get("sections", []):
        blocks.extend(_blocks_from_node(section))

    if element.get("closing"):
        blocks.append(
            {"type": "paragraph", "text": render_closing_text(element["closing"])}
        )

    return blocks


def render_closing_text(closing) -> str:
    """parse_closing() returns either a plain string or a structured
    dict ({"place", "date", "signatories", ...}); render either as text."""

    if isinstance(closing, str):
        return closing

    if isinstance(closing, dict):
        parts = []

        if closing.get("place") or closing.get("date"):
            parts.append(
                f"Done at {closing.get('place', '')}, "
                f"{closing.get('date', '')}".strip().strip(",")
            )

        for signatory in closing.get("signatories", []):
            if isinstance(signatory, dict):
                parts.append(", ".join(str(v) for v in signatory.values() if v))
            else:
                parts.append(str(signatory))

        return " ".join(p for p in parts if p)

    return str(closing)


def assign_block_ids(element: dict) -> None:
    for number, block in enumerate(element.get("blocks", []), start=1):
        block["id"] = f"{element['id']}.b{number}"


# ============================================================
# Article parsing
# ============================================================


def parse_article(
    lines: list[str],
    article_number: str,
    chapter: dict | None,
    id_prefix: str,
    tables: dict[int, dict] | None = None,
) -> dict:
    """
    Parse an Article block.

    Existing behavior is preserved:
        - numbered paragraphs
        - unnumbered paragraphs
        - legal points
        - closing/signatures

    `id_prefix` is the document's short slug (e.g. "aiact"), used to
    build a stable, document-scoped element ID. `tables` (see
    extract_tables_from_markdown) resolves any table placeholders in
    `lines`; the resulting table blocks are appended to article["blocks"].
    """

    article = {
        "type": "article",
        "id": f"{id_prefix}:art{article_number}",
        "number": article_number,
    }

    if chapter:
        article["chapter"] = chapter

    lines, table_blocks = pop_table_blocks(lines, tables or {})

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
        # Some articles (e.g. Article 3, "Definitions") have no "1."
        # paragraph numbering at all — the whole body is a top-level
        # "(1) ... (2) ... (3) ..." list. Left to
        # parse_unnumbered_article_body(), a lettered sub-list nested
        # inside just ONE of those numbered items (e.g. definition
        # (44) has its own "(a) ...; (b) ...;") gets mistaken for the
        # *entire article's* point structure, since that's the first
        # "(a)" found anywhere in the text — corrupting/duplicating
        # everything from there to the end of the article. Prefer the
        # numbered-list reading whenever one is actually present.
        intro, items = parse_paren_numbered_items(body)

        if items:
            article["intro"] = intro
            article["items"] = items
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

    article["blocks"] = legal_element_to_blocks(article) + table_blocks
    assign_block_ids(article)

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


PAREN_NUMBERED_ITEM_RE = re.compile(r"(?:^|\s)\((\d+)\)\s+")


def get_sequential_paren_number_matches(
    text: str,
    minimum_length: int = 3,
) -> list[re.Match]:
    """
    Find a genuine "(1) ... (2) ... (3) ..." top-level list, e.g. the
    definitions in Article 3. Mirrors get_sequential_point_matches():
    only a run starting at (1) and incrementing by exactly 1 each time
    counts; a mismatched number (e.g. an unrelated cross-reference like
    "Article 4, point (1)") is skipped rather than aborting the scan,
    so the real continuation can still be found.

    `minimum_length` guards against a body that merely happens to
    contain one or two incidental "(N)" references — e.g. "(1) of
    Article 4" — being mistaken for a real top-level numbered list.
    Requiring several in a row is what distinguishes an actual
    definitions-style list from citation noise.
    """

    matches = list(PAREN_NUMBERED_ITEM_RE.finditer(text))

    if not matches:
        return []

    valid_matches: list[re.Match] = []

    for match in matches:
        number = int(match.group(1))

        if not valid_matches:
            if number == 1:
                valid_matches.append(match)

            continue

        expected = int(valid_matches[-1].group(1)) + 1

        if number == expected:
            valid_matches.append(match)

        # else: skip, don't abort — an incidental "(N)" reference
        # elsewhere in the text shouldn't derail a real list that
        # resumes later at the correct number.

    if len(valid_matches) < minimum_length:
        return []

    return valid_matches


def parse_paren_numbered_items(text: str) -> tuple[str, list[dict]]:
    """
    Parse a "(1) ... (2) ... (3) ..." top-level list (e.g. Article 3's
    definitions), returning (intro, items). Each item is parsed with
    parse_nested_numbered_item(), which already generically detects
    whether that single item contains its own nested (a)/(b)/(c)
    sub-list (e.g. definition (44) in Article 3) — no document- or
    article-specific knowledge is used here.
    """

    matches = get_sequential_paren_number_matches(text)

    if not matches:
        return text.strip(), []

    intro = text[: matches[0].start()].strip()
    items = []

    for index, match in enumerate(matches):
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )

        body = text[start:end].strip()

        if not body:
            continue

        items.append(
            parse_nested_numbered_item(match.group(1), body)
        )

    return intro, items


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
        split_nested_subpoints_any(body)
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
    id_prefix: str,
    tables: dict[int, dict] | None = None,
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

    `id_prefix` is the document's short slug (e.g. "aiact"), used to
    build a stable, document-scoped element ID. `tables` (see
    extract_tables_from_markdown) resolves any table placeholders in
    `lines`; the resulting table blocks are appended to annex["blocks"].
    """

    annex_id_number = roman_to_int(
        annex_number
    )

    annex = {
        "type": "annex",
        "id": f"{id_prefix}:annex{annex_id_number}",
        "number": annex_number,
    }

    lines, table_blocks = pop_table_blocks(lines, tables or {})

    def finish(annex: dict) -> dict:
        annex["blocks"] = legal_element_to_blocks(annex) + table_blocks
        assign_block_ids(annex)
        return annex

    cleaned_lines = [
        clean_line(line)
        for line in lines
        if clean_line(line)
    ]

    if not cleaned_lines:
        return finish(annex)

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    annex["title"] = normalize_text(
        cleaned_lines[0]
    )

    remaining_lines = cleaned_lines[1:]

    if not remaining_lines:
        return finish(annex)

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

        return finish(annex)

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

        return finish(annex)

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

        return finish(annex)

    # --------------------------------------------------------
    # No recognized list structure.
    #
    # Preserve the text rather than dropping it.
    # --------------------------------------------------------

    annex["text"] = remaining_text

    return finish(annex)


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
    id_prefix: str,
) -> list[dict]:
    """
    Parse the complete Markdown document into legal elements.

    The parser recognizes:

        CHAPTER
        Article
        ANNEX

    `id_prefix` is the document's short slug (e.g. "aiact"), used to
    build stable, document-scoped element IDs so multiple documents
    in the same store never collide (e.g. "aiact:art5" vs "gdpr:art5").
    """

    raw_lines, tables = extract_tables_from_markdown(
        markdown.splitlines()
    )

    lines = []

    for line in raw_lines:
        # A table placeholder must survive untouched: clean_line()
        # would otherwise be harmless here too, but skip it explicitly
        # for clarity rather than relying on that.
        if TABLE_PLACEHOLDER_RE.match(line.strip()):
            lines.append(line.strip())
            continue

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
                id_prefix,
                tables,
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
                id_prefix,
                tables,
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
    metadata: DocumentMetadata,
) -> None:
    """
    Read cleaned Markdown, parse legal structure,
    and save JSON.

    `metadata` supplies both the "instrument" block written into the
    output JSON and the `id_prefix` (metadata.doc_id) used to build
    stable, document-scoped element IDs — see DocumentMetadata in
    src/common/docmeta.py.
    """

    markdown = input_path.read_text(
        encoding="utf-8"
    )

    elements = parse_document(
        markdown,
        id_prefix=metadata.doc_id,
    )

    output = {
        "instrument": metadata.as_instrument(),
        "structure_type": "legal",
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
    print(f"Doc ID:  {metadata.doc_id}")
    print(
        f"Elements parsed: {len(elements)}"
    )
    print(
        "Legal structure extraction completed."
    )


def run_for_stem(stem: str, extracted_dir: Path = EXTRACTED_DIR) -> None:
    """Run structure extraction for a single document stem."""

    metadata = load_metadata(stem)

    input_path = extracted_dir / f"{stem}.clean.md"
    output_path = extracted_dir / f"{stem}.structure.json"

    if not input_path.exists():
        print(
            f"SKIP {stem}: no cleaned Markdown at {input_path} "
            "(run cleaner.py first)."
        )
        return

    parse_structure_file(
        input_path=input_path,
        output_path=output_path,
        metadata=metadata,
    )


# ============================================================
# Main
# ============================================================


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract chapters/articles/annexes from a cleaned "
            "Markdown document into structured JSON."
        )
    )

    parser.add_argument(
        "--stem",
        help=(
            "Document stem shared by data/source/<stem>.* and "
            "data/extracted/<stem>.*, e.g. 'eli_reg_2024_1689_oj_EN_TXT'. "
            "Its metadata is read from "
            "data/source/<stem>.meta.json (see src/common/docmeta.py)."
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
        help="Directory holding *.clean.md input / *.structure.json output.",
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
        build_arg_parser().error(
            "Provide --stem <name> or --all."
        )