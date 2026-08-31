# Database Scripts

Scripts for downloading, building, and maintaining the OpenAlex local database.

## Quick Start

```bash
# Always start here - shows current state and what to do next
make status
```

## Numbering Convention

| Prefix | Category | Description |
|--------|----------|-------------|
| `00_` | Download | Main snapshot download (works) |
| `01_` | Download | Other entities + helpers |
| `02_` | Build | JSON → the corpus |
| `03_` | Build | Full-text search index |
| `04_` | Build | Sources/journals table (SciTeX IF proxy) |
| `05_` | Build | Citations table (accurate SciTeX IF) |
| `06_` | Build | SciTeX IF calculation indexes |

## Build Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1: DOWNLOAD (~760GB, 1-2 days)                               │
│  make download                                                       │
│    ├── 00_download_safe.sh (works: 698GB)                           │
│    └── 01_download_other_entities.sh (authors+9: 60GB)              │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 2: CORE DATABASE (12-48 hours)                               │
│  make build                                                          │
│    ├── 02_build_database.py (JSON → PostgreSQL)                     │
│    └── 03_build_fts_index.py (full-text search)                     │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 3: SciTeX IF (Optional)                                  │
│  make build-sources      # 04: Journal metadata (~30 sec)           │
│  make build-citations    # 05: Citation graph (~50-70h total)       │
│  make build-if-indexes   # 06: Works table indexes (~2-4 hours)     │
│  make build-ref-count    # 07: Add ref_count column (~8 hours)      │
│  [08_experiment_thresholds.py - determines >20 refs threshold]      │
│  make build-if-table     # 09: Precompute JCR-style IFs (~1 hour)   │
└─────────────────────────────────────────────────────────────────────┘
```

## Scripts Reference

### Download Scripts (00_, 01_)

| Script | Description | Duration | Command |
|--------|-------------|----------|---------|
| `00_download_safe.sh` | Download works entity (698GB) | 12-24h | `make download-works` |
| `00_download_all_entities.sh` | Download all entities | 1-2 days | - |
| `01_download_other_entities.sh` | Download non-works (60GB) | 2-4h | `make download-others` |
| `01_download_snapshot.py` | Python download helper | - | - |

### Build Scripts (02_, 03_)

| Script | Description | Duration | Command |
|--------|-------------|----------|---------|
| `02_build_database.py` | Parse JSON → the corpus | 12-48h | `make build-db` |
| `03_build_fts_index.py` | Build the full-text index | 1-4h | `make build-fts` |

### SciTeX IF Scripts (04_, 05_, 06_)

| Script | Description | Duration | Command |
|--------|-------------|----------|---------|
| `04_build_sources_table.py` | Journal metadata (SciTeX IF proxy) | ~30 sec | `make build-sources` |
| `05_build_citations_table.py` | Citation relationships (2.9B rows) | ~3-4h | `make build-citations` |
| `06_build_if_indexes.py` | All SciTeX IF-related indexes | ~8-10h | `make build-if-indexes` |
| `07_add_ref_count_column.py` | Add ref_count for citable filter | ~1-2h | `make build-ref-count` |
| `08_experiment_thresholds.py` | Test citable items threshold | ~5 min | manual |
| `09_build_if_table.py` | Precompute SciTeX IFs | ~1h | `make build-if-table` |

## Make Targets Summary

```bash
# Status & Help
make status              # Show current state (START HERE)
make help                # List all commands
make check               # Verify prerequisites

# Download
make download            # Download all (parallel)
make download-works      # Download works only (698GB)
make download-others     # Download other entities (60GB)
make download-stop       # Stop downloads (resumable)

# Core Build
make build               # Build database + FTS
make build-db            # Build the corpus from the snapshot
make build-fts           # Build full-text search

# SciTeX IF Build (Optional)
make build-sources       # Build journal metadata table
make build-citations     # Build citation graph (slow!)
make build-if-indexes    # Build IF calculation indexes

# Utilities
make build-stop          # Stop all builds (resumable)
make db-info             # Show database info
make db-stats            # Detailed statistics
```

## Database Schema

### Core Tables

```sql
-- Works table: 284M+ scholarly works
-- Authoritative copy: scripts/database/_schema.py
CREATE TABLE works (
    id BIGSERIAL PRIMARY KEY,
    openalex_id TEXT UNIQUE NOT NULL,  -- W2741809807
    doi TEXT,
    title TEXT,
    abstract TEXT,
    year INTEGER,
    publication_date TEXT,
    type TEXT,
    language TEXT,
    source TEXT,           -- Journal name
    source_id TEXT,        -- OpenAlex source ID
    issn TEXT,
    volume TEXT,
    issue TEXT,
    first_page TEXT,
    last_page TEXT,
    publisher TEXT,
    cited_by_count INTEGER DEFAULT 0,
    is_oa BOOLEAN DEFAULT FALSE,
    oa_status TEXT,
    oa_url TEXT,
    authors_json TEXT,
    concepts_json TEXT,
    topics_json TEXT,
    referenced_works_json TEXT,
    ref_count INTEGER,
    raw_json TEXT,
    search_vector TSVECTOR,   -- full-text index
    created_at TIMESTAMPTZ
);

