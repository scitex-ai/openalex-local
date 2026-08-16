"""Runtime cross-package import gate (PS-140 §2)."""

import importlib

import pytest

CROSS_PACKAGE_IMPORTS = [
    "scitex.cli.introspect",
    "scitex_dev",
    "scitex_dev._cli._completion",
    "scitex_dev.cli",
    "scitex_dev.system_deps",
]


@pytest.mark.parametrize("module_path", CROSS_PACKAGE_IMPORTS)
def test_cross_package_module_is_importable(module_path: str) -> None:
    """Test each declared cross-package module imports at runtime."""
    # Arrange
    pytest.importorskip(module_path)
    # Act
    module = importlib.import_module(module_path)
    # Assert
    assert module is not None
