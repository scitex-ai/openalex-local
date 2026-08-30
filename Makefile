# OpenAlex Local Makefile
# ========================
# Thin dispatcher - delegates actual logic to scripts
#
# Quick reference (run 'make help' for full list):
#   make status   - Show system status (START HERE)
#   make check    - Verify prerequisites
#   make download - Download OpenAlex snapshot (~760GB)
#   make build    - Build the corpus + full-text index

SHELL := /bin/bash
PROJECT_ROOT := $(shell pwd)
SCRIPTS := $(PROJECT_ROOT)/scripts
PYTHON := python3
# The corpus address is resolved by the fleet store primitive at recipe
# time, never assembled here. `=` and not `:=` on purpose: a recipe that
# never touches the database should not pay for a Python start-up, and a
# machine without scitex-dev installed should still be able to run
# `make help`.
CORPUS_DSN = $(shell $(PYTHON) -c 'from scitex_dev.store import host_store; print(host_store(pkg="openalex_local", name="corpus").dsn)' 2>/dev/null)
PSQL = psql "$(CORPUS_DSN)" -tAX
SNAPSHOT_DIR := $(PROJECT_ROOT)/data/snapshot/works

.PHONY: help status check install dev test \
        update update-dry-run update-since \
        download download-works download-others download-stop \
        build build-db build-fts build-sources build-citations build-if-indexes \
        build-ref-count build-if-table build-if-validate build-info \
        clean lint format db-info db-stats

# ============================================================
# HELP & STATUS
# ============================================================

help: ## Show this help
	@echo "OpenAlex Local - Available Commands"
	@echo "===================================="
	@echo ""
	@echo "Start here:"
	@echo "  make status   Show current system status"
	@echo "  make check    Verify prerequisites are installed"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

status: ## Show comprehensive status report
	@$(SCRIPTS)/utils/status.sh

# ============================================================
# SETUP
# ============================================================

check: ## Verify all prerequisites are installed
	@$(SCRIPTS)/setup/check_prerequisites.sh

install: ## Install openalex-local package
	pip install -e .

dev: ## Install with dev dependencies
	pip install -e ".[dev]"

# ============================================================
# DIFFERENTIAL UPDATE
# ============================================================
# Incremental update: downloads only new/changed data since last sync

update: ## Run differential update (download + merge changes since last sync)
	@echo "Starting differential update..."
	@mkdir -p $(PROJECT_ROOT)/logs
	$(PYTHON) $(SCRIPTS)/database/10_differential_update.py \
		--snapshot-dir $(SNAPSHOT_DIR) \
		2>&1 | tee $(PROJECT_ROOT)/logs/differential_update.log

update-dry-run: ## Show what would be updated (no changes)
	$(PYTHON) $(SCRIPTS)/database/10_differential_update.py \
		--snapshot-dir $(SNAPSHOT_DIR) --dry-run

update-since: ## Update from specific date (use: make update-since SINCE=2026-03-01)
	$(PYTHON) $(SCRIPTS)/database/10_differential_update.py \
		--snapshot-dir $(SNAPSHOT_DIR) --since $(SINCE)

# ============================================================
# DATABASE DOWNLOAD
# ============================================================
# Full snapshot: ~760GB (works: 698GB, authors: 59GB, others: ~3GB)
# Downloads are resumable - safe to interrupt and restart

download: ## Download ALL entities in background (recommended)
	@echo "Starting full OpenAlex download (~760GB)..."
	@echo "Works (698GB) and other entities (60GB) will download in parallel."
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-download bash -c '$(SCRIPTS)/database/00_download_safe.sh 2>&1 | tee $(PROJECT_ROOT)/logs/download_safe_run.log'
	@screen -dmS openalex-others bash -c '$(SCRIPTS)/database/01_download_other_entities.sh 2>&1 | tee $(PROJECT_ROOT)/logs/download_others.log'
	@echo ""
	@echo "Downloads started in background:"
	@echo "  - openalex-download: works (698GB)"
	@echo "  - openalex-others: authors + 9 others (60GB)"
	@echo ""
	@echo "Monitor: make status"
	@echo "Attach:  screen -r openalex-download"
	@echo "Logs:    tail -f logs/download_safe_run.log"

