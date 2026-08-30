#!/bin/bash
# -*- coding: utf-8 -*-
# Time-stamp: "2026-01-26"
# Author: ywatanabe (with Claude)
# File: scripts/utils/status.sh
# Description: Comprehensive status report for OpenAlex Local
#
# This is the reliable device for loading necessary information
# into administrator's short-term memory.
#
# Run: make status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
DATA_DIR="${PROJECT_ROOT}/data"
SNAPSHOT_DIR="${DATA_DIR}/snapshot"
LOG_DIR="${PROJECT_ROOT}/logs"
# The corpus address is resolved by the fleet's store primitive, never built
# here. An empty CORPUS_DSN means the resolver could not answer, which is a
# different thing from "the corpus is empty" and is reported as such below.
CORPUS_DSN="$(python3 -c 'from scitex_dev.store import host_store; print(host_store(pkg="openalex_local", name="corpus").dsn)' 2>/dev/null || true)"

# One helper, so every probe below asks the same way. -tAX gives bare,
# unaligned, single-column output: anything else and the value carries
# padding that breaks the numeric comparisons.
corpus_q() {
    [[ -n "$CORPUS_DSN" ]] || return 1
    command -v psql &>/dev/null || return 1
    psql "$CORPUS_DSN" -tAX -c "$1" 2>/dev/null
}

# Whether a relation exists, answered without raising.
corpus_has() {
    [[ "$(corpus_q "SELECT to_regclass('$1') IS NOT NULL;")" == "t" ]]
}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Icons
CHECK="[OK]"
CROSS="[!!]"
WARN="[??]"
INFO="[--]"
RUN="[>>]"

divider() {
    echo -e "${DIM}────────────────────────────────────────────────────────────${NC}"
}

header() {
    echo ""
    echo -e "${BOLD}$1${NC}"
    divider
}

# Expected sizes (KiB) - for progress calculation
# Source: OpenAlex S3 bucket actual sizes (Jan 2026)
declare -A EXPECTED_SIZES_KB=(
    ["works"]=731906048    # ~698 GiB
    ["authors"]=62070784   # ~59 GiB
    ["institutions"]=168960 # ~165 MiB
    ["sources"]=129024      # ~126 MiB
    ["funders"]=7885        # ~7.7 MiB
    ["concepts"]=6349       # ~6.2 MiB
    ["topics"]=5018         # ~4.9 MiB
    ["publishers"]=1912     # ~1.9 MiB
    ["subfields"]=323       # ~323 KiB
    ["fields"]=15           # ~15 KiB
    ["domains"]=9           # ~9 KiB
)

# ============================================================
# HEADER
# ============================================================
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║          OPENALEX LOCAL - STATUS REPORT                  ║${NC}"
echo -e "${BOLD}║          $(date '+%Y-%m-%d %H:%M:%S')                           ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"

# ============================================================
# ACTIVE DOWNLOADS
# ============================================================
header "ACTIVE DOWNLOADS"

SCREENS=$(screen -ls 2>/dev/null | grep -E "openalex" || true)
if [[ -n "$SCREENS" ]]; then
    while IFS= read -r line; do
        SESSION=$(echo "$line" | awk '{print $1}')
        STATUS=$(echo "$line" | grep -oP '\(.*\)')
        echo -e "${GREEN}${RUN}${NC} $SESSION $STATUS"
    done <<< "$SCREENS"

    # Show recent log activity
    if [[ -f "${LOG_DIR}/download_safe_run.log" ]]; then
        LAST_WORKS=$(tail -1 "${LOG_DIR}/download_safe_run.log" 2>/dev/null | head -c 60)
        [[ -n "$LAST_WORKS" ]] && echo -e "    ${DIM}works: ${LAST_WORKS}...${NC}"
    fi
    if [[ -f "${LOG_DIR}/download_others.log" ]]; then
        LAST_OTHER=$(tail -1 "${LOG_DIR}/download_others.log" 2>/dev/null | head -c 60)
        [[ -n "$LAST_OTHER" ]] && echo -e "    ${DIM}others: ${LAST_OTHER}...${NC}"
    fi

    echo ""
    echo -e "${DIM}  Attach: screen -r <session>  |  Detach: Ctrl-A D${NC}"
    echo -e "${DIM}  Logs:   tail -f logs/download_safe_run.log${NC}"
    echo -e "${DIM}          tail -f logs/download_others.log${NC}"
else
    echo -e "${INFO} No active downloads"
    echo -e "    ${DIM}Start: make download${NC}"
fi

# ============================================================
# SNAPSHOT PROGRESS (ALL ENTITIES)
# ============================================================
header "SNAPSHOT PROGRESS"

# Entity list (ordered by size)
ENTITIES=("works" "authors" "institutions" "sources" "funders" "concepts" "topics" "publishers" "subfields" "fields" "domains")

