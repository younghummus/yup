"""Understand DataWindows: the objects behind every Units screen, list and report.

A DataWindow bundles three things: the SQL that fetches the data, the list of result
columns (each mapped to a ``table.column`` in the database), and the layout that decides
which of those columns you actually see. Columns the SQL fetches but the layout hides are
exactly the "extra fields" that never show up on screen.

DataWindows reach us in two forms:

* **source** (``.srd`` entries in a .pbl, or text exported from PowerBuilder): readable
  DataWindow syntax, parsed here completely.
* **compiled** (``.dwo`` entries in a .pbd/.exe/.dll, and inside .psr files): a binary
  object. Its strings still carry the column names, the ``table.column`` database names
  and the retrieve SQL, which we recover. Very recent PowerBuilder releases can encrypt the
  SQL; columns and labels are still recovered and the DataWindow is flagged.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import pbselect, sqlscan

# ----------------------------------------------------------------------------- model


@dataclass
class Column:
    name: str
    dbname: str = ""
    type: str = ""
    key: bool = False
    updatable: bool = False
    label: str = ""
    shown: bool | None = None  # True visible, False hidden, None unknown (compiled)
    dddw: str = ""
    dddw_display: str = ""
    dddw_data: str = ""
    codes: str = ""

    @property
    def table(self) -> str:
        return self.dbname.rsplit(".", 1)[0] if "." in self.dbname else ""


@dataclass
class DataWindow:
    name: str
    library: str = ""
    form: str = "source"  # "source" | "compiled"
    comment: str = ""
    release: str = ""
    sql: str = ""  # as stored (PBSELECT, SQL, or a procedure call)
    sql_text: str = ""  # plain SQL, ready to paste
    sql_encrypted: bool = False
    update_table: str = ""
    arguments: list[tuple[str, str]] = field(default_factory=list)
    columns: list[Column] = field(default_factory=list)
    computes: list[tuple[str, str]] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    joins: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def hidden_columns(self) -> list[Column]:
        return [c for c in self.columns if c.shown is False]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["arguments"] = [list(a) for a in self.arguments]
        d["computes"] = [list(c) for c in self.computes]
        d["joins"] = [list(j) for j in self.joins]
        return d


# ----------------------------------------------------------------------------- source syntax


def _skip_quoted(text: str, i: int) -> int:
    """``text[i]`` is a quote; return the index just past its closing quote (``~`` escapes)."""
    q = text[i]
    i += 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "~":
            i += 2
            continue
        if c == q:
            return i + 1
        i += 1
    return n


def _match_paren(text: str, i: int) -> int:
    """``text[i]`` is ``(``; return the index of the matching ``)`` (quotes respected)."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            i = _skip_quoted(text, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def top_level(text: str) -> list[tuple[str, str]]:
    """Split DataWindow syntax into ``(keyword, body)`` items: ``table(...)``, ``column(...)``..."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(text)
    word = re.compile(r"\s*([A-Za-z_][\w.]*)\s*\(")
    while i < n:
        m = word.match(text, i)
        if not m:
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        start = m.end() - 1
        end = _match_paren(text, start)
        out.append((m.group(1).lower(), text[start + 1 : end]))
        i = end + 1
    return out


_KEY = re.compile(r"\s*([A-Za-z_][\w.]*)\s*=\s*")


def attrs(body: str) -> list[tuple[str, str]]:
    """Parse ``key=value`` pairs. Quoted values are un-escaped; ``(...)`` values come back raw."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(body)
    while i < n:
        m = _KEY.match(body, i)
        if not m:
            # skip one token
            while i < n and body[i].isspace():
                i += 1
            if i < n and body[i] in "\"'":
                i = _skip_quoted(body, i)
            elif i < n and body[i] == "(":
                i = _match_paren(body, i) + 1
            else:
                while i < n and not body[i].isspace() and body[i] not in "()":
                    i += 1
                if i < n and body[i] in "()":
                    i += 1
            continue
        key = m.group(1).lower()
        i = m.end()
        if i >= n:
            out.append((key, ""))
            break
        c = body[i]
        if c in "\"'":
            j = _skip_quoted(body, i)
            out.append((key, pbselect.unescape(body[i + 1 : j - 1])))
            i = j
        elif c == "(":
            j = _match_paren(body, i)
            out.append((key, body[i + 1 : j]))
            i = j + 1
        else:
            j = i
            while j < n and not body[j].isspace() and body[j] not in "()":
                j += 1
            if j < n and body[j] == "(":  # char(10), decimal(2)
                j = _match_paren(body, j) + 1
            out.append((key, body[i:j]))
            i = j
    return out


