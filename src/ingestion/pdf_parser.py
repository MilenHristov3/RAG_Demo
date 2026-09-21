from pathlib import Path
import json

import pymupdf
import pymupdf4llm


def extract_links(pdf_path: Path) -> list[dict]:
    """
    Extract links from a PDF.

    We preserve:
    - internal links (LINK_GOTO)
    - external URLs (LINK_URI)
    - other supported link types

    The result is stored as metadata and does not become
    part of the Markdown text.
    """

    links = []

    with pymupdf.open(pdf_path) as document:

        for page_number, page in enumerate(document, start=1):

            for link_number, link in enumerate(
                page.get_links(),
                start=1,
            ):

                link_data = {
                    "source_page": page_number,
                    "link_number": link_number,
                    "kind": link.get("kind"),
                    "from": {
                        "x0": link["from"].x0,
                        "y0": link["from"].y0,
                        "x1": link["from"].x1,
                        "y1": link["from"].y1,
                    },
                }

                # Internal link
                if link.get("kind") == pymupdf.LINK_GOTO:

                    link_data["type"] = "internal"

                    # PDF pages are 0-based internally.
                    # We store human-friendly 1-based page numbers.
                    if link.get("page") is not None:
                        link_data["target_page"] = link["page"] + 1

                    if link.get("to") is not None:
                        link_data["target_position"] = {
                            "x": link["to"].x,
                            "y": link["to"].y,
                        }

                # External URL
                elif link.get("kind") == pymupdf.LINK_URI:

                    link_data["type"] = "external"
                    link_data["uri"] = link.get("uri")

                # Other link types
                else:

                    link_data["type"] = "other"

                    if link.get("page") is not None:
                        link_data["target_page"] = link["page"] + 1

                    if link.get("uri"):
                        link_data["uri"] = link["uri"]

                    if link.get("file"):
                        link_data["file"] = link["file"]

                links.append(link_data)

    return links


def convert_pdf(
    input_path: Path,
    markdown_path: Path,
    json_path: Path,
    links_path: Path,
) -> None:
    """
    Convert a PDF into:

    1. Markdown
    2. Layout JSON
    3. Optional link metadata

    The original PDF is never modified.
    """

    print(f"Reading PDF: {input_path}")

    # PDF -> Markdown

    markdown = pymupdf4llm.to_markdown(
        str(input_path),
        header=False,
        footer=False,
    )

    # PDF -> layout JSON

    json_text = pymupdf4llm.to_json(str(input_path))

    # PDF -> links

    links = extract_links(input_path)

    # Create output directory

    markdown_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Save Markdown

    markdown_path.write_text(
        markdown,
        encoding="utf-8",
    )

    # Save layout JSON

    json_path.write_text(
        json_text,
        encoding="utf-8",
    )

    # Save links only if links exist

    if links:

        links_path.write_text(
            json.dumps(
                links,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print(f"Links found:    {len(links)}")
        print(f"Links saved:    {links_path}")

    else:

        # If an old links file exists because the document
        # previously contained links, remove it.
        if links_path.exists():
            links_path.unlink()

        print("Links found:    0")
        print("No links file created.")

    # Summary

    print()
    print("PDF conversion completed.")
    print()
    print(f"Markdown:       {markdown_path}")
    print(f"JSON:            {json_path}")
    print(f"Links:           {len(links)}")