TOTAL_EXPECTED_KB=0
TOTAL_DOWNLOADED_KB=0

printf "%-15s %10s %10s %8s\n" "Entity" "Size" "Expected" "Status"
echo -e "${DIM}─────────────────────────────────────────────────────${NC}"

for entity in "${ENTITIES[@]}"; do
    DIR="${SNAPSHOT_DIR}/${entity}"
    EXPECTED_KB=${EXPECTED_SIZES_KB[$entity]:-1}
    TOTAL_EXPECTED_KB=$((TOTAL_EXPECTED_KB + EXPECTED_KB))

    if [[ -d "$DIR" ]]; then
        # Get actual size in KB
        SIZE_BYTES=$(du -sb "$DIR" 2>/dev/null | cut -f1 || echo 0)
        SIZE_KB=$((SIZE_BYTES / 1024))
        SIZE_HR=$(du -sh "$DIR" 2>/dev/null | cut -f1 || echo "0")
        TOTAL_DOWNLOADED_KB=$((TOTAL_DOWNLOADED_KB + SIZE_KB))

        # Calculate percentage
        if [[ "$EXPECTED_KB" -gt 0 ]]; then
            PCT=$((SIZE_KB * 100 / EXPECTED_KB))
            [[ "$PCT" -gt 100 ]] && PCT=100
        else
            PCT=100
        fi

        # Format expected size for display
        if [[ "$EXPECTED_KB" -ge 1048576 ]]; then
            EXPECTED_HR="~$((EXPECTED_KB / 1048576))G"
        elif [[ "$EXPECTED_KB" -ge 1024 ]]; then
            EXPECTED_HR="~$((EXPECTED_KB / 1024))M"
        else
            EXPECTED_HR="~${EXPECTED_KB}K"
        fi

        # Status indicator
        if [[ "$PCT" -ge 95 ]]; then
            STATUS="${GREEN}Complete${NC}"
        elif [[ "$PCT" -gt 0 ]]; then
            STATUS="${YELLOW}${PCT}%${NC}"
        else
            STATUS="${DIM}Empty${NC}"
        fi

        printf "%-15s %10s %10s %b\n" "$entity" "$SIZE_HR" "$EXPECTED_HR" "$STATUS"
    else
        if [[ "$EXPECTED_KB" -ge 1048576 ]]; then
            EXPECTED_HR="~$((EXPECTED_KB / 1048576))G"
        elif [[ "$EXPECTED_KB" -ge 1024 ]]; then
            EXPECTED_HR="~$((EXPECTED_KB / 1024))M"
        else
            EXPECTED_HR="~${EXPECTED_KB}K"
        fi
        printf "%-15s %10s %10s %s\n" "$entity" "-" "$EXPECTED_HR" "Not started"
    fi
done

echo -e "${DIM}─────────────────────────────────────────────────────${NC}"
TOTAL_GB=$((TOTAL_DOWNLOADED_KB / 1048576))
TOTAL_EXPECTED_GB=$((TOTAL_EXPECTED_KB / 1048576))
TOTAL_PCT=$((TOTAL_DOWNLOADED_KB * 100 / TOTAL_EXPECTED_KB))
printf "%-15s %10s %10s %s\n" "TOTAL" "${TOTAL_GB}G" "~${TOTAL_EXPECTED_GB}G" "${TOTAL_PCT}%"

# ETA calculation
if [[ "$TOTAL_DOWNLOADED_KB" -gt 0 ]] && [[ "$TOTAL_DOWNLOADED_KB" -lt "$TOTAL_EXPECTED_KB" ]]; then
    REMAINING_GB=$(( (TOTAL_EXPECTED_KB - TOTAL_DOWNLOADED_KB) / 1048576 ))
    # Assume 5MB/s = 18GB/hour
    ETA_HOURS=$((REMAINING_GB / 18))
    echo ""
    echo -e "${INFO} Remaining: ~${REMAINING_GB} GB"
    echo -e "${INFO} ETA at 5MB/s: ~${ETA_HOURS} hours"
fi

# ============================================================
# PREREQUISITES
# ============================================================
header "PREREQUISITES"

# Python
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    echo -e "${GREEN}${CHECK}${NC} Python: $PY_VER"
else
    echo -e "${RED}${CROSS}${NC} Python: NOT FOUND"
fi

# AWS CLI
if command -v aws &>/dev/null; then
    AWS_VER=$(aws --version 2>&1 | cut -d' ' -f1 | cut -d'/' -f2)
    echo -e "${GREEN}${CHECK}${NC} AWS CLI: $AWS_VER"
else
    echo -e "${RED}${CROSS}${NC} AWS CLI: NOT INSTALLED"
    echo -e "         ${DIM}Install: pip install awscli${NC}"
