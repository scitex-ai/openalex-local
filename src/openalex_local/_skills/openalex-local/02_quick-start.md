---
description: |
  [TOPIC] Quick start
  [DETAILS] Smallest example — search by title, get by DOI, enrich a list of OpenAlex IDs.
tags: [openalex-local-quick-start]
---

# Quick Start

## Python — search

```python
import openalex_local as oal

results = oal.search("graph neural network", limit=10)
for w in results.works:
    print(w.id, w.title[:80])
```

## Python — get + enrich

```python
work = oal.get("W2741809807")
print(work.title, work.year, work.authors)

# Enrich a list of OpenAlex IDs with metadata
enriched = oal.enrich_ids(["W2741809807", "W4385237842"])
```

## Python — async

```python
from openalex_local import aio
results = await aio.search("transformer attention")
```

## CLI

```bash
openalex-local search "neural network attention" -n 5
openalex-local search-by-doi 10.1038/nature12373 --bibtex
openalex-local cache create --query "CRISPR"
openalex-local export-if -o scitex_if.csv
openalex-local show-status
```

## HTTP relay

```bash
# host A
openalex-local relay --port 31292

# host B
openalex-local --http --api-url http://A:31292 search "graph neural network"
```

## Next

- [03_python-api.md](03_python-api.md) — full surface
- [04_cli-reference.md](04_cli-reference.md) — all CLI commands
- [10_database-setup.md](10_database-setup.md) — snapshot build pipeline
- [14_search-syntax.md](14_search-syntax.md) — full-text query syntax
