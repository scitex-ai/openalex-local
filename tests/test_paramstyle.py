#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: tests/test_paramstyle.py
"""The qmark->pyformat adapter rewrites placeholders and refuses ambiguity.

The dangerous failure here is silent: a `?` inside a string literal rewritten
to `%s` produces a statement that still RUNS and returns the wrong rows. So
these tests weight the refusals as heavily as the conversions, and every
conversion case is one that actually appears in this package's SQL.
"""

import pytest
from openalex_local._core.paramstyle import (
    AmbiguousSql,
    count_placeholders,
    qmark_to_pyformat,
)


def test_single_placeholder_is_rewritten():
    # Arrange: the shape used by get_work_by_doi
    sql = "SELECT * FROM works WHERE doi = ?"
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert rewritten == "SELECT * FROM works WHERE doi = %s"


def test_every_placeholder_is_rewritten():
    # Arrange: get_source_metrics binds the same value twice
    sql = "SELECT 1 FROM issn_lookup WHERE issn = ? AND other = ?"
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert rewritten.count("%s") == 2


def test_sql_without_placeholders_is_unchanged():
    # Arrange
    sql = "SELECT COUNT(*) AS count FROM works"
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert rewritten == sql


def test_question_mark_inside_a_literal_is_left_alone():
    """The silent-corruption case: rewriting this returns wrong rows, not an error."""
    # Arrange
    sql = "SELECT * FROM works WHERE title = 'why? because'"
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert "?" in rewritten


def test_placeholder_after_a_literal_is_still_rewritten():
    # Arrange: the scanner must resume normal handling once the literal closes
    sql = "SELECT * FROM works WHERE title = 'why?' AND doi = ?"
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert rewritten.endswith("doi = %s")


def test_doubled_quote_escape_does_not_end_the_literal():
    # Arrange: 'it''s ?' is ONE literal containing an apostrophe and a ?
    sql = "SELECT * FROM works WHERE title = 'it''s ?'"
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert "%s" not in rewritten


def test_question_mark_inside_a_quoted_identifier_is_left_alone():
    # Arrange
    sql = 'SELECT "odd?column" FROM works'
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert "%s" not in rewritten


def test_literal_percent_is_escaped():
    """Unescaped, pyformat reads % as the start of a placeholder."""
    # Arrange
    sql = "SELECT * FROM sources WHERE issns LIKE 'x%'"
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert "%%" in rewritten


def test_question_mark_in_a_line_comment_is_left_alone():
    # Arrange
    sql = "SELECT 1\n-- why? because\nFROM works WHERE doi = ?"
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert rewritten.count("%s") == 1


def test_question_mark_in_a_block_comment_is_left_alone():
    # Arrange
    sql = "SELECT 1 /* why? */ FROM works"
    # Act
    rewritten = qmark_to_pyformat(sql)
    # Assert
    assert "%s" not in rewritten


def test_unterminated_literal_is_refused():
    # Arrange
    sql = "SELECT * FROM works WHERE title = 'unterminated"

    # Act
    def _rewrite():
        qmark_to_pyformat(sql)

    # Assert
    with pytest.raises(AmbiguousSql):
        _rewrite()


def test_unterminated_block_comment_is_refused():
    # Arrange
    sql = "SELECT 1 /* never closed"

    # Act
    def _rewrite():
        qmark_to_pyformat(sql)

    # Assert
    with pytest.raises(AmbiguousSql):
        _rewrite()


def test_numbered_placeholder_is_refused():
    """?1 maps to a different params shape, not just a different spelling."""
    # Arrange
    sql = "SELECT * FROM works WHERE doi = ?1"

    # Act
    def _rewrite():
        qmark_to_pyformat(sql)

    # Assert
    with pytest.raises(AmbiguousSql):
        _rewrite()


def test_named_colon_placeholder_is_refused():
    # Arrange
    sql = "SELECT * FROM works WHERE doi = :doi AND x = ?"

    # Act
    def _rewrite():
        qmark_to_pyformat(sql)

    # Assert
    with pytest.raises(AmbiguousSql):
        _rewrite()


def test_dollar_quoted_block_is_refused():
    # Arrange
    sql = "SELECT $$why? not$$ FROM works"

    # Act
    def _rewrite():
        qmark_to_pyformat(sql)

    # Assert
    with pytest.raises(AmbiguousSql):
        _rewrite()


@pytest.fixture
def numbered_placeholder_refusal():
    """The refusal text produced for a numbered ?1 placeholder."""
    sql = "SELECT * FROM works WHERE doi = ?1"
    with pytest.raises(AmbiguousSql) as caught:
        qmark_to_pyformat(sql)
    return sql, str(caught.value)


def test_refusal_message_names_the_offending_sql(numbered_placeholder_refusal):
    # Arrange: an error that does not quote the statement is unactionable
    sql, message = numbered_placeholder_refusal
    # Act
    quoted = sql in message
    # Assert
    assert quoted


def test_refusal_message_says_what_to_do(numbered_placeholder_refusal):
    # Arrange: name the next step, not only the fault
    _, message = numbered_placeholder_refusal
    # Act
    actionable = "pyformat" in message
    # Assert
    assert actionable


def test_count_placeholders_matches_the_rewrite():
    # Arrange
    sql = "SELECT * FROM works WHERE a = ? AND b = ? AND c = 'lit?'"
    # Act
    counted = count_placeholders(sql)
    # Assert
    assert counted == 2


# EOF
