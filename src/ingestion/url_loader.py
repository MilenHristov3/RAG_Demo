from pathlib import Path
from urllib.parse import urlparse

import requests


def download_url(
    url: str,
    output_dir: Path,
) -> tuple[Path, str]:

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print(f"Requesting: {url}")

    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml,"
                "application/pdf,"
                "text/plain,"
                "*/*"
            ),
        },
        allow_redirects=True,
    )

    print(f"Status:         {response.status_code}")
    print(f"Final URL:      {response.url}")

    response.raise_for_status()

    content_type = response.headers.get(
        "Content-Type",
        "",
    ).lower()

    print(f"Content-Type:   {content_type}")
    print(f"Bytes received: {len(response.content)}")

    extension = detect_extension(
        content_type=content_type,
        url=response.url,
    )

    filename = build_filename(
        response.url,
        extension,
    )

    output_path = output_dir / filename

    output_path.write_bytes(response.content)

    print(f"Saved to:       {output_path}")

    return output_path, content_type


def detect_extension(
    content_type: str,
    url: str,
) -> str:

    content_type = content_type.split(";")[0].strip()

    mapping = {
        "application/pdf": ".pdf",
        "text/html": ".html",
        "application/xhtml+xml": ".html",
        "text/plain": ".txt",
        "application/xml": ".xml",
        "text/xml": ".xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }

    if content_type in mapping:
        return mapping[content_type]

    parsed = urlparse(url)

    suffix = Path(parsed.path).suffix.lower()

    if suffix in {
        ".pdf",
        ".html",
        ".htm",
        ".txt",
        ".xml",
        ".docx",
    }:
        if suffix == ".htm":
            return ".html"

        return suffix

    return ".html"


def build_filename(
    url: str,
    extension: str,
) -> str:

    parsed = urlparse(url)

    name = Path(parsed.path).stem

    if not name:
        name = "downloaded_document"

    return f"{name}{extension}"
