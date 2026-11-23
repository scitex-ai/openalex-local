#!/usr/bin/env python3
"""Run the OpenAlex incremental updater from a repository checkout."""

from pathlib import Path

from openalex_local._core._differential_update import main


if __name__ == "__main__":
    main(Path(__file__).resolve().parents[2] / "data" / "snapshot" / "works")