download-works: ## Download works only (698GB)
	@echo "Starting works download (698GB)..."
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-download bash -c '$(SCRIPTS)/database/00_download_safe.sh 2>&1 | tee $(PROJECT_ROOT)/logs/download_safe_run.log'
	@echo "Started in screen session: openalex-download"
	@echo "Monitor: make status"

download-others: ## Download authors + other entities (60GB)
	@echo "Starting download of authors + other entities (60GB)..."
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-others bash -c '$(SCRIPTS)/database/01_download_other_entities.sh 2>&1 | tee $(PROJECT_ROOT)/logs/download_others.log'
	@echo "Started in screen session: openalex-others"
	@echo "Monitor: make status"

download-stop: ## Stop all active downloads
	@echo "Stopping downloads (safe to resume later)..."
	@screen -S openalex-download -X quit 2>/dev/null || true
	@screen -S openalex-others -X quit 2>/dev/null || true
	@echo "Stopped. Run 'make download' to resume."

# ============================================================
# DATABASE BUILD
# ============================================================
# Build order: download -> build-db -> build-fts
# Total build time: ~1-3 days depending on hardware

build: build-db build-fts ## Build the corpus and full-text index (run after download)

build-db: ## Build the corpus from the snapshot (background)
	@echo "Starting database build..."
	@echo "This will take 12-48 hours depending on your hardware."
	@echo ""
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-build-db bash -c '$(PYTHON) $(SCRIPTS)/database/02_build_database.py 2>&1 | tee $(PROJECT_ROOT)/logs/build_db.log'
	@echo "Build started in screen session: openalex-build-db"
	@echo ""
	@echo "Monitor:"
	@echo "  screen -r openalex-build-db  (attach to session)"
	@echo "  tail -f logs/build_db.log    (watch log)"
	@echo "  make db-info                 (check progress)"

build-db-fg: ## Build the corpus (foreground, for debugging)
	$(PYTHON) $(SCRIPTS)/database/02_build_database.py

build-fts: ## Build the full-text search index (background)
	@echo "Starting FTS index build..."
	@echo "This will take 1-4 hours depending on database size."
	@echo ""
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-build-fts bash -c '$(PYTHON) $(SCRIPTS)/database/03_build_fts_index.py 2>&1 | tee $(PROJECT_ROOT)/logs/build_fts.log'
	@echo "Build started in screen session: openalex-build-fts"
	@echo ""
	@echo "Monitor:"
	@echo "  screen -r openalex-build-fts  (attach to session)"
	@echo "  tail -f logs/build_fts.log    (watch log)"

build-fts-fg: ## Build FTS index (foreground, for debugging)
	$(PYTHON) $(SCRIPTS)/database/03_build_fts_index.py

build-sources: ## Build sources/journals table for SciTeX IF (background)
	@echo "Starting sources table build..."
	@echo "This indexes journal metadata with SciTeX IF from snapshot."
	@echo ""
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-build-sources bash -c '$(PYTHON) $(SCRIPTS)/database/04_build_sources_table.py 2>&1 | tee $(PROJECT_ROOT)/logs/build_sources.log'
	@echo "Build started in screen session: openalex-build-sources"
	@echo "Monitor: tail -f logs/build_sources.log"

build-sources-fg: ## Build sources table (foreground)
	$(PYTHON) $(SCRIPTS)/database/04_build_sources_table.py

build-citations: ## Build citations table for SciTeX IF calculation (background, ~50-70h)
	@echo "Starting citations table build..."
	@echo "This extracts citation relationships for accurate SciTeX IF calculation."
	@echo "WARNING: This takes 50-70 hours and adds ~200-300GB to database."
	@echo ""
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-build-citations bash -c '$(PYTHON) $(SCRIPTS)/database/05_build_citations_table.py 2>&1 | tee $(PROJECT_ROOT)/logs/build_citations.log'
	@echo "Build started in screen session: openalex-build-citations"
	@echo ""
	@echo "Monitor:"
	@echo "  screen -r openalex-build-citations  (attach to session)"
	@echo "  tail -f logs/build_citations.log    (watch log)"
	@echo "  make status                         (check progress)"

