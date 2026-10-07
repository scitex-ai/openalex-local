"""Tests for the completion drop-in contract v1.

All install-behavior tests run with an isolated temp HOME so they never
touch the real ``~/.scitex`` or shell rc files. Environment isolation uses
plain ``os.environ`` save/restore (no mocks): the no-mocks rule (PA-306)
bans the ``monkeypatch`` fixture outright, and each test carries exactly
one assertion (PA-307).
"""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from openalex_local._cli.cli import cli
from openalex_local._cli.completion import _cache_path

PROG = "openalex-local"
EXPECTED_REL = Path(".scitex") / "openalex-local" / "runtime" / "completion" / PROG


@pytest.fixture
def isolated_home(tmp_path):
    """Point HOME at tmp_path and clear SCITEX_DIR (both restored after)."""
    previous_home = os.environ.get("HOME")
    previous_scitex_dir = os.environ.get("SCITEX_DIR")
    os.environ["HOME"] = str(tmp_path)
    os.environ.pop("SCITEX_DIR", None)
    try:
        yield tmp_path
    finally:
        if previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous_home
        if previous_scitex_dir is None:
            os.environ.pop("SCITEX_DIR", None)
        else:
            os.environ["SCITEX_DIR"] = previous_scitex_dir


@pytest.fixture
def custom_scitex_home(tmp_path):
    """Point HOME and SCITEX_DIR at separate temp dirs (restored after)."""
    home = tmp_path / "home"
    home.mkdir()
    scitex_dir = tmp_path / "custom-scitex"
    previous_home = os.environ.get("HOME")
    previous_scitex_dir = os.environ.get("SCITEX_DIR")
    os.environ["HOME"] = str(home)
    os.environ["SCITEX_DIR"] = str(scitex_dir)
    try:
        yield home, scitex_dir
    finally:
        if previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous_home
        if previous_scitex_dir is None:
            os.environ.pop("SCITEX_DIR", None)
        else:
            os.environ["SCITEX_DIR"] = previous_scitex_dir


@pytest.fixture
def runner():
    """Return a Click CLI runner."""
    return CliRunner()


def _install(runner, *args):
    """Invoke ``completion install`` with the given extra args."""
    return runner.invoke(cli, ["completion", "install", *args])


class TestCompletionInstall:
    """Test `completion install` writes the drop-in file."""

    def test_install_exits_zero(self, runner, isolated_home):
        # Arrange
        args = ("--shell", "bash", "--yes")
        # Act
        result = _install(runner, *args)
        # Assert
        assert result.exit_code == 0

    def test_install_writes_dropin_file(self, runner, isolated_home):
        # Arrange
        args = ("--shell", "bash", "--yes")
        # Act
        _install(runner, *args)
        # Assert
        assert (isolated_home / EXPECTED_REL).is_file()

    def test_install_prints_dropin_path(self, runner, isolated_home):
        # Arrange
        args = ("--shell", "bash", "--yes")
        # Act
        result = _install(runner, *args)
        # Assert
        assert str(isolated_home / EXPECTED_REL) in result.output

    def test_install_default_shell_exits_zero(self, runner, isolated_home):
        # Arrange
        args = ()
        # Act
        result = _install(runner, *args)
        # Assert
        assert result.exit_code == 0

    def test_install_default_shell_writes_dropin_file(self, runner, isolated_home):
        # Arrange
        args = ()
        # Act
        _install(runner, *args)
        # Assert
        assert (isolated_home / EXPECTED_REL).is_file()

    def test_install_second_run_exits_zero(self, runner, isolated_home):
        # Arrange
        _install(runner, "--shell", "bash", "--yes")
        # Act
        result = _install(runner, "--shell", "bash", "--yes")
        # Assert
        assert result.exit_code == 0

    def test_install_repeated_writes_stay_identical(self, runner, isolated_home):
        # Arrange
        _install(runner, "--shell", "bash", "--yes")
        content_first = (isolated_home / EXPECTED_REL).read_text()
        # Act
        _install(runner, "--shell", "bash", "--yes")
        content_second = (isolated_home / EXPECTED_REL).read_text()
        # Assert
        assert content_first == content_second

    def test_install_leaves_bashrc_content_unchanged(self, runner, isolated_home):
        # Arrange
        bashrc = isolated_home / ".bashrc"
        bashrc.write_text("# user bashrc\n")
        # Act
        _install(runner, "--yes")
        # Assert
        assert bashrc.read_text() == "# user bashrc\n"

    def test_install_leaves_zshrc_content_unchanged(self, runner, isolated_home):
        # Arrange
        zshrc = isolated_home / ".zshrc"
        zshrc.write_text("# user zshrc\n")
        # Act
        _install(runner, "--yes")
        # Assert
        assert zshrc.read_text() == "# user zshrc\n"

    def test_install_custom_scitex_dir_exits_zero(self, runner, custom_scitex_home):
        # Arrange
        args = ("--yes",)
        # Act
        result = _install(runner, *args)
        # Assert
        assert result.exit_code == 0

    def test_install_custom_scitex_dir_writes_expected_file(
        self, runner, custom_scitex_home
    ):
        # Arrange
        _, scitex_dir = custom_scitex_home
        expected = scitex_dir / "openalex-local" / "runtime" / "completion" / PROG
        # Act
        _install(runner, "--yes")
        # Assert
        assert expected.is_file()

    def test_install_custom_scitex_dir_prints_expected_path(
        self, runner, custom_scitex_home
    ):
        # Arrange
        _, scitex_dir = custom_scitex_home
        expected = scitex_dir / "openalex-local" / "runtime" / "completion" / PROG
        # Act
        result = _install(runner, "--yes")
        # Assert
        assert str(expected) in result.output

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
    def test_install_shell_variant_exits_zero(self, runner, isolated_home, shell):
        # Arrange
        args = ("--shell", shell, "--yes")
        # Act
        result = _install(runner, *args)
        # Assert
        assert result.exit_code == 0

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
    def test_install_shell_variant_writes_dropin_file(
        self, runner, isolated_home, shell
    ):
        # Arrange
        args = ("--shell", shell, "--yes")
        # Act
        _install(runner, *args)
        # Assert
        assert (isolated_home / EXPECTED_REL).is_file()

    def test_install_dry_run_exits_zero(self, runner, isolated_home):
        # Arrange
        args = ("--dry-run",)
        # Act
        result = _install(runner, *args)
        # Assert
        assert result.exit_code == 0

    def test_install_dry_run_reports_target_path(self, runner, isolated_home):
        # Arrange
        args = ("--dry-run",)
        # Act
        result = _install(runner, *args)
        # Assert
        assert str(isolated_home / EXPECTED_REL) in result.output

    def test_install_dry_run_writes_no_file(self, runner, isolated_home):
        # Arrange
        args = ("--dry-run",)
        # Act
        _install(runner, *args)
        # Assert
        assert not (isolated_home / EXPECTED_REL).exists()


