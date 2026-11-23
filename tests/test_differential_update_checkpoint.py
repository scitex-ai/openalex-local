"""Regression tests for incomplete OpenAlex snapshot updates."""

import gzip
import os
import subprocess
import sys

import pytest

from openalex_local._core._differential_update import process_date_directory


@pytest.mark.parametrize(
    ("listing", "expected_error"),
    [
        ("exit 7", "returned non-zero exit status 7"),
        ("printf 'PRE updated_date=2026-11-02/\\n'", "partitions missing or empty"),
    ],
)
def test_incomplete_snapshot_stops_before_opening_corpus(tmp_path, listing, expected_error):
    # Arrange
    aws = tmp_path / "aws"
    aws.write_text("#!/bin/sh\n" + listing + "\n")
    aws.chmod(0o700)
    args = [
        sys.executable, "-c",
        "from openalex_local._core._differential_update import differential_update; "
        "from pathlib import Path; import sys; "
        "differential_update('invalid-dsn', Path(sys.argv[1]), "
        "since='2026-11-01', skip_download=True)",
        str(tmp_path),
    ]

    # Act
    result = subprocess.run(
        args,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )

    # Assert
    assert (result.returncode, expected_error in result.stderr) == (1, True)


def test_malformed_snapshot_record_aborts_partition(tmp_path):
    # Arrange
    (tmp_path / "records.gz").write_bytes(gzip.compress(b"malformed JSON\n"))

    # Act
    try:
        process_date_directory(tmp_path, conn=None)
    except ValueError as error:
        message = str(error)
    else:
        message = ""

    # Assert
    assert message.startswith("Expecting value")
