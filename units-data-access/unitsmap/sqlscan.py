"""Pull tables, column references and join conditions out of SQL text.

This is a deliberately forgiving scanner, not a full SQL parser: DataWindow SQL comes in
many dialects (SQL Server, Sybase ASE/ASA, Oracle) and old-style joins (``*=``, ``(+)``).
It is good at the questions the catalog needs answered:

* which tables does this query read?
* which ``table.column`` pairs does it touch?
* which columns does it join on (``vehicle.stock_no = deal.stock_no``)?
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_IDENT = r'(?:\[[^\]]+\]|"[^"]+"|[A-Za-z_#@$][\w#@$]*)'
_QNAME = rf"{_IDENT}(?:\s*\.\s*{_IDENT}){{0,3}}"

_KEYWORDS = {
    "select", "from", "where", "join", "inner", "left", "right", "full", "outer", "cross", "on",
    "and", "or", "not", "group", "order", "by", "having", "union", "all", "as", "with", "nolock",
    "holdlock", "readuncommitted", "index", "set", "values", "into", "exists", "in", "is", "null",
    "case", "when", "then", "else", "end", "distinct", "top", "apply", "lateral", "using", "natural",
    "straight_join", "for", "browse", "at", "isolation", "read", "only", "update", "delete", "insert",
}

_FROM_START = re.compile(r"\b(from|join|update|into)\b", re.I)
_CLAUSE_END = re.compile(
    r"\b(where|group\s+by|order\s+by|having|union|on|using|for\s+(?:update|browse|read)|"
    r"(?:inner|left|right|full|cross|natural)?\s*(?:outer\s+)?join|at\s+isolation|option|set|values)\b",
    re.I,
)
_EQ_JOIN = re.compile(rf"({_QNAME})\s*(\*=|=\*|=)\s*({_QNAME})(\s*\(\+\))?")
_COLREF = re.compile(rf"(?<![\w.:@])({_IDENT}\s*\.\s*{_IDENT}(?:\s*\.\s*{_IDENT})?)(?![\w(])")


@dataclass
class Scan:
    tables: list[str] = field(default_factory=list)          # real table names, schema stripped
    aliases: dict[str, str] = field(default_factory=dict)    # alias(lower) -> table
    columns: list[str] = field(default_factory=list)         # table.column (aliases resolved)
    joins: list[tuple[str, str]] = field(default_factory=list)  # (table.col, table.col)
    arguments: list[str] = field(default_factory=list)       # :name placeholders
    procedure: str = ""


def _unquote(name: str) -> str:
    return re.sub(r'[\[\]"]', "", re.sub(r"\s*\.\s*", ".", name.strip()))


def strip_literals(sql: str) -> str:
    """Blank out comments and string literals so they cannot fool the scanner."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def bare(table: str) -> str:
    """``dbo.vehicle`` -> ``vehicle``; ``units..deal`` -> ``deal``."""
    return _unquote(table).split(".")[-1]


def _from_items(clause: str) -> list[tuple[str, str]]:
    items = []
    for part in re.split(r",", clause):
        part = re.sub(r"\(.*?\)", " ", part)  # WITH (NOLOCK), index hints
        words = [w for w in re.findall(_QNAME, part)]
        if not words:
            continue
        table = words[0]
        if table.lower() in _KEYWORDS:
            continue
        alias = ""
        for w in words[1:]:
            if w.lower() == "as":
                continue
            if w.lower() not in _KEYWORDS:
                alias = w
            break
        items.append((_unquote(table), _unquote(alias)))
    return items


def scan(sql: str) -> Scan:
    out = Scan()
    if not sql:
        return out
    text = strip_literals(sql)
    out.arguments = sorted(set(re.findall(r"(?<![\w:]):([A-Za-z_][\w]*)", text)), key=str.lower)

    proc = re.match(r"\s*(?:\d+\s+)?(?:exec(?:ute)?|call)\s+(" + _QNAME + ")", text, re.I)
    if proc:
        out.procedure = _unquote(proc.group(1))

    # Tables: every FROM/JOIN/UPDATE/INTO clause up to the next clause keyword.
    for m in _FROM_START.finditer(text):
        rest = text[m.end():]
        end = _CLAUSE_END.search(rest)
        clause = rest[: end.start()] if end else rest
        if m.group(1).lower() != "from":
            clause = clause.split(",")[0]
        # Subquery in FROM: skip; its own FROM is found by the outer loop.
        if clause.strip().startswith("("):
            continue
        for table, alias in _from_items(clause):
            t = bare(table)
            if t.lower() in _KEYWORDS or not t:
                continue
            if t not in out.tables:
                out.tables.append(t)
            out.aliases[t.lower()] = t
            if alias:
                out.aliases[alias.lower()] = t

    def resolve(ref: str) -> str | None:
        parts = _unquote(ref).split(".")
        if len(parts) < 2:
            return None
        owner, col = parts[-2], parts[-1]
        table = out.aliases.get(owner.lower())
        if table is None:
            if len(out.tables) and owner.lower() not in {t.lower() for t in out.tables}:
                return None
            table = owner
        return f"{table}.{col}"

    for m in _COLREF.finditer(text):
        r = resolve(m.group(1))
        if r and r not in out.columns:
            out.columns.append(r)
    for m in _EQ_JOIN.finditer(text):
        a, b = resolve(m.group(1)), resolve(m.group(3))
        if a and b and a.split(".")[0].lower() != b.split(".")[0].lower():
            pair = (a, b)
            if pair not in out.joins and (b, a) not in out.joins:
                out.joins.append(pair)
    return out
