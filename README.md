# Document Store

A single-user, local-first document management system for organising and
searching case material: PDFs, Word documents, email, and scanned images.
Supports keyword and semantic search, timelines, communication chains, and
citation-grounded question answering.

This is a personal tool for managing a single legal case. It is not designed
for multi-user or production deployment.

## Status

Early development (EPIC-1: project foundation). See `docs/architecture.md`
and `docs/backlog.md` for the full design and task list.

## Requirements

- Docker Desktop with WSL2 integration (Windows) or Docker Engine (Linux)
- VS Code with the Dev Containers extension
- The [LLM Gateway](../llm-gateway) running separately, attached to the
  `llm_net` Docker network (see below)

All other dependencies (Python 3.12, PaddleOCR, uv) are installed inside the
devcontainer; nothing else needs to be installed on the host.

## Setup

1. Clone this repository onto the Linux filesystem under WSL (not under
   `/mnt/c` or `/mnt/e`), e.g. `~/DOCUMENT_STORE`. Performance and SQLite
   file locking are unreliable on Windows-mounted paths.

2. Create the shared Docker network, if it doesn't already exist:

   ```bash
   docker network create llm_net
   ```

3. Start the LLM Gateway stack (in its own repository) and confirm it is
   attached to `llm_net`.

4. Copy the environment template and set the gateway key:

   ```bash
   cp .env.example .env
   # edit .env and set LLM_GATEWAY_KEY
   ```

5. Copy the example configuration:

   ```bash
   cp config/config.example.toml config/config.toml
   ```

6. Open the folder in VS Code and select **Reopen in Container** when
   prompted. This builds the devcontainer and runs `uv sync`.

## Originals Folder Structure

Case documents are placed in `originals/`, organised by document class:

```
originals/
├── in_camera/          # in camera material; processed locally only
├── court_filings/     # filed or served court documents
├── correspondence/    # letters and other correspondence
└── ...                # any other folders; files are classified as "other"
```

Classification is based on these folder names and on filename patterns
(e.g. `bank_statement*`, `receipt*`). Rules are in `config/config.toml`
under `[classification]`.

**Important:**

- Files placed outside these folders are classified as `other` and processed
  locally only. They are still searchable, but they may need manual
  reclassification (STORY-2.5).
- Bank statements are excluded from chunking and embedding; they are handled
  by a separate tool.
- Folder names must match the rules in `config.toml` exactly (case-insensitive).
  If you rename a folder, update the rules to match.

## Document Routing

Each document has a processing route that controls what may happen to its
content. Routes, from most to least restrictive:

| Route | Meaning |
|-------|---------|
| `local_only` | Processed locally only; never sent to cloud services |
| `index_only` | Registered and searchable by metadata; not chunked or embedded |
| `external` | Handled by another tool (e.g. bank statements); not chunked or embedded |
| `standard` | Processed normally; cloud services permitted if enabled |

### How routes are assigned

- At ingestion, a document's route comes from its class (`[routing]` in `config.toml`).
- If identical content exists at several locations, the **most restrictive** route applies.
- Automatic processing only ever makes a document more restrictive. It never downgrades one.

### Changing a document's route

Route changes are manual and recorded in the `document_route_change` table.

- **Upgrading** (making a document more restrictive) needs no acknowledgment.
- **Downgrading** (making it less restrictive, for example after material has been filed publicly) requires explicit acknowledgment of the risk. The change is refused without it.

Every change records the previous and new route, the reason, and whether the
risk was acknowledged.

> Downgrading an in camera document may expose its content to processing that
> the original classification was designed to prevent. Confirm that you are
> entitled to do so before acknowledging the risk.

## Verifying the Setup

Run these inside the devcontainer terminal:

```bash
uv run python -m document_store       # expect: document_store 0.1.0
uv run pytest                         # expect: all tests passing
uv run ruff check .                   # expect: no errors
curl -s http://llm-gateway-api:8000/health   # expect: {"status": "ok"}
```

If the gateway check fails, see `docs/troubleshooting.md` (network and DNS
issues between the devcontainer and the gateway are the most common cause).

## Project Layout

```
DOCUMENT_STORE/
├── .devcontainer/        # Devcontainer build and configuration
├── src/document_store/   # Application package
├── tests/                # Automated tests
├── config/                # Configuration templates (config.toml is local-only)
├── docs/                  # Architecture, backlog, troubleshooting notes
├── originals/             # Case documents (not committed)
├── cache/                  # Regenerable OCR output (not committed)
├── logs/                   # Pipeline and audit logs (not committed)
└── case.sqlite             # Main database (not committed)
```

`originals/`, `cache/`, `logs/`, and `case.sqlite` hold case-specific data and
are excluded from version control. `config/config.toml` and `.env` are also
excluded, since they contain machine-specific paths and secrets.

## Configuration

Settings are read from `config/config.toml`, with the gateway API key read
separately from the `LLM_GATEWAY_KEY` environment variable. See
`config/config.example.toml` for the full set of options: paths, gateway
connection, model names, chunking parameters, and OCR thresholds.

## Environment Variables

| Variable | Source | Purpose |
|---|---|---|
| `LLM_GATEWAY_KEY` | `.env` | Authenticates requests to the LLM Gateway |
| `LLM_GATEWAY_URL` | Devcontainer env | Gateway base URL (`http://llm-gateway-api:8000`) |
| `LLM_CLIENT_NAME` | Devcontainer env | Identifies this project in gateway logs |

## Architecture and Design

See `docs/architecture.md` for the full system design, including process
flows, data model, and rationale for technology choices. See
`docs/backlog.md` for the epic and story breakdown.

## Development Notes

- Dependencies are managed with `uv`. Development tools (`pytest`, `ruff`)
  are declared as a dependency group and installed by default — use
  `uv sync` after changing `pyproject.toml`.
- The devcontainer is attached to the external `llm_net` Docker network so
  it can reach the LLM Gateway by container name.
- PaddleOCR is the primary OCR engine; Tesseract is a fallback for low-
  confidence results.
- Original files are never modified. All derived data (chunks, embeddings,
  extracted entities) can be regenerated from originals.