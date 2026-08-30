---
description: |
  [TOPIC] Installation
  [DETAILS] pip install openalex-local. Pulls click + awscli (for snapshot download). Optional [server], [mcp] extras.
tags: [openalex-local-installation]
---

# Installation

## Standard

```bash
pip install openalex-local
```

Pulls `click>=8.0` and `awscli>=1.0` (for downloading the OpenAlex
snapshot from S3). The 284M-row corpus is built separately, into the
PostgreSQL store this host resolves to.

## Optional extras

| Extra | Purpose |
|---|---|
| `server` | FastAPI HTTP relay (`openalex-local relay`) |
| `mcp` | MCP server (`openalex-local mcp start`) |
| `dev` | Test + lint tooling |
| `docs` | Sphinx + RTD theme |
| `all` | Everything above |

```bash
pip install 'openalex-local[server,mcp]'
```

## Verify

```bash
python -c "import openalex_local; print(openalex_local.__version__)"
openalex-local --version
openalex-local show-status
```

## Editable install (development)

```bash
git clone https://github.com/ywatanabe1989/openalex-local
cd openalex-local
pip install -e '.[dev]'
```

## DB vs HTTP mode

Two modes share the same Python + CLI surface:

- **DB mode** (default, when the corpus is reachable) — direct SQL queries
- **HTTP mode** (`--http`) — talks to an `openalex-local relay` server

See [10_database-setup.md](10_database-setup.md) for snapshot setup.
