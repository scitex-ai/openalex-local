---
description: |
  [TOPIC] Database Setup
  [DETAILS] Database architecture, build pipeline, access modes, and deployment options.
tags: [openalex-local-database-setup, openalex-local]
---


# Database Setup and Architecture

The corpus lives in PostgreSQL — the fleet store, resolved by
`scitex_dev.store.host_store(pkg="openalex_local", name="corpus")`. There is no
file to find and no second engine to choose.

## Database Contents

| Table | Contents | Size |
|-------|----------|------|
| `works` | 284M+ scholarly works with metadata | ~200 GB |
| `works.search_vector` | `tsvector` over title + abstract, GIN-indexed | ~100 GB |
| `sources` | Journal metadata + SciTeX IF | Optional |
| `journal_impact_factors` | Precomputed impact factors | Optional |

Build counters (`total_works`, `fts_total_indexed`, `last_sync_date`) are not a
table. They live in a `scitex_dev.store.Store`; read them with
`openalex_local._core.state.get_metadata(key)`.

## Build Pipeline

```bash
# 1. Download OpenAlex snapshot (~300 GB compressed)
python scripts/database/01_download_snapshot.py

# 2. Build the corpus
python scripts/database/02_build_database.py

# 3. Build the full-text index
python scripts/database/03_build_fts_index.py

# 4. (Optional) Build sources/journal table
python scripts/database/04_build_sources_table.py

# 5. (Optional) Build citations table
python scripts/database/05_build_citations_table.py

# 6. (Optional) Build impact factor indexes
python scripts/database/06_build_if_indexes.py
```

## Access Modes

### Direct corpus access (db mode)

```bash
# Nothing to set on a host whose store is configured:
openalex-local search "CRISPR"

# To reach a corpus elsewhere:
export SCITEX_STORE_DSN=postgresql://user@host:55432/scitex
openalex-local search "CRISPR"
```

### HTTP Relay (http mode)

```bash
# On the server with the corpus
openalex-local relay --host 0.0.0.0 --port 31292

# On the client
export OPENALEX_LOCAL_MODE=http
export OPENALEX_LOCAL_API_URL=http://server:31292
openalex-local search "CRISPR"

# Or via SSH tunnel
ssh -L 31292:127.0.0.1:31292 your-server
```

## Corpus Discovery

There is exactly one resolution path, and it is not this package's:

1. `$SCITEX_STORE_DSN` when set — an explicit override wins outright.
2. Otherwise this host's PostgreSQL, over its UNIX socket.

The old four-entry search of candidate `.db` locations is gone. It answered
differently depending on the working directory the command was run from, and
nothing in the output said which database had replied.

## Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `SCITEX_STORE_DSN` | Corpus DSN override | `postgresql://user@host:55432/scitex` |
| `OPENALEX_LOCAL_API_URL` | HTTP API URL | `http://localhost:31292` |
| `OPENALEX_LOCAL_MODE` | Force mode | `db`, `http`, or `auto` |
| `OPENALEX_LOCAL_HOST` | Relay bind host | `0.0.0.0` |
| `OPENALEX_LOCAL_PORT` | Relay port | `31292` |