def _flag(v: str) -> bool:
    return v.strip().strip('"').lower() in ("yes", "y", "1", "true")


def _visible(v: str | None) -> bool:
    if v is None:
        return True
    return not v.strip().strip('"').startswith("0") or "\t" in v


def parse_source(text: str, name: str = "", library: str = "") -> DataWindow:
    dw = DataWindow(name=name, library=library, form="source")
    m = re.search(r"release\s+([\d.]+)\s*;", text, re.I)
    dw.release = m.group(1) if m else ""
    columns: dict[str, Column] = {}
    texts: dict[str, str] = {}
    display: dict[str, dict[str, str]] = {}
    for kw, body in top_level(text):
        if kw == "table":
            for key, val in attrs(body):
                if key == "column":
                    a = dict(attrs(val))
                    c = Column(
                        name=a.get("name", ""),
                        dbname=a.get("dbname", ""),
                        type=a.get("type", ""),
                        key=_flag(a.get("key", "")),
                        updatable=_flag(a.get("update", "")),
                        codes=a.get("values", ""),
                    )
                    if c.name:
                        columns[c.name.lower()] = c
                elif key == "retrieve":
                    dw.sql = val
                elif key == "procedure":
                    dw.sql = dw.sql or val
                elif key == "update":
                    dw.update_table = val
                elif key == "arguments":
                    for an, at in re.findall(r'\(\s*"([^"]*)"\s*,\s*([\w]+)\s*\)', val):
                        dw.arguments.append((an, at))
        elif kw == "text":
            a = dict(attrs(body))
            if a.get("text"):
                label = a["text"].split("\t")[0].strip()
                if a.get("name"):
                    texts[a["name"].lower()] = label
                if label and label not in dw.labels:
                    dw.labels.append(label)
        elif kw == "column":
            a = dict(attrs(body))
            if a.get("name"):
                display[a["name"].lower()] = a
        elif kw == "compute":
            a = dict(attrs(body))
            dw.computes.append((a.get("name", ""), a.get("expression", "")))
        elif kw in ("report", "nested"):
            a = dict(attrs(body))
            if a.get("dataobject") and a["dataobject"] not in dw.references:
                dw.references.append(a["dataobject"])

    for key, c in columns.items():
        disp = display.get(key)
        c.label = texts.get(key + "_t", "")
        if disp is None:
            # Graph/crosstab DataWindows show data without column objects: unknown, not hidden.
            c.shown = False if display else None
        else:
            c.shown = _visible(disp.get("visible"))
            c.dddw = disp.get("dddw.name", "")
            c.dddw_display = disp.get("dddw.displaycolumn", "")
            c.dddw_data = disp.get("dddw.datacolumn", "")
            codes = disp.get("edit.codetable") and disp.get("values") or ""
            c.codes = c.codes or codes
            if c.dddw and c.dddw not in dw.references:
                dw.references.append(c.dddw)
    dw.columns = list(columns.values())
    _finish(dw)
    return dw


# ----------------------------------------------------------------------------- compiled objects

_ANSI_RUN = re.compile(rb"[\x01\x09\x0a\x0d\x20-\x7e\x80-\xff]{2,}(?=\x00)")
_WIDE_RUN = re.compile(rb"(?:[\x01\x09\x0a\x0d\x20-\x7e]\x00|[\x80-\xff][\x00-\x24])(?:[\x01\x09\x0a\x0d\x20-\x7e]\x00|[\x80-\xff][\x00-\x24]){1,}")

_DBNAME = re.compile(r"^[A-Za-z_#@$][\w#@$]*(?:\.[A-Za-z_#@$][\w#@$]*){1,2}$")
_IDENT = re.compile(r"^[A-Za-z_][\w#@$]*$")
_SQL_START = re.compile(r"^\s*(?:\(\s*)?(?:pbselect\s*\(|select\b|with\b|exec\b|execute\b|call\b|\d+\s+exec)", re.I)
_ENCRYPTED = re.compile(r"^[a-z]{3,8};[A-Za-z0-9+/=]{6,};[A-Za-z0-9+/=]{16,}")
_FONTS = {
    "arial", "tahoma", "verdana", "segoe ui", "ms sans serif", "microsoft sans serif", "times new roman",
    "courier new", "courier", "system", "calibri", "ms serif", "small fonts", "arial narrow", "consolas",
}


