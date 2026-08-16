#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File: src/openalex_local/_core/paramstyle.py
"""Rewrite sqlite-flavoured SQL so psycopg can execute it.

Seven modules in this package write SQL with sqlite's ``qmark`` placeholders
(``WHERE doi = ?``). psycopg speaks ``pyformat`` (``WHERE doi = %s``) and raises
rather than misbinding, so every one of those call sites is a hard failure
against Postgres. Converting them all is the right end state and is a
seven-module change; this adapter lets the Postgres path be exercised
end-to-end first, against a real database, instead of after a long refactor
with nothing to measure.

It is therefore TEMPORARY BY DESIGN. Each converted call site removes work from
it, and when the last one is converted this module is deleted rather than kept
"in case".

TWO REWRITES, AND BOTH ARE NECESSARY
------------------------------------
1. ``?`` -> ``%s``  — the placeholder itself.
2. ``%`` -> ``%%``  — because pyformat gives ``%`` meaning. A literal percent in
   the SQL (``LIKE 'foo%'``) would otherwise be read as the start of a
   placeholder and raise, or worse, bind the wrong thing.

WHAT IT REFUSES, AND WHY REFUSING IS THE POINT
----------------------------------------------
A ``?`` inside a string literal is data, not a placeholder, and rewriting it
corrupts the query silently — the statement still runs and returns the wrong
rows. So the scanner tracks quoting, and where it cannot be confident it raises
:class:`AmbiguousSql` instead of guessing. A translator that mangles one query
in a hundred is worse than no translator, because the ninety-nine successes
teach you to trust it.
"""

from __future__ import annotations

__all__ = ["AmbiguousSql", "qmark_to_pyformat", "count_placeholders"]


class AmbiguousSql(ValueError):
    """The SQL could not be rewritten with confidence, so it was not rewritten."""


def _fail(reason: str, sql: str) -> "AmbiguousSql":
    return AmbiguousSql(
        f"{reason}. Refusing to rewrite rather than risk corrupting the "
        f"statement. Convert this call site to pyformat (%s) by hand instead. "
        f"SQL: {sql!r}"
    )


def qmark_to_pyformat(sql: str) -> str:
    """Return ``sql`` with qmark placeholders rewritten for psycopg.

    Handles single-quoted literals (including SQL's doubled-quote escape,
    ``'it''s'``), double-quoted identifiers, and ``--`` / ``/* */`` comments.
    Everything inside those is copied through untouched.

    Raises
    ------
    AmbiguousSql
        On an unterminated literal or comment, on a dollar-quoted block, or on
        a named/numbered placeholder mixed in — each a case where the correct
        rewrite is not determinable from a scan this simple.
    """
    if "$$" in sql:
        raise _fail("dollar-quoted block found, which this scanner cannot delimit", sql)

    out: list[str] = []
    i = 0
    n = len(sql)

    while i < n:
        ch = sql[i]

        # Spans copied through with their `?` intact -- but NOT their `%`.
        # pyformat's percent handling applies to the whole statement, literals
        # included, so `LIKE 'x%'` must still become `LIKE 'x%%'` or psycopg
        # reads that percent as the start of a placeholder. Measured by
        # test_literal_percent_is_escaped, which caught this exact omission.
        if ch == "'":
            j = _scan_single_quoted(sql, i)
            out.append(_escape_percents(sql[i:j]))
            i = j
            continue

        if ch == '"':
            j = _scan_double_quoted(sql, i)
            out.append(_escape_percents(sql[i:j]))
            i = j
            continue

        if ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(_escape_percents(sql[i:j]))
            i = j
            continue

        if ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j == -1:
                raise _fail("unterminated /* comment", sql)
            out.append(_escape_percents(sql[i : j + 2]))
            i = j + 2
            continue

        if ch == "?":
            # A bare `?` outside any literal is sqlite's placeholder. `?NNN`
            # and `?name` are sqlite's NUMBERED/named forms, which map onto a
            # different psycopg style and a different params shape -- not a
            # rewrite this function can do correctly.
            if i + 1 < n and (sql[i + 1].isdigit() or sql[i + 1].isalpha()):
                raise _fail("numbered or named ? placeholder", sql)
            out.append("%s")
            i += 1
            continue

        if ch == "%":
            # Literal percent must be escaped, or pyformat reads it as the
            # start of a placeholder.
            out.append("%%")
            i += 1
            continue

        if ch == ":" and i + 1 < n and (sql[i + 1].isalpha() or sql[i + 1] == "_"):
            raise _fail("named :placeholder found alongside qmark style", sql)

        out.append(ch)
        i += 1

    return "".join(out)


def _escape_percents(span: str) -> str:
    """Double every percent in a span copied through verbatim otherwise."""
    return span.replace("%", "%%")


def _scan_single_quoted(sql: str, start: int) -> int:
    """Return the index just past a single-quoted literal beginning at start."""
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == "'":
            # '' inside a literal is an escaped quote, not the end.
            if i + 1 < n and sql[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    raise _fail("unterminated single-quoted literal", sql)


def _scan_double_quoted(sql: str, start: int) -> int:
    """Return the index just past a double-quoted identifier beginning at start."""
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == '"':
            if i + 1 < n and sql[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    raise _fail("unterminated double-quoted identifier", sql)


def count_placeholders(sql: str) -> int:
    """Count the qmark placeholders a rewrite would produce.

    Exists so a caller can check the parameter count BEFORE handing the
    statement to a driver. A mismatch caught here names the query; the same
    mismatch caught by psycopg names only the binding.
    """
    return qmark_to_pyformat(sql).count("%s")


# EOF
