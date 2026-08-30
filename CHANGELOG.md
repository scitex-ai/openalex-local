# Changelog

All notable changes to `openalex-local` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.8.0]

**Breaking.** The corpus moved to PostgreSQL and the package-local database
layer is gone.

- The corpus lives in the fleet store. `scitex_dev.store.host_store` is the
  only thing that resolves its address; `SCITEX_STORE_DSN` moves it.
- `scitex-dev>=0.57.0` and `psycopg[binary]>=3.1` are HARD dependencies, not
  extras.
- REMOVED: `OPENALEX_LOCAL_DB` and the four-entry default path search. They
  were a second resolver, and it answered differently depending on the
  working directory the command ran from.
- REMOVED: `openalex_local._core.dsn` (which declared its own backend enum)
  and `openalex_local._core.paramstyle` (a placeholder translator that existed
  only for the migration).
- `configure(db_path)` is now `configure(dsn)` and refuses anything that is
  not a PostgreSQL connection string. `Config.get_db_path` / `set_db_path`
  become `Config.get_dsn` / `set_dsn`.
- `openalex-local db update --db PATH` is now `--dsn DSN`.
- `info()` reports `dsn` where it reported `db_path`; the HTTP `/info` and
  `/health` endpoints report `database_dsn` where they reported
  `database_path`.
- Full-text search is `works.search_vector` (a GIN-indexed `tsvector`) rather
  than a separate index table, and queries are parsed with
  `websearch_to_tsquery`. The hand-rolled query sanitiser is deleted: it
  existed to prevent an exception that can no longer occur, and it silently
  changed the meaning of any query containing a hyphen.
- Build counters (`total_works`, `fts_total_indexed`, `last_sync_date`) live
  in a `scitex_dev.store.Store` instead of a table inside the corpus, so a
  status call no longer has to open a 200 GB database to read a number.
- The corpus schema is declared once, in `scripts/database/_schema.py`. The
  test-corpus builder now uses it too — it previously declared different
  column names, so every database-touching test measured a schema no build
  step produced.

## [0.7.9]

- Back-merge `main` into `develop` (reconcile divergence; keep `develop`'s
  source-fix #40, sphinx dedup #41, and the `10_quickstart` example +
  test).
- Standardize CI to the canonical SciTeX workflow set
  (`pytest-matrix`, `import-smoke`, `rtd-sphinx-build`,
  `<pkg>-quality-audit`, `newb-docs-quality`, `auto-merge-to-develop`);
  drop the legacy `CI` / `Tests` / `Docs` / `Newb` workflows.
- `v0.7.7` and `v0.7.8` tags were burned (publish/version mismatch);
  this is the next valid release.

## [0.7.5]

- Initial CHANGELOG entry — see git log for prior history.