-- Full-text search is a COLUMN on works, not a second table: an
-- external index keyed on a row number the table does not declare
-- points at the wrong row after any rebuild, and the join still
-- succeeds.
CREATE INDEX idx_works_search_vector ON works USING GIN (search_vector);
```

### SciTeX IF Tables (Optional)

```sql
-- Sources: 255K journals with metrics
CREATE TABLE sources (
    id BIGSERIAL PRIMARY KEY,
    openalex_id TEXT UNIQUE,
    issn_l TEXT,
    issns TEXT,              -- JSON array
    display_name TEXT,
    type TEXT,
    works_count INTEGER,
    cited_by_count INTEGER,
    two_year_mean_citedness DOUBLE PRECISION,  -- SciTeX IF proxy
    h_index INTEGER,
    i10_index INTEGER,
    is_oa BOOLEAN,
    is_in_doaj BOOLEAN
);

-- ISSN lookup for fast journal identification
CREATE TABLE issn_lookup (
    issn TEXT PRIMARY KEY,
    source_id BIGINT REFERENCES sources(id)
);

-- Citations: 2.9B citation relationships
CREATE TABLE citations (
    citing_id TEXT NOT NULL,   -- Work that cites
    cited_id TEXT NOT NULL,    -- Work being cited
    citing_year INTEGER        -- Year of citation
);
```

### Indexes for SciTeX IF Calculation

```sql
-- Works table (for finding articles by journal+year)
CREATE INDEX idx_works_issn ON works(issn);
CREATE INDEX idx_works_issn_year ON works(issn, year);  -- KEY for IF
CREATE INDEX idx_works_source_id ON works(source_id);
CREATE INDEX idx_works_source_id_year ON works(source_id, year);

-- Citations table (for counting citations)
CREATE INDEX idx_citations_cited_year ON citations(cited_id, citing_year);  -- KEY for IF
CREATE INDEX idx_citations_citing ON citations(citing_id);
CREATE INDEX idx_citations_year ON citations(citing_year);
```

## SciTeX Impact Factor (OpenAlex) Calculation

Note: We use "SciTeX Impact Factor" or "SciTeX IF" to distinguish from
the trademarked "Journal Impact Factor" (JCR/Clarivate). Our calculation
uses the same formula but with OpenAlex data.

### Formula
```
SciTeX IF(2023) = Citations in 2023 to articles from 2021-2022
                  ─────────────────────────────────────────────
                  Citable articles published in 2021-2022
```

### Data Flow
```
1. Find articles: SELECT openalex_id FROM works
                  WHERE issn = ? AND year BETWEEN 2021 AND 2022

2. Count citations: SELECT COUNT(*) FROM citations
                    WHERE cited_id IN (...) AND citing_year = 2023

3. Calculate: IF = citations / articles
```

### Two SciTeX IF Sources

| Source | Table | Speed | Accuracy |
|--------|-------|-------|----------|
| OpenAlex proxy | `sources.two_year_mean_citedness` | Fast | Good proxy |
| Calculated | `citations` table | Slower | JCR-style |

## Resource Requirements

| Phase | Disk | Duration | Notes |
|-------|------|----------|-------|
| Download | 760GB | 1-2 days | At 5-10 MB/s |
| Core Build | +1TB | 12-48h | DB + FTS |
| SciTeX IF Build | +300GB | 50-70h | Citations + indexes |
| **Total** | **~2TB** | **3-5 days** | |

## Monitoring Progress

```bash
# Check overall status
make status

# Watch specific builds
tail -f logs/build_db.log
tail -f logs/build_fts.log
tail -f logs/build_citations.log
tail -f logs/build_if_indexes.log

# Check screen sessions
screen -ls

# Attach to session
screen -r openalex-build-db

# Database growth
watch -n 60 'make db-info'
```

## Resumability

All scripts support resuming after interruption:

| Script | Resume Mechanism |
|--------|------------------|
| `02_build_database.py` | Tracks files in `_build_progress` table |
| `03_build_fts_index.py` | Checks if FTS complete |
| `05_build_citations_table.py` | Tracks rowid in `_citations_build_progress` |
| `06_build_if_indexes.py` | Uses `CREATE INDEX IF NOT EXISTS` |

## Troubleshooting

### Build seems stuck
```bash
screen -r openalex-build-db     # Attach to session
tail -f logs/build_db.log       # Check log
watch -n 60 'make db-info'  # Watch growth
```

### Out of disk space
```bash
df -h                           # Check space
# Need ~2TB total for full build
```

### Checking which indexes exist
```bash
make db-info   # tables, row counts and build progress
```

## Related Files

- `Makefile` - Build orchestration
- `scripts/utils/status.sh` - Status reporter
- `src/openalex_local/_core/db.py` - Database connection
- `src/openalex_local/_core/fts.py` - FTS search
- `src/openalex_local/_core/models.py` - Work model
