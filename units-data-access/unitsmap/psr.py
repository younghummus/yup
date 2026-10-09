"""Read PowerBuilder saved reports (.psr).

A .psr file is a DataWindow saved together with the rows it held at the time. Two layouts
exist in the wild:

* **compound file** (starts ``D0 CF 11 E0``): an OLE2 container with streams such as
  ``source``/``object`` (the DataWindow) and ``data`` (the rows).
* **PowerSoft binary** (contains ``Platform independent PSR File Format``): the compiled
  DataWindow followed by the saved rows.

Neither layout is publicly documented. What this module recovers reliably is the report
*definition*: its columns, their ``table.column`` database names, labels and the SQL that
produced it. Saved row *values* are recovered best-effort as the text strings stored in the
data part, in file order; numbers and dates are stored in binary and are not decoded.
For a faithful copy of the rows, open the .psr in a PSR viewer and use Save As > Excel/CSV
(see docs/GETTING-DATA-OUT.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import cfb
from .dwparse import DataWindow, binary_strings, looks_like_syntax, parse_compiled, parse_source

BINARY_MARKER = b"Platform independent PSR File Format"


@dataclass
class Report:
    path: str
    variant: str  # "compound" | "binary" | "unknown"
    datawindow: DataWindow | None = None
    streams: list[tuple[str, int]] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _decode_syntax(blob: bytes, encoding: str) -> str | None:
    """Find DataWindow source syntax in a blob (UTF-16 or single-byte)."""
    for enc in ("utf-16-le", encoding):
        text = blob.decode(enc, "replace")
        m = re.search(r"release\s+\d+(?:\.\d+)?\s*;", text)
        if m and looks_like_syntax(text[m.start():]):
            end = text.find("\x00", m.start())
            return text[m.start(): end if end > 0 else len(text)]
    return None


def _definition_strings(dw: DataWindow) -> set[str]:
    s = {dw.sql, dw.sql_text, dw.name}
    for c in dw.columns:
        s.update({c.name, c.dbname, c.label, c.type})
    s.update(dw.labels)
    s.update(dw.identifiers)
    s.update(f":{a}" for a, _ in dw.arguments)
    return {x for x in s if x}


def read(path: str | Path, encoding: str = "cp1252") -> Report:
    p = Path(path)
    return read_bytes(p.read_bytes(), str(p), encoding)


def read_bytes(data: bytes, path: str = "", encoding: str = "cp1252") -> Report:
    name = Path(path).stem if path else "report"
    if cfb.is_compound(data):
        return _read_compound(data, path, name, encoding)
    rep = Report(path, "binary" if BINARY_MARKER in data or b"PDW" in data[:4096] else "unknown")
    syntax = _decode_syntax(data, encoding)
    if syntax:
        rep.datawindow = parse_source(syntax, name, path)
        rep.notes.append("report definition read from embedded DataWindow source")
    else:
        rep.datawindow = parse_compiled(data, name, path, encoding)
        rep.notes.append("report definition recovered from the compiled DataWindow strings")
    known = _definition_strings(rep.datawindow)
    rep.values = [s for _, s in binary_strings(data, encoding)
                  if s not in known and BINARY_MARKER.decode() not in s and not s.startswith("PDW")]
    if rep.variant == "unknown":
        rep.notes.append("file does not carry a known PSR signature; results are a best guess")
    return rep


def _read_compound(data: bytes, path: str, name: str, encoding: str) -> Report:
    rep = Report(path, "compound")
    cf = cfb.CompoundFile(data)
    blobs = {e.path: cf.read(e) for e in cf.streams()}
    rep.streams = [(k, len(v)) for k, v in blobs.items()]
    dw = None
    for key in sorted(blobs, key=lambda k: (0 if "source" in k.lower() else 1, k)):
        syntax = _decode_syntax(blobs[key], encoding)
        if syntax:
            dw = parse_source(syntax, name, path)
            rep.notes.append(f"report definition read from stream '{key}'")
            break
    if dw is None:
        for key in sorted(blobs, key=lambda k: (0 if "object" in k.lower() else 1, k)):
            cand = parse_compiled(blobs[key], name, path, encoding)
            if cand.columns or cand.sql:
                dw = cand
                rep.notes.append(f"report definition recovered from stream '{key}'")
                break
    rep.datawindow = dw
    known = _definition_strings(dw) if dw else set()
    data_keys = [k for k in blobs if "data" in k.lower()] or [k for k in blobs if k not in ("source", "object")]
    for key in data_keys:
        rep.values += [s for _, s in binary_strings(blobs[key], encoding) if s not in known]
    if dw is None:
        rep.notes.append("no DataWindow definition found in any stream")
    return rep
