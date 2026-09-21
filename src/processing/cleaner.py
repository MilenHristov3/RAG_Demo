from pathlib import Path
import re

"""clean formatting/extraction noise without changing the legal wording"""

def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace while preserving Markdown structure.
    """

    # Normalize line endings
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Replace non-breaking spaces
    text = text.replace("\u00a0", " ")

    # Replace other common Unicode whitespace characters
    text = text.replace("\u2009", " ")  # thin space
    text = text.replace("\u200a", " ")  # hair space
    text = text.replace("\u202f", " ")  # narrow no-break space

    # Remove trailing whitespace from every line
    text = "\n".join(line.rstrip() for line in text.splitlines())

    return text


def normalize_superscripts(text: str) -> str:
    """
    Normalize HTML superscript tags produced by PDF extraction.

    Example:
        <sup>8</sup> -> 8

    We keep the actual number because it may correspond to a
    footnote or PDF link that is preserved separately in links.json.
    """

    text = re.sub(
        r"<sup>\s*(.*?)\s*</sup>",
        r"\1",
        text,
        flags=re.DOTALL,
    )

    return text


def remove_empty_markdown_lines(text: str) -> str:
    """
    Remove unnecessary empty Markdown formatting lines.

    This does not remove legal text.
    """

    lines = text.splitlines()

    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        # Remove completely empty emphasis markers
        if stripped in {"**", "__", "*", "_"}:
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def collapse_excessive_blank_lines(text: str) -> str:
    """
    Collapse 3+ consecutive blank lines into a single blank line.
    """

    return re.sub(r"\n{3,}", "\n\n", text)


def clean_markdown(text: str) -> str:
    """
    Main cleaning pipeline.

    The goal is to normalize extraction artifacts while preserving:
    - legal wording
    - Markdown headings
    - article numbering
    - paragraph numbering
    - lists
    - superscript reference numbers
    """

    text = normalize_whitespace(text)

    text = normalize_superscripts(text)

    text = remove_empty_markdown_lines(text)

    text = collapse_excessive_blank_lines(text)

    # Remove whitespace at the beginning and end of the document
    text = text.strip()

    return text


def clean_markdown_file(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Read a raw Markdown file, clean it, and save the result.
    """

    text = input_path.read_text(encoding="utf-8")

    cleaned_text = clean_markdown(text)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        cleaned_text,
        encoding="utf-8",
    )

    print(f"Input:   {input_path}")
    print(f"Output:  {output_path}")
    print("Cleaning completed.")


if __name__ == "__main__":
    input_file = Path(
        "data/extracted/eli_reg_2024_1689_oj_EN_TXT.md" #TODO change it to have option to choose file eventually or to accept file name and to keep it
    )

    output_file = Path(
        "data/extracted/eli_reg_2024_1689_oj_EN_TXT.clean.md"
    )

    clean_markdown_file(
        input_path=input_file,
        output_path=output_file,
    )

"""
    
Important: what it deliberately does not do

I would not make the cleaner responsible for:

detecting Article 1
detecting Paragraph 1
detecting CHAPTER I
changing # Article into a different heading level
splitting articles
removing footnote/reference numbers
removing legal numbering
modifying legal wording
identifying links
"""