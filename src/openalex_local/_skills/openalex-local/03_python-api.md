---
description: |
  [TOPIC] Python API
  [DETAILS] Public callables grouped by area — search, retrieval, enrichment, cache, export, async, configuration.
tags: [openalex-local-python-api]
---

# Python API

```python
import openalex_local as oal
```

## Search + count

| Symbol | Purpose |
|---|---|
| `search(query, limit=...)` | Full-text search → `SearchResult` |
| `count(query)` | Count matches without retrieving them |
| `exists(work_id_or_doi)` | Boolean presence check |

## Retrieval + enrichment

| Symbol | Purpose |
|---|---|
| `get(work_id_or_doi)` | Single `Work` |
| `get_many(ids)` | Batch lookup |
| `enrich(input)` | Enrich a record (or BibTeX) with OpenAlex metadata |
| `enrich_ids(ids)` | Resolve a list of OpenAlex IDs |

## Models (dataclasses)

| Symbol | Purpose |
|---|---|
| `Work` | Single record — id, doi, title, authors, year, abstract, IF, concepts, … |
| `SearchResult` | Iterable container with `.works`, `.total`, `.query` |

## Cache

| Symbol | Purpose |
|---|---|
| `cache.*` | Local paper caches — create / append / query / list / delete / export / show-ids / show-stats |

## Export

| Symbol | Purpose |
|---|---|
| `save(records, path, format=...)` | Write JSON / BibTeX / text |
| `SUPPORTED_FORMATS` | Tuple of supported export formats |

## Configuration

| Symbol | Purpose |
|---|---|
| `configure(...)` | One-shot global config |
| `get_mode()` | `"db"` or `"http"` |
| `info()` | Status snapshot (DB path, mode, version) |

## Async

| Symbol | Purpose |
|---|---|
| `aio.search(...)` | asyncio-friendly variants |

## Jobs

| Symbol | Purpose |
|---|---|
| `jobs.*` | Long-running batch jobs |

## See also

- [04_cli-reference.md](04_cli-reference.md) — CLI mirror of this surface
- [14_search-syntax.md](14_search-syntax.md) — search syntax cheatsheet
