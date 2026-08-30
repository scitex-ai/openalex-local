"""Runtime cross-package import gate (PS-140 §2)."""

import importlib

import pytest

CROSS_PACKAGE_IMPORTS = [
    "scitex.cli.introspect",
    "scitex_dev",
    "scitex_dev._cli._completion",
    "scitex_dev.cli",
    "scitex_dev.ecosystem",
    # The store primitive. It resolves where the corpus lives, so this one is
    # not optional in any install: `scitex-dev>=0.57.0` is a hard dependency.
    "scitex_dev.store",
    "scitex_dev.system_deps",
]


@pytest.mark.parametrize("module_path", CROSS_PACKAGE_IMPORTS)
def test_cross_package_module_is_importable(module_path: str) -> None:
    """Test each declared cross-package module imports at runtime.

    The skip is on the ROOT distribution and the import is of the FULL path.
    Skipping on the full path would make a RENAMED submodule raise
    ModuleNotFoundError, get swallowed as a skip, and report green — which is
    the exact drift this gate exists to catch. Dropping the skip entirely is
    also wrong: a lean install where the peer is legitimately absent (an
    optional extra, or a marker-gated dependency) would fail rather than skip.
    """
    # Arrange
    pytest.importorskip(module_path.split(".")[0])
    # Act
    module = importlib.import_module(module_path)
    # Assert
    assert module is not None
