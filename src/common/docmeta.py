"""
Per-document metadata for the ingestion pipeline.

Every document that moves through the pipeline is identified by its
filename "stem" — the same stem is reused for every artifact derived
from it:

    data/source/<stem>.<pdf|html|...>
    data/source/<stem>.meta.json          <- this module reads/writes this
    data/extracted/<stem>.md
    data/extracted/<stem>.json
    data/extracted/<stem>.links.json
    data/extracted/<stem>.clean.md
    data/extracted/<stem>.structure.json

The `.meta.json` file is what makes a document's identity (its ID
prefix, title, CELEX number, etc.) data instead of something hardcoded
in the parsing code. This lets the rest of the pipeline (cleaner,
legal_structure, future chunker/embedder) operate on ANY document
dropped into data/source/, not just Regulation (EU) 2024/1689.

Example data/source/eli_reg_2024_1689_oj_EN_TXT.meta.json:

    {
      "doc_id": "aiact",
      "title": "Regulation (EU) 2024/1689 (AI Act)",
      "celex": "32024R1689",
      "eli": "http://data.europa.eu/eli/reg/2024/1689/oj",
      "language": "EN",
      "publication_date": "2024-07-12",
      "source": "EUR-Lex",
      "source_url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng/pdf",
      "source_type": "regulation"
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

SOURCE_DIR = Path("data/source")
META_SUFFIX = ".meta.json"


@dataclass
class DocumentMetadata:
    # doc_id is the short, stable slug used as the element-ID prefix,
    # e.g. "aiact" -> "aiact:art1". Keep it short, lowercase, stable —
    # changing it later breaks any citations/links built on old IDs.
    doc_id: str
    title: str = ""
    celex: str | None = None
    eli: str | None = None
    language: str = "EN"
    publication_date: str | None = None
    source: str | None = None
    source_url: str | None = None
    source_type: str | None = None
    extra: dict = field(default_factory=dict)

    def as_instrument(self) -> dict:
        """The subset written into structure.json's 'instrument' block."""
        instrument = {
            "celex": self.celex,
            "eli": self.eli,
            "title": self.title,
            "language": self.language,
            "publication_date": self.publication_date,
        }
        return {k: v for k, v in instrument.items() if v is not None}


def slugify(value: str) -> str:
    """Turn a title/filename into a short lowercase id-safe slug."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "doc"


def meta_path(stem: str, source_dir: Path = SOURCE_DIR) -> Path:
    return source_dir / f"{stem}{META_SUFFIX}"


def load_metadata(stem: str, source_dir: Path = SOURCE_DIR) -> DocumentMetadata:
    """
    Load metadata for the document identified by `stem`.

    If data/source/<stem>.meta.json does not exist yet, this does NOT
    fail — it derives a minimal placeholder (doc_id = slug of the
    stem) and prints a warning, so new documents can be run through
    the pipeline immediately and given proper metadata later.
    """
    path = meta_path(stem, source_dir)

    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.setdefault("doc_id", slugify(raw.get("title") or stem))
        known = {f.name for f in DocumentMetadata.__dataclass_fields__.values()}
        extra = {k: v for k, v in raw.items() if k not in known}
        clean = {k: v for k, v in raw.items() if k in known and k != "extra"}
        return DocumentMetadata(**clean, extra=extra)

    print(
        f"WARNING: no metadata file at {path} — using a placeholder "
        f"derived from the filename. Create that file (see "
        f"src/common/docmeta.py docstring) or pass --doc-id/--title "
        f"to set it explicitly."
    )
    return DocumentMetadata(doc_id=slugify(stem), title=stem)


def save_metadata(
    stem: str,
    meta: DocumentMetadata,
    source_dir: Path = SOURCE_DIR,
) -> Path:
    path = meta_path(stem, source_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = asdict(meta)
    extra = payload.pop("extra", {}) or {}
    payload.update(extra)

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def list_source_stems(source_dir: Path = SOURCE_DIR) -> list[str]:
    """All distinct document stems currently in data/source/."""
    stems = set()
    for file in source_dir.glob("*"):
        if file.is_file() and not file.name.endswith(META_SUFFIX):
            stems.add(file.stem)
    return sorted(stems)