build-citations-fg: ## Build citations table (foreground)
	$(PYTHON) $(SCRIPTS)/database/05_build_citations_table.py

build-if-indexes: ## Build indexes for fast SciTeX IF calculation (after citations)
	@echo "Building indexes for SciTeX IF calculation..."
	@echo "Run this AFTER build-citations completes."
	@echo ""
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-build-if-indexes bash -c '$(PYTHON) $(SCRIPTS)/database/06_build_if_indexes.py 2>&1 | tee $(PROJECT_ROOT)/logs/build_if_indexes.log'
	@echo "Build started in screen session: openalex-build-if-indexes"
	@echo "Monitor: tail -f logs/build_if_indexes.log"

build-if-indexes-fg: ## Build SciTeX IF indexes (foreground)
	$(PYTHON) $(SCRIPTS)/database/06_build_if_indexes.py

build-ref-count: ## Add ref_count column for citable items filter (~1-2h)
	@echo "Adding ref_count column for SciTeX IF citable items filter..."
	@echo "This enables fast filtering of articles with >20 references."
	@echo ""
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-build-refcount bash -c '$(PYTHON) $(SCRIPTS)/database/07_add_ref_count_column.py 2>&1 | tee $(PROJECT_ROOT)/logs/build_ref_count.log'
	@echo "Build started in screen session: openalex-build-refcount"
	@echo "Monitor: tail -f logs/build_ref_count.log"

build-ref-count-fg: ## Add ref_count column (foreground)
	$(PYTHON) $(SCRIPTS)/database/07_add_ref_count_column.py

build-if-table: ## Precompute SciTeX Impact Factors (~2-4h)
	@echo "Precomputing SciTeX Impact Factors (OpenAlex)..."
	@echo "This creates journal_impact_factors table with SciTeX IF values."
	@echo ""
	@mkdir -p $(PROJECT_ROOT)/logs
	@screen -dmS openalex-build-if-table bash -c '$(PYTHON) $(SCRIPTS)/database/09_build_if_table.py --full 2>&1 | tee $(PROJECT_ROOT)/logs/build_if_table.log'
	@echo "Build started in screen session: openalex-build-if-table"
	@echo "Monitor: tail -f logs/build_if_table.log"

build-if-table-fg: ## Precompute SciTeX IF table (foreground)
	$(PYTHON) $(SCRIPTS)/database/09_build_if_table.py --full

build-if-validate: ## Validate SciTeX IF calculation against JCR (30 journals)
	$(PYTHON) $(SCRIPTS)/database/09_build_if_table.py --validate

build-stop: ## Stop all build processes
	@echo "Stopping build processes..."
	@screen -S openalex-build-db -X quit 2>/dev/null || true
	@screen -S openalex-build-fts -X quit 2>/dev/null || true
	@screen -S openalex-build-sources -X quit 2>/dev/null || true
	@screen -S openalex-build-citations -X quit 2>/dev/null || true
	@screen -S openalex-build-if-indexes -X quit 2>/dev/null || true
	@screen -S openalex-create-indexes -X quit 2>/dev/null || true
	@echo "Stopped. Builds are resumable - run the same command to continue."

build-info: ## Show build instructions and estimated times
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║            DATABASE BUILD INSTRUCTIONS                   ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Prerequisites:"
	@echo "  1. Download complete (make status shows all Complete)"
	@echo "  2. ~2TB free disk space"
	@echo "  3. Python 3.10+"
	@echo ""
	@echo "Build Steps:"
	@echo "┌─────────────────────────────────────────────────────────┐"
	@echo "│  Step 1: make build-db    (12-48 hours)                 │"
	@echo "│          Parse JSON into PostgreSQL, create indices     │"
	@echo "├─────────────────────────────────────────────────────────┤"
	@echo "│  Step 2: make build-fts   (1-4 hours)                   │"
	@echo "│          Build the full-text search index               │"
	@echo "└─────────────────────────────────────────────────────────┘"
	@echo ""
	@echo "Or run both: make build"
	@echo ""
	@echo "Monitor Progress:"
	@echo "  make db-info      Show database stats"
	@echo "  make db-stats     Show detailed row counts"
	@echo "  screen -ls        List active build sessions"

