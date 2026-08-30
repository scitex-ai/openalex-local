"""Tests for openalex_local CLI."""

import pytest
from click.testing import CliRunner
from openalex_local._cli.cli import cli

try:
    from scitex_dev import get_tools_sync  # noqa: F401

    _has_scitex_dev = True
except ImportError:
    _has_scitex_dev = False


@pytest.fixture
def runner():
    """Return a Click CLI runner."""
    return CliRunner()


class TestCLIHelp:
    """Test CLI --help output for each command."""

    def test_root_help_exits_zero(self, runner):
        """Test the root --help exits with status zero."""
        # Arrange
        args = ["--help"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_root_help_mentions_a_command(self, runner):
        """Test the root --help lists at least the search command."""
        # Arrange
        args = ["--help"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert "search" in result.output

    def test_version_exits_zero(self, runner):
        """Test --version exits with status zero."""
        # Arrange
        args = ["--version"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_version_prints_zero_dot_series(self, runner):
        """Test --version prints a 0.x version string."""
        # Arrange
        args = ["--version"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert "0." in result.output

    def test_help_recursive_exits_zero(self, runner):
        """Test --help-recursive exits with status zero."""
        # Arrange
        args = ["--help-recursive"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_help_recursive_lists_mcp_command(self, runner):
        """Test --help-recursive surfaces the nested mcp command."""
        # Arrange
        args = ["--help-recursive"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert "mcp" in result.output

    def test_search_help_exits_zero(self, runner):
        """Test search --help exits with status zero."""
        # Arrange
        args = ["search", "--help"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_status_help_exits_zero(self, runner):
        """Test status --help exits with status zero."""
        # Arrange
        args = ["status", "--help"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_mcp_help_exits_zero(self, runner):
        """Test mcp --help exits with status zero."""
        # Arrange
        args = ["mcp", "--help"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_mcp_list_tools_help_exits_zero(self, runner):
        """Test mcp list-tools --help exits with status zero."""
        # Arrange
        args = ["mcp", "list-tools", "--help"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_mcp_doctor_help_exits_zero(self, runner):
        """Test mcp doctor --help exits with status zero."""
        # Arrange
        args = ["mcp", "doctor", "--help"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_mcp_installation_help_exits_zero(self, runner):
        """Test mcp installation --help exits with status zero."""
        # Arrange
        args = ["mcp", "installation", "--help"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_mcp_start_help_exits_zero(self, runner):
        """Test mcp start --help exits with status zero."""
        # Arrange
        args = ["mcp", "start", "--help"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0


class TestCLICommands:
    """Test CLI command execution (without database)."""

    @pytest.mark.skipif(
        not _has_scitex_dev,
        reason="scitex_dev not installed",
    )
    def test_mcp_list_tools_runs_clean(self, runner):
        """Test mcp list-tools runs and exits with status zero."""
        # Arrange
        args = ["mcp", "list-tools"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_mcp_installation_exits_zero(self, runner):
        """Test mcp installation runs and exits with status zero."""
        # Arrange
        args = ["mcp", "installation"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_mcp_installation_mentions_mcp(self, runner):
        """Test mcp installation output references mcp setup."""
        # Arrange
        args = ["mcp", "installation"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert "mcp" in result.output.lower() or "install" in result.output.lower()

    def test_mcp_doctor_does_not_crash(self, runner):
        """Test mcp doctor runs to a clean exit code without crashing."""
        # Arrange
        args = ["mcp", "doctor"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code in (0, 1)


# ---------------------------------------------------------------------------
# `update` command
#
# The command loads its sync logic from a script whose path can be overridden
# via OPENALEX_LOCAL_DIFFERENTIAL_UPDATE_SCRIPT. Tests point that env var at a
# REAL fake script written into tmp_path (no monkeypatch of production
# internals): the fake records the kwargs it was called with to a JSON sidecar
# and returns a fixed stats dict, so we exercise the real loader + wiring
# against real bytes on disk.
# ---------------------------------------------------------------------------

import json as _json
import os as _os

_FAKE_SCRIPT_TEMPLATE = """\
import json
import sys


def differential_update(**kwargs):
    calls_path = {calls_path!r}
    recorded = {{k: (str(v) if v is not None else None) for k, v in kwargs.items()}}
    with open(calls_path, "w") as fh:
        json.dump(recorded, fh)
    if kwargs.get("dry_run"):
        return {{
            "dates_processed": 0,
            "records_upserted": 0,
            "elapsed_seconds": 0,
            "dry_run": True,
            "last_sync_date": kwargs.get("since"),
        }}
    return {{
        "dates_processed": 2,
        "records_upserted": 42,
        "elapsed_seconds": 1.0,
        "last_sync_date": "2026-03-15",
    }}
"""


@pytest.fixture
def fake_update_script(tmp_path):
    """Write a real fake differential-update script and point the env at it.

    Yields the sidecar path where the fake records its call kwargs, so tests
    can assert the CLI wired arguments through without touching the network,
    the S3 snapshot, or a real database.
    """
    calls_path = tmp_path / "calls.json"
    script_path = tmp_path / "fake_differential_update.py"
    script_path.write_text(_FAKE_SCRIPT_TEMPLATE.format(calls_path=str(calls_path)))
    env_var = "OPENALEX_LOCAL_DIFFERENTIAL_UPDATE_SCRIPT"
    previous = _os.environ.get(env_var)
    _os.environ[env_var] = str(script_path)
    try:
        yield calls_path
    finally:
        if previous is None:
            _os.environ.pop(env_var, None)
        else:
            _os.environ[env_var] = previous


class TestUpdateCommand:
    """Test the `update` command wiring against a real fake script."""

    def setup_method(self):
        """Create a CLI runner."""
        self.runner = CliRunner()

    def test_update_help_lists_dry_run_flag(self):
        """Help comes from the canonical location, `db update`.

        The top-level `update` is now a deprecation alias, and an alias
        intercepts `--help` to announce the move rather than reprinting the
        target's options. The remaining tests in this class still invoke the
        alias, which is what pins the forwarding contract the systemd unit
        depends on.
        """
        # Arrange
        runner = CliRunner()
        # Act
        result = runner.invoke(cli, ["db", "update", "--help"])
        # Assert
        assert "--dry-run" in result.output

    def test_update_dry_run_exits_zero(self, fake_update_script):
        # Arrange
        runner = CliRunner()
        # Act
        result = runner.invoke(cli, ["update", "--dry-run"])
        # Assert
        assert result.exit_code == 0

    def test_update_dry_run_forwards_dry_run_true(self, fake_update_script):
        # Arrange
        runner = CliRunner()
        # Act
        runner.invoke(cli, ["update", "--dry-run"])
        # Assert
        assert _json.loads(fake_update_script.read_text())["dry_run"] == "True"

    def test_update_yes_forwards_since_value(self, fake_update_script):
        # Arrange
        runner = CliRunner()
        # Act
        runner.invoke(cli, ["update", "--yes", "--since", "2026-03-01"])
        # Assert
        assert _json.loads(fake_update_script.read_text())["since"] == "2026-03-01"

    def test_update_yes_forwards_dsn_value(self, fake_update_script):
        """The `--dsn` override reaches the update entry point verbatim.

        The flag used to be `--db` and carried a filesystem path. It carries a
        connection string now; a path is not accepted anywhere any more.
        """
        # Arrange
        runner = CliRunner()
        elsewhere = "postgresql://reader@example.invalid:55432/scitex"
        # Act
        runner.invoke(cli, ["update", "--yes", "--dsn", elsewhere])
        # Assert
        assert _json.loads(fake_update_script.read_text())["dsn"] == elsewhere

    def test_update_yes_unattended_exits_zero(self, fake_update_script):
        # Arrange
        runner = CliRunner()
        # Act
        result = runner.invoke(cli, ["update", "--yes"])
        # Assert
        assert result.exit_code == 0

    def test_update_quiet_prints_records_and_last_sync(self, fake_update_script):
        # Arrange
        runner = CliRunner()
        # Act
        result = runner.invoke(cli, ["update", "--yes", "--quiet"])
        # Assert
        assert result.output.strip() == "42 2026-03-15"

    def test_update_summary_reports_new_last_sync_date(self, fake_update_script):
        # Arrange
        runner = CliRunner()
        # Act
        result = runner.invoke(cli, ["update", "--yes"])
        # Assert
        assert "2026-03-15" in result.output

    def test_update_declined_confirm_exits_nonzero(self, fake_update_script):
        # Arrange
        runner = CliRunner()
        # Act
        result = runner.invoke(cli, ["update"], input="n\n")
        # Assert
        assert result.exit_code != 0
