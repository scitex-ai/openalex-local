"""Shared test fixtures for openalex_local tests.

Module-import-time also wires subprocess coverage (parallel +
COVERAGE_PROCESS_START + an idempotent .pth shim). `os.environ.setdefault`
would be a no-op here because pytest-cov has already set COVERAGE_FILE to
a tmp dir by the time conftest is loaded — we force-set instead.

See: scitex_dev skill leaf 05_development_06_subprocess-coverage.md.
"""
from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Pin coverage's data file at the repo root and point process_startup at
# our pyproject so child interpreters configure themselves correctly.
os.environ["COVERAGE_PROCESS_START"] = str(_PROJECT_ROOT / "pyproject.toml")
os.environ["COVERAGE_FILE"] = str(_PROJECT_ROOT / ".coverage")


def _ensure_subprocess_coverage_shim() -> None:
    """Drop an idempotent .pth file in site-packages that auto-starts
    coverage in every child Python interpreter via
    ``coverage.process_startup()``.
    """
    purelib = Path(sysconfig.get_paths()["purelib"])
    pth = purelib / "_openalex_local_subprocess_coverage.pth"
    shim = (
        "import os, coverage\n"
        "if os.environ.get('COVERAGE_PROCESS_START'):\n"
        "    coverage.process_startup()\n"
    )
    try:
        if not pth.exists() or pth.read_text() != shim:
            pth.write_text(shim)
    except OSError:
        # site-packages may be read-only (e.g. system Python); silently
        # skip — local dev venvs are writable and that's where this matters.
        pass


_ensure_subprocess_coverage_shim()


from openalex_local._core.config import Config


# Sample OpenAlex IDs for testing (known to exist in most datasets)
SAMPLE_OPENALEX_IDS = [
    "W2741809807",  # "The state of OA" - well-known paper
    "W2100837269",  # Nature paper
]

# Sample DOIs for testing
SAMPLE_DOIS = [
    "10.7717/peerj.4375",  # "The state of OA"
]


@pytest.fixture
def sample_openalex_id():
    """Return a sample OpenAlex ID."""
    return SAMPLE_OPENALEX_IDS[0]


@pytest.fixture
def sample_doi():
    """Return a sample DOI."""
    return SAMPLE_DOIS[0]


@pytest.fixture
def db_available():
    """Whether the corpus is reachable AND holds a works table.

    Both halves, deliberately. The previous version asked only whether a FILE
    existed, so an empty or half-built database counted as available and every
    test guarded by it then failed one layer down on a missing table.
    """
    from openalex_local._core.db import corpus_available

    Config.reset()
    return corpus_available()


@pytest.fixture
def reset_config():
    """Reset configuration before and after test."""
    Config.reset()
    yield
    Config.reset()


@pytest.fixture
def sample_work_data():
    """Return sample OpenAlex API response data."""
    return {
        "id": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.7717/peerj.4375",
        "title": "The state of OA: a large-scale analysis of the prevalence and impact of Open Access articles",
        "publication_year": 2018,
        "authorships": [
            {"author": {"display_name": "Heather Piwowar"}},
            {"author": {"display_name": "Jason Priem"}},
            {"author": {"display_name": "Vincent Larivière"}},
            {"author": {"display_name": "Juan Pablo Alperin"}},
            {"author": {"display_name": "Lisa Matthias"}},
            {"author": {"display_name": "Bree Norlander"}},
            {"author": {"display_name": "Ashley Farley"}},
            {"author": {"display_name": "Jevin West"}},
            {"author": {"display_name": "Stefanie Haustein"}},
        ],
        "abstract_inverted_index": {
            "Despite": [0],
            "growing": [1],
            "interest": [2],
            "in": [3, 15],
            "Open": [4],
            "Access": [5],
        },
        "primary_location": {
            "source": {
                "display_name": "PeerJ",
                "issn": ["2167-8359"],
                "host_organization_name": "PeerJ",
            }
        },
        "biblio": {
            "volume": "6",
            "issue": None,
            "first_page": "e4375",
        },
        "type": "journal-article",
        "cited_by_count": 1500,
        "concepts": [
            {"display_name": "Open access", "score": 0.95},
            {"display_name": "Citation", "score": 0.85},
        ],
        "topics": [
            {"display_name": "Scholarly Communication", "subfield": {"display_name": "Library Science"}},
        ],
        "open_access": {
            "is_oa": True,
            "oa_url": "https://peerj.com/articles/4375/",
        },
        "referenced_works": [
            "https://openalex.org/W123",
            "https://openalex.org/W456",
        ],
    }
