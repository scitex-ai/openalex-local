#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: tests/test_config.py
"""Tests for openalex_local._core.config.

WHAT CHANGED AND WHY THE OLD TESTS COULD NOT SURVIVE. These used to create a
temporary FILE and assert that the package found it. There is no file any
more: the corpus address comes from ``scitex_dev.store.host_store``, and the
package-local ``OPENALEX_LOCAL_DB`` variable it used to read is deleted. A
test that set that variable would now pass by asserting nothing.

So the resolution tests are rewritten to pin the property that replaced it:
the DSN this package uses is the one the store primitive resolves, and
``SCITEX_STORE_DSN`` is what moves it. No DSN is hardcoded here — the
expected value is read from the same resolver, so the test measures agreement
between the package and the primitive rather than agreement between the test
and a string somebody typed.
"""

import os

import pytest

from openalex_local._core.config import Config, corpus_target, get_dsn


class TestConfig:
    """Test Config class."""

    def setup_method(self):
        """Reset Config before each test."""
        Config.reset()
        # Clear environment variables
        self._original_env = {}
        for key in [
            "OPENALEX_LOCAL_API_URL",
            "OPENALEX_LOCAL_MODE",
        ]:
            self._original_env[key] = os.environ.pop(key, None)

    def teardown_method(self):
        """Restore environment after each test."""
        Config.reset()
        for key, value in self._original_env.items():
            if value is not None:
                os.environ[key] = value

    def test_get_mode_default_is_auto(self):
        """Test that the default internal mode is auto."""
        # Arrange
        Config.reset()
        # Act
        mode = Config._mode
        # Assert
        assert mode == "auto"

    def test_get_mode_returns_http_when_api_url_env_set(self):
        """Test that mode is http when OPENALEX_LOCAL_API_URL is set."""
        # Arrange
        os.environ["OPENALEX_LOCAL_API_URL"] = "http://localhost:8080"
        # Act
        mode = Config.get_mode()
        # Assert
        assert mode == "http"

    def test_set_api_url_changes_mode_to_http(self):
        """Test that set_api_url switches the mode to http."""
        # Arrange
        Config.set_api_url("http://example.com:1234")
        # Act
        mode = Config.get_mode()
        # Assert
        assert mode == "http"

    def test_set_api_url_stores_the_url(self):
        """Test that set_api_url records the supplied URL."""
        # Arrange
        Config.set_api_url("http://example.com:1234")
        # Act
        url = Config.get_api_url()
        # Assert
        assert url == "http://example.com:1234"

    def test_get_api_url_default_is_localhost(self):
        """Test the default API URL points at localhost."""
        # Arrange
        Config.reset()
        # Act
        url = Config.get_api_url()
        # Assert
        assert url == "http://localhost:31292"

    def test_get_api_url_reads_from_env(self):
        """Test the API URL is read from the environment."""
        # Arrange
        os.environ["OPENALEX_LOCAL_API_URL"] = "http://custom:9999"
        Config.reset()
        # Act
        url = Config.get_api_url()
        # Assert
        assert url == "http://custom:9999"

    def test_set_dsn_stores_the_dsn(self):
        """Test set_dsn records the supplied connection string."""
        # Arrange
        chosen = "postgresql://reader@example.invalid:55432/scitex"
        # Act
        Config.set_dsn(chosen)
        stored = Config.get_dsn()
        # Assert
        assert stored == chosen

    def test_set_dsn_switches_mode_to_db(self):
        """Test set_dsn switches the mode to db."""
        # Arrange
        Config.set_dsn("postgresql://reader@example.invalid:55432/scitex")
        # Act
        mode = Config.get_mode()
        # Assert
        assert mode == "db"

    def test_set_dsn_refuses_a_filesystem_path(self):
        """A path names no database this package can open, so it is refused.

        This is the ONE behaviour worth keeping from the deleted file-path
        tests: a path used to be accepted and meant something. Accepting one
        now would select nothing and say so several layers downstream.
        """
        # Arrange
        looks_like_the_old_setting = "/data/openalex.db"
        # Act
        ctx = pytest.raises(ValueError)
        # Assert
        with ctx:
            Config.set_dsn(looks_like_the_old_setting)

    def test_set_dsn_refuses_an_empty_value(self):
        """An empty setting is a mistake, not a request for the default."""
        # Arrange
        empty = "   "
        # Act
        ctx = pytest.raises(ValueError)
        # Assert
        with ctx:
            Config.set_dsn(empty)

    def test_reset_clears_the_dsn(self):
        """Test that reset clears the stored DSN."""
        # Arrange
        Config.set_dsn("postgresql://reader@example.invalid:55432/scitex")
        # Act
        Config.reset()
        # Assert
        assert Config._dsn is None

    def test_reset_clears_api_url(self):
        """Test that reset clears the stored API URL."""
        # Arrange
        Config.set_api_url("http://test:1234")
        # Act
        Config.reset()
        # Assert
        assert Config._api_url is None

    def test_reset_restores_auto_mode(self):
        """Test that reset restores the auto mode."""
        # Arrange
        Config.set_api_url("http://test:1234")
        # Act
        Config.reset()
        # Assert
        assert Config._mode == "auto"


class TestCorpusResolution:
    """The corpus address comes from the store primitive, and only from it."""

    def setup_method(self):
        Config.reset()

    def teardown_method(self):
        Config.reset()

    def test_get_dsn_matches_the_store_primitive(self):
        """The package's DSN IS the primitive's answer, not a copy of it."""
        # Arrange
        from scitex_dev.store import host_store

        expected = host_store(pkg="openalex_local", name="corpus").dsn
        # Act
        resolved = get_dsn()
        # Assert
        assert resolved == expected

    def test_corpus_target_is_postgres(self):
        """There is one backend, and the target names it."""
        # Arrange
        from scitex_dev.store import Backend

        # Act
        target = corpus_target()
        # Assert
        assert target.backend is Backend.POSTGRES

    def test_the_store_override_moves_the_corpus(self, monkeypatch_free_env):
        """SCITEX_STORE_DSN is the knob, and it actually turns.

        The control that makes this test meaningful is in the fixture: it
        asserts the resolved DSN DIFFERS from the one resolved without the
        override. Without that, a resolver that ignored the variable entirely
        would still satisfy an equality check against whatever it returned.
        """
        # Arrange
        elsewhere = "postgresql://reader@example.invalid:55432/scitex"
        baseline = monkeypatch_free_env(None)
        # Act
        overridden = monkeypatch_free_env(elsewhere)
        # Assert
        assert overridden == elsewhere and overridden != baseline


@pytest.fixture
def monkeypatch_free_env():
    """Resolve the corpus DSN under a chosen SCITEX_STORE_DSN, then restore.

    Written by hand rather than with monkeypatch because this suite does not
    use it: the environment is real, the resolver is real, and the restore is
    explicit so a failure cannot leave the variable changed for later tests.
    """
    from scitex_dev.store import host_store
    from scitex_dev.store._host import STORE_DSN_ENV

    saved = os.environ.get(STORE_DSN_ENV)

    def resolve(value):
        if value is None:
            os.environ.pop(STORE_DSN_ENV, None)
        else:
            os.environ[STORE_DSN_ENV] = value
        return host_store(pkg="openalex_local", name="corpus").dsn

    try:
        yield resolve
    finally:
        if saved is None:
            os.environ.pop(STORE_DSN_ENV, None)
        else:
            os.environ[STORE_DSN_ENV] = saved

# EOF
