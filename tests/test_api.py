"""Tests for openalex_local API functions."""

import pytest

import openalex_local
from openalex_local import (
    Work,
    SearchResult,
    search,
    count,
    get,
    get_many,
    exists,
    info,
    get_mode,
    configure,
)
from openalex_local._core.config import Config


PUBLIC_CALLABLES = [
    "search",
    "count",
    "get",
    "get_many",
    "exists",
    "info",
    "get_mode",
    "configure",
]


class TestAPIExports:
    """Test that the public API surface is exported and callable."""

    @pytest.mark.parametrize("name", PUBLIC_CALLABLES)
    def test_public_function_listed_in_dunder_all(self, name):
        """Test each public function is advertised in __all__."""
        # Arrange
        exported = openalex_local.__all__
        # Act
        present = name in exported
        # Assert
        assert present is True

    @pytest.mark.parametrize("name", PUBLIC_CALLABLES)
    def test_public_function_is_callable(self, name):
        """Test each public function attribute is callable."""
        # Arrange
        attr = getattr(openalex_local, name)
        # Act
        is_callable = callable(attr)
        # Assert
        assert is_callable is True

    def test_work_class_is_exported(self):
        """Test the Work model class is exported."""
        # Arrange
        exported = openalex_local.__all__
        # Act
        present = "Work" in exported
        # Assert
        assert present is True

    def test_search_result_class_is_exported(self):
        """Test the SearchResult model class is exported."""
        # Arrange
        exported = openalex_local.__all__
        # Act
        present = "SearchResult" in exported
        # Assert
        assert present is True


class TestGetMode:
    """Test get_mode function."""

    def test_get_mode_returns_known_mode(self, reset_config):
        """Test get_mode returns one of the supported mode strings."""
        # Arrange
        Config.reset()
        # Act
        mode = get_mode()
        # Assert
        assert mode in ("db", "http")

    def test_get_mode_is_db_when_the_mode_is_forced(self, reset_config):
        """Test get_mode honours an explicit db mode.

        This replaces a test that created an empty temporary FILE and asserted
        the package found it. There is no file to find now, and the auto-detect
        branch reaches the network — so what is pinned here is the part that is
        decidable without one: an explicit choice wins.
        """
        # Arrange
        import os

        old_url = os.environ.pop("OPENALEX_LOCAL_API_URL", None)
        old_mode = os.environ.get("OPENALEX_LOCAL_MODE")
        os.environ["OPENALEX_LOCAL_MODE"] = "db"
        Config.reset()
        # Act
        try:
            mode = get_mode()
        finally:
            if old_url:
                os.environ["OPENALEX_LOCAL_API_URL"] = old_url
            if old_mode is None:
                os.environ.pop("OPENALEX_LOCAL_MODE", None)
            else:
                os.environ["OPENALEX_LOCAL_MODE"] = old_mode
        # Assert
        assert mode == "db"


class TestSearchResult:
    """Test SearchResult container."""

    def test_search_result_len_counts_works(self):
        """Test SearchResult length reflects its number of works."""
        # Arrange
        works = [Work(openalex_id=f"W{i}") for i in range(5)]
        result = SearchResult(works=works, total=100, query="test", elapsed_ms=10.0)
        # Act
        length = len(result)
        # Assert
        assert length == 5

    def test_search_result_iterates_over_works(self):
        """Test SearchResult iteration yields its works."""
        # Arrange
        works = [Work(openalex_id=f"W{i}") for i in range(3)]
        result = SearchResult(works=works, total=3, query="test", elapsed_ms=5.0)
        # Act
        listed = list(result)
        # Assert
        assert [w.openalex_id for w in listed] == ["W0", "W1", "W2"]

    def test_search_result_getitem_returns_work(self):
        """Test SearchResult indexing returns the work at that position."""
        # Arrange
        works = [Work(openalex_id=f"W{i}") for i in range(3)]
        result = SearchResult(works=works, total=3, query="test", elapsed_ms=5.0)
        # Act
        first = result[0]
        # Assert
        assert first.openalex_id == "W0"

    def test_search_result_exposes_total(self):
        """Test SearchResult records the total match count."""
        # Arrange
        works = [Work(openalex_id="W1")]
        result = SearchResult(
            works=works, total=50, query="machine learning", elapsed_ms=15.5
        )
        # Act
        total = result.total
        # Assert
        assert total == 50

    def test_search_result_exposes_query(self):
        """Test SearchResult records the originating query."""
        # Arrange
        works = [Work(openalex_id="W1")]
        result = SearchResult(
            works=works, total=50, query="machine learning", elapsed_ms=15.5
        )
        # Act
        query = result.query
        # Assert
        assert query == "machine learning"

    def test_search_result_exposes_elapsed_ms(self):
        """Test SearchResult records the elapsed query time."""
        # Arrange
        works = [Work(openalex_id="W1")]
        result = SearchResult(
            works=works, total=50, query="machine learning", elapsed_ms=15.5
        )
        # Act
        elapsed = result.elapsed_ms
        # Assert
        assert elapsed == 15.5


class TestAPIWithDatabase:
    """Integration tests that require database access."""

    @pytest.fixture(autouse=True)
    def check_db(self, db_available):
        """Skip tests if database is not available."""
        if not db_available:
            pytest.skip("Database not available")

    def test_search_returns_search_result(self, reset_config):
        """Test search returns a SearchResult instance."""
        # Arrange
        Config.reset()
        # Act
        result = search("machine learning", limit=5)
        # Assert
        assert isinstance(result, SearchResult)

    def test_search_respects_limit(self, reset_config):
        """Test search returns no more works than the limit."""
        # Arrange
        Config.reset()
        # Act
        result = search("science", limit=3)
        # Assert
        assert len(result.works) <= 3

    def test_count_returns_non_negative_int(self, reset_config):
        """Test count returns a non-negative integer."""
        # Arrange
        Config.reset()
        # Act
        result = count("machine learning")
        # Assert
        assert isinstance(result, int) and result >= 0

    def test_get_nonexistent_id_returns_none(self, reset_config):
        """Test get returns None for an unknown OpenAlex ID."""
        # Arrange
        Config.reset()
        # Act
        work = get("W99999999999999")
        # Assert
        assert work is None

    def test_get_many_returns_list(self, reset_config, sample_openalex_id):
        """Test get_many returns a list of works."""
        # Arrange
        Config.reset()
        # Act
        works = get_many([sample_openalex_id, "W99999999999999"])
        # Assert
        assert isinstance(works, list)

    def test_exists_returns_bool(self, reset_config, sample_openalex_id):
        """Test exists returns a boolean for a known id."""
        # Arrange
        Config.reset()
        # Act
        result = exists(sample_openalex_id)
        # Assert
        assert isinstance(result, bool)

    def test_exists_false_for_nonexistent_id(self, reset_config):
        """Test exists returns False for an unknown id."""
        # Arrange
        Config.reset()
        # Act
        result = exists("W99999999999999")
        # Assert
        assert result is False

    def test_info_reports_db_mode(self, reset_config):
        """Test info reports db mode when a database is active."""
        # Arrange
        Config.reset()
        # Act
        result = info()
        # Assert
        assert result["mode"] == "db"