# ============================================================
# DEVELOPMENT
# ============================================================

test: ## Run tests
	pytest tests/ -v

lint: ## Run linter
	ruff check src/ tests/

format: ## Format code
	ruff format src/ tests/

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# ============================================================
# DATABASE INFO
# ============================================================

db-info: ## Show corpus schema and stats
	@if [ -z "$(CORPUS_DSN)" ]; then \
		echo "Corpus address unresolved (is scitex-dev installed?)"; \
	elif [ "$$($(PSQL) -c "SELECT to_regclass('works') IS NOT NULL;")" != "t" ]; then \
		echo "No works table at $(CORPUS_DSN)"; \
		echo "Run: make build-db"; \
	else \
		echo "Corpus: $(CORPUS_DSN)"; \
		echo "Size: $$($(PSQL) -c "SELECT pg_size_pretty(pg_total_relation_size('works'));")"; \
		echo ""; \
		echo "Tables:"; \
		$(PSQL) -c "SELECT tablename FROM pg_tables WHERE schemaname = ANY(current_schemas(false)) ORDER BY tablename;"; \
		echo ""; \
		echo "Works count:"; \
		$(PSQL) -c "SELECT COUNT(*) FROM works;"; \
		echo ""; \
		echo "Full-text indexed:"; \
		$(PSQL) -c "SELECT COUNT(*) FROM works WHERE search_vector IS NOT NULL;"; \
		echo ""; \
		echo "Build progress:"; \
		$(PSQL) -c "SELECT COUNT(*) FROM _build_progress;" 2>/dev/null || echo "  (not started)"; \
	fi

db-stats: ## Show detailed corpus statistics
	@if [ -z "$(CORPUS_DSN)" ]; then \
		echo "Corpus address unresolved (is scitex-dev installed?)"; \
	elif [ "$$($(PSQL) -c "SELECT to_regclass('works') IS NOT NULL;")" != "t" ]; then \
		echo "No works table. Run: make build-db"; \
	else \
		echo "╔══════════════════════════════════════════════════════════╗"; \
		echo "║            CORPUS STATISTICS                             ║"; \
		echo "╚══════════════════════════════════════════════════════════╝"; \
		echo ""; \
		echo "Corpus: $(CORPUS_DSN)"; \
		echo "Size: $$($(PSQL) -c "SELECT pg_size_pretty(pg_total_relation_size('works'));")"; \
		echo ""; \
		echo "Row Counts:"; \
		echo "─────────────────────────────────────────"; \
		$(PSQL) -c "SELECT 'works', COUNT(*) FROM works UNION ALL SELECT 'indexed', COUNT(*) FROM works WHERE search_vector IS NOT NULL;"; \
		echo ""; \
		echo "Build counters:"; \
		echo "─────────────────────────────────────────"; \
		$(PYTHON) -c "from openalex_local._core.state import metadata_store; \
			[print(r.values['key'], '=', r.values['value']) for r in metadata_store().rows()]" \
			2>/dev/null || echo "  (no counters recorded)"; \
		echo ""; \
		echo "Sample search test:"; \
		$(PSQL) -c "SELECT COUNT(*) FROM works WHERE search_vector @@ websearch_to_tsquery('english', 'machine learning');"; \
	fi

db-search: ## Test search (usage: make db-search Q="your query")
	@if [ -z "$(CORPUS_DSN)" ]; then \
		echo "Corpus address unresolved (is scitex-dev installed?)"; \
	else \
		$(PSQL) -c "SELECT openalex_id, year, substr(title, 1, 60) FROM works WHERE search_vector @@ websearch_to_tsquery('english', '$(Q)') ORDER BY id LIMIT 10;"; \
	fi