class TestCompletionStatus:
    """Test `completion status` checks the drop-in file."""

    def test_status_before_install_exits_zero(self, runner, isolated_home):
        # Arrange
        args = ["completion", "status"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_status_before_install_reports_missing(self, runner, isolated_home):
        # Arrange
        args = ["completion", "status"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert "not installed" in result.output.lower()

    def test_status_before_install_prints_expected_path(self, runner, isolated_home):
        # Arrange
        args = ["completion", "status"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert str(isolated_home / EXPECTED_REL) in result.output

    def test_status_after_install_exits_zero(self, runner, isolated_home):
        # Arrange
        _install(runner, "--yes")
        args = ["completion", "status"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.exit_code == 0

    def test_status_after_install_reports_installed(self, runner, isolated_home):
        # Arrange
        _install(runner, "--yes")
        args = ["completion", "status"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert result.output.startswith("Completion installed:")

    def test_status_after_install_prints_expected_path(self, runner, isolated_home):
        # Arrange
        _install(runner, "--yes")
        args = ["completion", "status"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert str(isolated_home / EXPECTED_REL) in result.output

    def test_status_json_before_install_marks_uninstalled(
        self, runner, isolated_home
    ):
        # Arrange
        args = ["completion", "status", "--json"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert json.loads(result.output)["installed"] is False

    def test_status_json_after_install_marks_installed(self, runner, isolated_home):
        # Arrange
        _install(runner, "--yes")
        args = ["completion", "status", "--json"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert json.loads(result.output)["installed"] is True

    def test_status_json_carries_dropin_path(self, runner, isolated_home):
        # Arrange
        _install(runner, "--yes")
        args = ["completion", "status", "--json"]
        # Act
        result = runner.invoke(cli, args)
        # Assert
        assert json.loads(result.output)["path"] == str(isolated_home / EXPECTED_REL)


class TestCompletionCachePath:
    """Test the drop-in path convention."""

    def test_cache_path_matches_expected_convention(self, isolated_home):
        # Arrange
        prog = PROG
        # Act
        cache = _cache_path(prog)
        # Assert
        assert cache == isolated_home / EXPECTED_REL

    def test_cache_path_uses_custom_scitex_dir(self, custom_scitex_home):
        # Arrange
        _, scitex_dir = custom_scitex_home
        # Act
        cache = _cache_path(PROG)
        # Assert
        assert cache == scitex_dir / "openalex-local" / "runtime" / "completion" / PROG
