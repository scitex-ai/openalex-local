# Runtime directory for openalex-local

This directory contains regenerable, per-host runtime data — caches,
job queues and logs.  The corpus itself does NOT live here: it is in the
per-host PostgreSQL that `scitex_dev.store.host_store` resolves.
Everything under `runtime/` is excluded from git; only `.gitkeep` and this
`README.md` are tracked.

See: `scitex-dev` skill `01_ecosystem/06_local-state-directories.md` for
the canonical layout.