fi

# Screen
if command -v screen &>/dev/null; then
    echo -e "${GREEN}${CHECK}${NC} Screen: available"
else
    echo -e "${YELLOW}${WARN}${NC} Screen: not installed (recommended for downloads)"
fi

# ============================================================
# DISK SPACE
# ============================================================
header "DISK SPACE"

if [[ -d "$DATA_DIR" ]]; then
    DISK_INFO=$(df -h "$DATA_DIR" 2>/dev/null | tail -1)
    DISK_AVAIL=$(echo "$DISK_INFO" | awk '{print $4}')
    DISK_USED=$(echo "$DISK_INFO" | awk '{print $3}')
    DISK_PCT=$(echo "$DISK_INFO" | awk '{print $5}')
    echo -e "${INFO} Available: ${BOLD}$DISK_AVAIL${NC} (Used: $DISK_USED, $DISK_PCT)"

    AVAIL_GB=$(df -BG "$DATA_DIR" 2>/dev/null | tail -1 | awk '{print $4}' | tr -d 'G')
    if [[ "$AVAIL_GB" -lt 800 ]]; then
        echo -e "${YELLOW}${WARN}${NC} Recommend 800GB+ for full snapshot (~760GB)"
    fi
fi

# ============================================================
# DATABASE STATUS
# ============================================================
header "DATABASE"

if [[ -z "$CORPUS_DSN" ]]; then
    echo -e "${YELLOW}${WARN}${NC} Corpus address unresolved"
    echo -e "    ${DIM}scitex_dev.store.host_store could not answer; is scitex-dev installed?${NC}"
elif ! command -v psql &>/dev/null; then
    echo -e "${YELLOW}${WARN}${NC} psql not installed — cannot query the corpus"
    echo -e "    ${DIM}Address: $CORPUS_DSN${NC}"
elif corpus_has works; then
    DB_SIZE=$(corpus_q "SELECT pg_size_pretty(pg_total_relation_size('works'));")
    echo -e "${GREEN}${CHECK}${NC} Corpus works table: ${BOLD}${DB_SIZE:-?}${NC}"

    WORKS_COUNT=$(corpus_q "SELECT COUNT(*) FROM works;")
    echo -e "${INFO} Works: ${WORKS_COUNT:-?} rows"

    if corpus_has idx_works_search_vector; then
        echo -e "${GREEN}${CHECK}${NC} Full-text index: built"
    else
        echo -e "${YELLOW}${WARN}${NC} Full-text index: not built (run: make build-fts)"
    fi
else
    echo -e "${INFO} Not built yet"
    echo -e "    ${DIM}Run: make build-db  (after snapshot download)${NC}"
fi

# ============================================================
# SOURCES & CITATIONS (Impact Factor)
# ============================================================
header "IMPACT FACTOR DATA"

if corpus_has works; then
    # Sources table
    if corpus_has sources; then
        SOURCES_COUNT=$(corpus_q "SELECT COUNT(*) FROM sources;")
        echo -e "${GREEN}${CHECK}${NC} Sources table: ${SOURCES_COUNT:-?} journals"
    else
        echo -e "${INFO} Sources table: not built"
        echo -e "    ${DIM}Run: make build-sources (fast, ~30 sec)${NC}"
    fi

    # Citations table
    if corpus_has citations; then
        CITATIONS_COUNT=$(corpus_q "SELECT COUNT(*) FROM citations;")
        echo -e "${GREEN}${CHECK}${NC} Citations table: ${CITATIONS_COUNT:-?} rows"
    elif corpus_has _citations_build_progress; then
        PROGRESS=$(corpus_q "SELECT last_work_id || '|' || records_processed || '|' || citations_inserted FROM _citations_build_progress ORDER BY last_work_id DESC LIMIT 1;")
        if [[ -n "$PROGRESS" ]]; then
            LAST_WORK_ID=$(echo "$PROGRESS" | cut -d'|' -f1)
            CITS=$(echo "$PROGRESS" | cut -d'|' -f3)
            MAX_WORK_ID=$(corpus_q "SELECT COALESCE(MAX(id), 0) FROM works;")
            if [[ -n "$MAX_WORK_ID" ]] && [[ "$MAX_WORK_ID" -gt 0 ]]; then
                PCT=$((LAST_WORK_ID * 100 / MAX_WORK_ID))
                echo -e "${YELLOW}${RUN}${NC} Citations table: building... ${PCT}% (${CITS} citations)"
            else
                echo -e "${YELLOW}${RUN}${NC} Citations table: building... (${CITS} citations)"
            fi
        fi
    else
        echo -e "${INFO} Citations table: not built"
        echo -e "    ${DIM}Run: make build-citations (slow, ~50-70h)${NC}"
    fi

    # Citations indexes
    CITATIONS_INDEXES=$(corpus_q "SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'citations';")
    CITATIONS_INDEXES=${CITATIONS_INDEXES:-0}
    if [[ "$CITATIONS_INDEXES" -gt 0 ]]; then
        INDEXES_LIST=$(corpus_q "SELECT string_agg(indexname, ', ') FROM pg_indexes WHERE tablename = 'citations';")
        if [[ "$CITATIONS_INDEXES" -ge 3 ]]; then
            echo -e "${GREEN}${CHECK}${NC} Citations indexes: ${CITATIONS_INDEXES}/3 complete"
        else
            echo -e "${YELLOW}${RUN}${NC} Citations indexes: ${CITATIONS_INDEXES}/3 (${INDEXES_LIST})"
        fi
    fi

    # Works IF indexes (issn, issn_year)
    if corpus_has idx_works_issn_year; then
        echo -e "${GREEN}${CHECK}${NC} Works IF indexes: built"
    elif corpus_has citations; then
        echo -e "${YELLOW}${WARN}${NC} Works IF indexes: not built"
        echo -e "    ${DIM}Run: make build-if-indexes${NC}"
    fi

    # Show active build sessions
    INDEX_SCREEN=$(screen -ls 2>/dev/null | grep -E "openalex-(build-citations|create-indexes|build-if-indexes|if-indexes)" || true)
    if [[ -n "$INDEX_SCREEN" ]]; then
        echo ""
        echo -e "${YELLOW}${RUN}${NC} Index build active:"
        while IFS= read -r line; do
            SESSION=$(echo "$line" | awk '{print $1}' | cut -d. -f2)
            echo -e "    ${DIM}${SESSION}${NC}"
        done <<< "$INDEX_SCREEN"
        echo -e "    ${DIM}Monitor: tail -f logs/create_indexes.log${NC}"
        echo -e "    ${DIM}         tail -f logs/build_if_indexes.log${NC}"
    fi
