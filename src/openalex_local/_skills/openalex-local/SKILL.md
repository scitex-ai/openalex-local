---
name: openalex-local
description: |
  [WHAT] Offline, zero-API-key search over the full OpenAlex academic corpus.
  [WHEN] Use when the user asks to "search papers", "find literature on X", "look up a DOI", "get metadata for this paper", "enrich these OpenAlex IDs", "batch-resolve DOIs to BibTeX", "search by title/abstract/author".
  [HOW] `import openalex_local` then call `openalex_local.search(...)`.
tags: [openalex-local]
allowed-tools: mcp__scitex__openalex_*
primary_interface: python
interfaces:
  python: 3
  cli: 2
  mcp: 2
  skills: 2
  hook: 0
  http: 0
---


# openalex-local

> **Interfaces:** Python ⭐⭐⭐ (primary) · CLI ⭐⭐ · MCP ⭐⭐ · Skills ⭐⭐ · Hook — · HTTP —

## Installation & import

`pip install openalex-local` installs the standalone:

```python
import openalex_local
```

This package does not ship as a submodule of the `scitex` umbrella.

## Sub-skills

### Mandatory
- [01_installation.md](01_installation.md) — pip install + extras + verify
- [02_quick-start.md](02_quick-start.md) — search / get / enrich / relay
- [03_python-api.md](03_python-api.md) — Public callables grouped by area
- [04_cli-reference.md](04_cli-reference.md) — `openalex-local` console entry

### Workflows
- [06_http-api.md](06_http-api.md) — FastAPI routes (works search/get/batch, health/info)
- [10_database-setup.md](10_database-setup.md) — Database architecture, build pipeline, access modes
- [11_cli-reference.md](11_cli-reference.md) — historical CLI notes
- [12_mcp-tools.md](12_mcp-tools.md) — MCP tools for AI agents
- [13_quick-start.md](13_quick-start.md) — historical quick-start
- [14_search-syntax.md](14_search-syntax.md) — full-text query syntax

## CLI

```bash
openalex-local search "neural network attention"
openalex-local search-by-id W2741809807
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `openalex_search` | Full-text search across works |
| `openalex_search_by_id` | Get work by OpenAlex ID |
| `openalex_enrich_ids` | Enrich IDs with metadata |
| `openalex_status` | Database status |