def _printable_ratio(s: str) -> float:
    if not s:
        return 0.0
    good = sum(1 for ch in s if ch.isalnum() or ch in " _.,:;()'\"=<>!*/+-%#@$&?[]{}|\t\r\n\x01~^")
    return good / len(s)


def binary_strings(blob: bytes, encoding: str = "cp1252", min_len: int = 2) -> list[tuple[int, str]]:
    """Recover the text strings stored inside a compiled object, in file order.

    Both single-byte (PB 9 and earlier) and UTF-16 (PB 10+) strings are collected.
    """
    found: list[tuple[int, int, str]] = []
    for m in _ANSI_RUN.finditer(blob):
        s = m.group().decode(encoding, "replace")
        if len(s) >= min_len and _printable_ratio(s) >= 0.85:
            found.append((m.start(), m.end(), s))
    for m in _WIDE_RUN.finditer(blob):
        raw = m.group()
        if len(raw) % 2:
            raw = raw[:-1]
        s = raw.decode("utf-16-le", "replace")
        if len(s) >= min_len and _printable_ratio(s) >= 0.85:
            found.append((m.start(), m.start() + len(raw), s))
    found.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    out: list[tuple[int, str]] = []
    last_end = -1
    for start, end, s in found:
        if start < last_end:  # overlap: keep the earlier/longer one
            continue
        out.append((start, s))
        last_end = end
    return out


def _label_like(s: str) -> bool:
    t = s.strip()
    if len(t) < 2 or len(t) > 80 or _is_font(t):
        return False
    if _IDENT.match(t) or _DBNAME.match(t) or _SQL_START.match(t):
        return False
    if re.fullmatch(r"[-\d.,\s]+", t) or t.startswith("[") or "~" in t or "\x01" in t:
        return False
    if re.search(r"[#0]{2,}|dd/|mm/|yy|hh:", t):  # display formats
        return False
    if re.search(r"\w\(.*\)", t) and not re.search(r"\s", t.split("(")[0]):  # expressions: if(...)
        return False
    return bool(re.search(r"[^\W\d_]{2,}", t))


def _meaningful(s: str) -> bool:
    """Drop binary noise that happens to look like text."""
    if "\x01" in s and not _SQL_START.match(s):
        return False
    core = s.strip()
    if not core:
        return False
    if len(core) <= 4 and not re.search(r"[A-Za-z0-9]", core):
        return False
    return True


_FONT_WORDS = re.compile(
    r"^(?:arial|tahoma|verdana|segoe|ms |microsoft|times|courier|calibri|cambria|helvetica|consolas|lucida|"
    r"georgia|trebuchet|wingdings|symbol|garamond|century|franklin|book antiqua|palatino|small fonts|system|"
    r"modern|roman|script|fixedsys|terminal|marlett|webdings|impact|comic sans|candara|corbel|constantia)\b",
    re.I,
)


def _is_font(t: str) -> bool:
    return t.lower() in _FONTS or bool(_FONT_WORDS.match(t))


def _heading_like(t: str) -> bool:
    if len(t) < 2 or _is_font(t) or t.startswith("[") or re.fullmatch(r"[-\d.,\s<>]+", t):
        return False
    if re.search(r"[#0]{2,}|dd/|mm/|yy|hh:", t):
        return False
    return bool(re.search(r"[^\W\d_]", t))


