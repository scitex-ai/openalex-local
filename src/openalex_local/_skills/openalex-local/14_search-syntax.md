---
description: |
  [TOPIC] Search Syntax
  [DETAILS] operators, phrases, filters.
tags: [openalex-local-search-syntax, openalex-local]
---


# Search Syntax

Uses PostgreSQL full-text search across 284M+ works.
Queries are parsed with `websearch_to_tsquery`, so the syntax is
the one web search engines use.

```python
# Simple terms
search("neural network")

# Phrase match
search('"deep learning"')

# Boolean operators
search("EEG epilepsy")        # both terms
search("fMRI or PET")
search("CRISPR -bacteria")    # leading - excludes
```

## Async API

```python
from openalex_local import aio

async def main():
    results = await aio.search("machine learning")
    counts = await aio.count_many(["CRISPR", "neural network"])
```

## Caching

```python
from openalex_local import cache
# Cache search results for repeated queries
cached = cache.search("frequently searched term")
```
