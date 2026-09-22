# EU Regulatory Text RAG Pipeline

A production-grade pipeline for ingesting, structuring, and retrieving EU regulatory documents — starting with the EU AI Act (Regulation (EU) 2024/1689) as a reference implementation.

## Overview

This repository provides a complete **Retrieval-Augmented Generation (RAG) pipeline** tailored for EU legal texts. It transforms official PDFs from EUR-Lex into structured, queryable data while preserving the hierarchical legal structure (chapters, articles, paragraphs, points, annexes) and cross-references essential for accurate legal retrieval.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Ingest    │────▶│  Process    │────▶│  Structure   │────▶│   Store/Query    │
│  (PDF/HTML) │     │  (Clean)    │     │  (Parse)     │     │  (pgvector)      │
└─────────────┘     └─────────────┘     └──────────────┘     └──────────────────┘
```

### 1. Ingestion Layer (`src/ingestion/`)
- **`url_loader.py`** — Downloads documents from EUR-Lex (PDF, HTML, TXT, DOCX, XML) with proper headers and redirect handling
- **`pdf_parser.py`** — Converts PDFs to Markdown, layout JSON, and link metadata using `pymupdf4llm`
- **`converter.py`** — Interactive CLI for batch processing source files

### 2. Processing Layer (`src/processing/`)
- **`cleaner.py`** — Conservative Markdown cleaning: normalizes Unicode whitespace, removes extraction artifacts, converts `<sup>` tags, collapses blank lines — **never modifies legal wording**
- **`legal_structure.py`** — Core legal parser extracting:
  - **Chapters** (Roman numerals)
  - **Articles** with titles, numbered/unnumbered paragraphs, legal points `(a)`–`(z)`
  - **Annexes** (sectioned or dash-list format)
  - **Legal references** (e.g., `Article 5(1)`, `Chapter III Section 4`, `Annex II`)
  - **Cited acts** (Directives, Regulations with OJ references, dates)
  - **Closing blocks** (formal "Done at...", signatures)
  - Outputs structured JSON with stable IDs (`aiact:art1`, `aiact:annex2`)

### 3. Storage Layer (`src/db.py`)
- PostgreSQL + **pgvector** connection for vector embeddings and semantic search

## Data Flow

```
EUR-Lex PDF (data/source/)
       │
       ▼
Markdown + Layout JSON + Links JSON (data/extracted/)
       │
       ▼
Cleaned Markdown (.clean.md)
       │
       ▼
Structured Legal JSON (.structure.json)
       │
       ▼
PostgreSQL / pgvector  ──▶  RAG Retrieval
```

## Key Features

| Feature | Description |
|---------|-------------|
| **Legal fidelity** | Preserves article/paragraph/point numbering, never invents structure |
| **Cross-references** | Extracts `Article X(Y)`, `Chapter Z`, `Annex N` links as structured metadata |
| **Cited acts** | Parses Directive/Regulation citations with OJ references and dates |
| **Annex support** | Handles both sectioned annexes (Annex I) and dash-list annexes (Annex II) |
| **Conservative cleaning** | Only normalizes whitespace/artifacts — never rewrites legal text |
| **Stable IDs** | Deterministic IDs (`aiact:art5`, `aiact:annex3`) for citation linking |
| **Extensible** | Add new document types via `converter.py` plugin pattern |

## Quick Start

1. **Install dependencies** — See [docs/installation.md](docs/installation.md)
2. **Configure database** — Add `.env` with PostgreSQL credentials
3. **Download a document** — Use `src/ingestion/url_loader.py` or place PDFs in `data/source/`
4. **Convert to Markdown** — Run `python src/ingestion/converter.py`
5. **Clean Markdown** — Run `python src/processing/cleaner.py`
6. **Extract legal structure** — Run `python src/processing/legal_structure.py`
7. **Load to pgvector** — Implement embedding generation and upsert (see `src/db.py`)

## Example Output

The parser produces structured JSON like:

```json
{
  "instrument": {
    "celex": "32024R1689",
    "eli": "http://data.europa.eu/eli/reg/2024/1689/oj",
    "title": "Regulation (EU) 2024/1689 (AI Act)",
    "language": "EN",
    "publication_date": "2024-07-12"
  },
  "elements": [
    {
      "type": "article",
      "id": "aiact:art1",
      "number": "1",
      "chapter": { "number": "I", "title": "GENERAL PROVISIONS" },
      "title": "Subject matter",
      "paragraphs": [
        { "index": 1, "number": "1", "text": "The purpose of this Regulation is to..." },
        { "index": 2, "number": "2", "intro": "This Regulation lays down:", "points": [
          { "label": "a", "text": "harmonised rules for the placing on the market..." },
          { "label": "b", "text": "prohibitions of certain AI practices..." }
        ]}
      ]
    }
  ]
}
```

## Project Structure

```
RAG_Demo/
├── data/
│   ├── metadata.json              # Document metadata
│   ├── source/                    # Raw downloaded PDFs
│   └── extracted/                 # Markdown, JSON, cleaned, structured output
├── docs/
│   └── installation.md            # Installation guide
├── src/
│   ├── db.py                      # PostgreSQL/pgvector connection
│   ├── ingestion/
│   │   ├── url_loader.py          # EUR-Lex downloader
│   │   ├── pdf_parser.py          # PDF → Markdown/JSON/Links
│   │   ├── converter.py           # Batch conversion CLI
│   │   └── parser.py              # Legacy text extractor
│   └── processing/
│       ├── cleaner.py             # Markdown cleaning pipeline
│       └── legal_structure.py     # Legal structure parser (core)
├── requirements.txt
├── pyproject.toml
└── todo.md
```

## Agentic Development (Recommended)

This project is designed for **agentic workflows** — AI agents that can read, write, and reason about code autonomously. We strongly recommend using an agentic harness for development.

### OpenCode

[**OpenCode**](https://opencode.dev) is the preferred agentic harness for this project. It provides:

- **Native agent support** — Built-in agents for exploration, coding, debugging
- **Model flexibility** — Swap models per task (coding, reasoning, long-context)
- **Session persistence** — Resume work across sessions
- **Extensible** — Custom agents, commands, skills, MCP servers
- **Local-first** — Runs on your machine, your data stays private

#### Installation

See [docs/opencode.md](docs/opencode.md) for full installation instructions.

Quick start:
```sh
# macOS
brew install opencode

# Linux
curl -fsSL https://opencode.dev/install.sh | sh

# Windows
scoop install opencode
```

#### Recommended Models

| Model | Provider | Best For |
|-------|----------|----------|
| **Nemotron 3 Ultra** | NVIDIA | Complex reasoning, architecture decisions, code review |
| **Hy4** | Hyperbolic | Day-to-day coding, refactoring, implementation |
| **Kimi K3** | Moonshot | Large file analysis, long-context tasks, multilingual |

All three integrate natively with OpenCode. Configure API keys in `~/.config/opencode/opencode.json`.

#### Usage

```sh
# Start OpenCode in this project
cd RAG_Demo
opencode

# Or with a specific model
opencode -m nvidia/nemotron-3-ultra
```

### Why Agentic Harnesses?

| Traditional IDE + Copilot | Agentic Harness (OpenCode) |
|---------------------------|----------------------------|
| Autocomplete & chat | Autonomous multi-step tasks |
| Single-file context | Whole-repo understanding |
| Human drives every step | Agent plans & executes |
| Limited tool use | Full shell, git, browser, DB access |
| Session = tab | Session = persistent workspace |

---

## License

This project processes public EU legal texts available from EUR-Lex under the [EU Public Licence](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689).