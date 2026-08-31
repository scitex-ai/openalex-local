---
description: |
  [TOPIC] HTTP API — openalex-local FastAPI server
  [DETAILS] Standalone FastAPI app in `_server/` exposing work search and retrieval over the local OpenAlex DB. Boot with `openalex-local serve` or `uvicorn openalex_local._server:app`.
tags: [openalex-local-http-api]
---

# HTTP API — openalex-local

The `openalex_local._server` package exposes the local OpenAlex DB as a
FastAPI service. Routes live in `_server/routes.py` and the app is
assembled in `_server/__init__.py`.

## Endpoints

### Root / health

| Method | Path | Handler | Returns |
|--------|------|---------|---------|
| GET | `/` | root | API name, version, endpoint map |
| GET | `/health` | health | DB connectivity + path |
| GET | `/info` | info | Total works, FTS state, DB path |

### Works

| Method | Path | Returns |
|--------|------|---------|
| GET | `/works?q=<query>` | `SearchResponse` — full-text search across titles/abstracts |
| GET | `/works/{id_or_doi:path}` | `WorkResponse` (or null) — fetch by OpenAlex ID or DOI |
| POST | `/works/batch` | `BatchResponse` — bulk ID/DOI lookup |

## Boot

```bash
openalex-local serve --host 0.0.0.0 --port 8766
# or
uvicorn openalex_local._server:app --port 8766
```

See `10_database-setup.md` for the underlying DB layout and access modes.