else
    echo -e "${INFO} Corpus not built yet (or unreachable)"
fi

# ============================================================
# QUICK REFERENCE
# ============================================================
header "QUICK REFERENCE"

echo -e "${CYAN}Download Commands:${NC}"
echo -e "  ${DIM}make download${NC}          Start/resume download (all entities)"
echo -e "  ${DIM}make download-works${NC}    Download works only (698GB)"
echo -e "  ${DIM}make download-others${NC}   Download other entities (60GB)"
echo ""
echo -e "${CYAN}Monitor Commands:${NC}"
echo -e "  ${DIM}make status${NC}            Show this report"
echo -e "  ${DIM}screen -r <session>${NC}    Attach to download session"
echo -e "  ${DIM}tail -f logs/*.log${NC}     Watch download logs"
echo ""
echo -e "${CYAN}Build Commands:${NC}"
echo -e "  ${DIM}make build-db${NC}          Build the corpus"
echo -e "  ${DIM}make build-fts${NC}         Build full-text search index"
echo ""
echo -e "${CYAN}Impact Factor (Optional):${NC}"
echo -e "  ${DIM}make build-sources${NC}     Journal metadata (~30 sec)"
echo -e "  ${DIM}make build-citations${NC}   Citation graph (~3-4h data)"
echo -e "  ${DIM}make build-if-indexes${NC}  All IF indexes (~8-10h)"

# ============================================================
# NOTIFICATIONS
# ============================================================
WARNINGS=()

# Check AWS CLI
if ! command -v aws &>/dev/null; then
    WARNINGS+=("AWS CLI not installed - required for download")
fi

# Check for stale downloads (no screen but incomplete data)
if [[ -z "$SCREENS" ]]; then
    if [[ "$TOTAL_DOWNLOADED_KB" -gt 0 ]] && [[ "$TOTAL_PCT" -lt 95 ]]; then
        WARNINGS+=("Download incomplete (${TOTAL_PCT}%) - run 'make download' to resume")
    fi
fi

# Check disk space
if [[ -d "$DATA_DIR" ]]; then
    AVAIL_GB=$(df -BG "$DATA_DIR" 2>/dev/null | tail -1 | awk '{print $4}' | tr -d 'G')
    REMAINING_GB=$(( (TOTAL_EXPECTED_KB - TOTAL_DOWNLOADED_KB) / 1048576 ))
    if [[ "$AVAIL_GB" -lt "$REMAINING_GB" ]]; then
        WARNINGS+=("Insufficient disk space: need ~${REMAINING_GB}GB, have ${AVAIL_GB}GB")
    fi
fi

if [[ ${#WARNINGS[@]} -gt 0 ]]; then
    header "⚠ NOTIFICATIONS"
    for w in "${WARNINGS[@]}"; do
        echo -e "${YELLOW}!${NC} $w"
    done
fi

echo ""