def parse_compiled(blob: bytes, name: str = "", library: str = "", encoding: str = "cp1252") -> DataWindow:
    dw = DataWindow(name=name, library=library, form="compiled")
    head = blob[:8].rstrip(b"\x00").decode("ascii", "replace")
    if head.startswith("PDW"):
        dw.release = head[3:]
    strings = [s for _, s in binary_strings(blob, encoding) if _meaningful(s)]

    # Retrieve SQL: the longest SQL-looking string.
    sql_candidates = [s for s in strings if _SQL_START.match(s)]
    encrypted = [s for s in strings if _ENCRYPTED.match(s)]
    if sql_candidates:
        dw.sql = max(sql_candidates, key=len).strip()
    elif encrypted:
        dw.sql_encrypted = True
        dw.warnings.append("retrieve SQL is encrypted in this compiled DataWindow; columns are still listed")

    # Arguments appear as ":name" strings; compiled SQL holds \x01 where each one goes.
    args = []
    for s in strings:
        if re.fullmatch(r":[A-Za-z_][\w]*", s) and s[1:] not in args:
            args.append(s[1:])
    if dw.sql and "\x01" in dw.sql:
        holes = dw.sql.count("\x01")
        it = iter(args) if holes == len(args) else None
        dw.sql = re.sub("\x01", lambda _m: ":" + next(it) if it else ":?", dw.sql)
        if it is None:
            dw.warnings.append("argument positions in the SQL could not be matched to names")
    dw.arguments = [(a, "") for a in args]

    # Columns: an identifier followed by its "table.column" database name.
    seen: dict[str, Column] = {}
    first_pair = len(strings)
    for i, (prev, cur) in enumerate(zip(strings, strings[1:])):
        if _DBNAME.match(cur) and _IDENT.match(prev):
            first_pair = min(first_pair, i)
            if prev.lower() not in seen:
                seen[prev.lower()] = Column(name=prev, dbname=cur)
    dw.columns = list(seen.values())

    # Layout objects come before the table definition. A column whose name appears there has
    # an on-screen field; "<column>_t" is its heading, whose text follows a few strings later.
    layout = strings[:first_pair]
    names_in_layout = {s.lower() for s in layout}
    if dw.columns and any(c.name.lower() in names_in_layout for c in dw.columns):
        for c in dw.columns:
            c.shown = c.name.lower() in names_in_layout
    for i, s in enumerate(layout):
        if not s.lower().endswith("_t"):
            continue
        col = seen.get(s[:-2].lower())
        if col is None or col.label:
            continue
        for nxt in layout[i + 1 : i + 30]:
            t = nxt.split("\t")[0].strip()
            if t.lower().endswith("_t") and _IDENT.match(t):
                break
            if _heading_like(t):
                col.label = t
                break

    labels = []
    for s in strings:
        t = s.split("\t")[0].strip()
        if _label_like(t) and t not in labels:
            labels.append(t)
    dw.labels = labels
    dw.identifiers = sorted({s for s in strings if _IDENT.match(s)}, key=str.lower)
    _finish(dw)
    return dw


# ----------------------------------------------------------------------------- shared


def _finish(dw: DataWindow) -> None:
    """Fill in plain SQL, tables, joins and argument names from whatever SQL we have."""
    sql = dw.sql.strip()
    sc = None
    if sql and pbselect.is_pbselect(sql):
        try:
            sel = pbselect.to_select(pbselect.parse(sql))
            dw.sql_text = pbselect.render(sel)
            for name, _alias in sel.tables:
                t = sqlscan.bare(name)
                if t and t not in dw.tables:
                    dw.tables.append(t)
            if not dw.arguments:
                dw.arguments = [(n, t) for n, t in sel.arguments]
            alias = {(a or n).lower(): sqlscan.bare(n) for n, a in sel.tables}

            def res(x: str) -> str:
                parts = x.split(".")
                if len(parts) >= 2:
                    return f"{alias.get(parts[-2].lower(), parts[-2])}.{parts[-1]}"
                return x

            for j in sel.joins:
                pair = (res(j.left), res(j.right))
                if pair not in dw.joins:
                    dw.joins.append(pair)
        except pbselect.PBSelectError as exc:
            dw.warnings.append(f"could not convert PBSELECT: {exc}")
            dw.sql_text = sql
    elif sql:
        dw.sql_text = sql
    if dw.sql_text:
        sc = sqlscan.scan(dw.sql_text)
        for t in sc.tables:
            if t not in dw.tables:
                dw.tables.append(t)
        for j in sc.joins:
            if j not in dw.joins and (j[1], j[0]) not in dw.joins:
                dw.joins.append(j)
        if not dw.arguments and sc.arguments:
            dw.arguments = [(a, "") for a in sc.arguments]
    # Tables named only in column dbnames (e.g. encrypted SQL) still count.
    for c in dw.columns:
        t = c.table
        if t:
            t = sqlscan.bare(t)
            if t not in dw.tables:
                dw.tables.append(t)
    if dw.update_table:
        t = sqlscan.bare(dw.update_table)
        if t not in dw.tables:
            dw.tables.append(t)


def looks_like_syntax(text: str) -> bool:
    return bool(re.search(r"(?:^|\n)\s*release\s+\d+(?:\.\d+)?\s*;", text)) and "datawindow(" in text.lower()
