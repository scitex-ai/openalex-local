#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: tests/test_update_cli_refuses_without_yes.py
"""`openalex-local update` refuses without --yes instead of prompting.

Ecosystem doctrine §2: no interactive prompts. This command's primary caller
is a systemd timer, where a prompt does not ask anybody anything -- it hangs,
or it reads EOF and silently takes the default. Refusing puts the missing flag
in the exit status where an unattended caller can see it.

Exit 2 is the conventional usage-error code, and is deliberately distinct from
the exit 1 the command uses when the update itself fails: "you forgot a flag"
and "the update broke" are different outcomes and must not share a code.
"""

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def update_cmd():
    from openalex_local._cli.update import update_cmd as cmd

    return cmd


def test_refuses_without_yes(runner, update_cmd):
    # Arrange: no --yes, no --dry-run -- the unattended-caller mistake
    args = []
    # Act
    result = runner.invoke(update_cmd, args)
    # Assert
    assert result.exit_code == 2, (
        "expected the usage-error code 2; got "
        f"{result.exit_code}. Output: {result.output!r}"
    )


def test_refusal_names_the_flag_to_use(runner, update_cmd):
    # Arrange: an error that does not say what to do is half-written
    args = []
    # Act
    result = runner.invoke(update_cmd, args)
    # Assert
    assert "--yes" in result.output, (
        f"the refusal must name the remedy; got {result.output!r}"
    )


def test_does_not_prompt_when_stdin_is_closed(runner, update_cmd):
    """A prompt would consume stdin; a refusal must not."""
    # Arrange
    args = []
    # Act
    result = runner.invoke(update_cmd, args, input="")
    # Assert
    assert "Abort" not in result.output, (
        "output looks like a click prompt was still being used; a refusal "
        f"should never reach the abort path. Got {result.output!r}"
    )


def test_dry_run_is_not_refused(runner, update_cmd):
    """--dry-run changes nothing, so it must not require --yes.

    Asserted on the refusal MESSAGE rather than on the exit code. Without a
    database configured, --dry-run fails later for an unrelated reason, and an
    exit-code assertion would then pass for the wrong reason -- green while
    proving nothing. The absence of the refusal text is the actual contract.
    """
    # Arrange
    args = ["--dry-run"]
    # Act
    result = runner.invoke(update_cmd, args)
    # Assert
    assert "Refusing to update" not in result.output, (
        f"--dry-run must not hit the refuse-without-yes path; got {result.output!r}"
    )


# EOF
