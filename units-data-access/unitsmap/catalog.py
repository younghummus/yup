"""The catalog: every DataWindow found, the tables and columns behind them, and how tables join.

``build()`` walks folders for PowerBuilder libraries (.pbd .pbl .exe .dll), exported
DataWindow source (.srd), and saved reports (.psr), and turns them into a ``Catalog``
that can be searched, saved as JSON, and exported to Excel/CSV/HTML.

The join graph is learned from the application's own SQL: every ``a.x = b.y`` that Units
itself uses becomes an edge, so ``path()`` can answer "how do I get from the vehicle table
to the salesperson?" with joins the vendor already relies on.
"""

from __future__ import annotations

import heapq
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .dwparse import Column, DataWindow, looks_like_syntax, parse_compiled, parse_source
from .pblib import Library, LibraryError, is_library

LIBRARY_SUFFIXES = {".pbd", ".pbl", ".exe", ".dll"}
SOURCE_SUFFIXES = {".srd"}
REPORT_SUFFIXES = {".psr"}
MAX_FILE = 512 * 1024 * 1024


@dataclass
class Hit:
    dw: DataWindow
    score: int
    reasons: list[str] = field(default_factory=list)


@dataclass
class Edge:
    a: str
    b: str
    pairs: list[tuple[str, str]]  # (a.col, b.col) as used together most often
    count: int  # how many DataWindows join these two tables
    examples: list[str] = field(default_factory=list)


@dataclass
class Catalog:
    datawindows: list[DataWindow] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ indexes
    def get(self, name: str) -> DataWindow | None:
        name = name.lower()
        for dw in self.datawindows:
            if dw.name.lower() == name:
                return dw
        return None

    def tables(self) -> dict[str, dict]:
        """table -> {"columns": {col: [labels]}, "datawindows": [names]} (case-folded keys)."""
        out: dict[str, dict] = {}

        def slot(t: str) -> dict:
            key = t.lower()
            if key not in out:
                out[key] = {"name": t, "columns": {}, "datawindows": []}
            return out[key]

        for dw in self.datawindows:
            for t in dw.tables:
                s = slot(t)
                if dw.name not in s["datawindows"]:
                    s["datawindows"].append(dw.name)
            for c in dw.columns:
                if "." not in c.dbname:
                    continue
                t, col = c.dbname.rsplit(".", 1)
                t = t.split(".")[-1]
                s = slot(t)
                labels = s["columns"].setdefault(col, [])
                if c.label and c.label not in labels:
                    labels.append(c.label)
                if dw.name not in s["datawindows"]:
                    s["datawindows"].append(dw.name)
            for a, b in dw.joins:
                for ref in (a, b):
                    if "." in ref:
                        t, col = ref.rsplit(".", 1)
                        slot(t.split(".")[-1])["columns"].setdefault(col, [])
        return dict(sorted(out.items()))

    def edges(self) -> dict[tuple[str, str], Edge]:
        """Join graph learned from the app's SQL, keyed by sorted lower-case table pair."""
        per_pair: dict[tuple[str, str], Counter] = defaultdict(Counter)
        names: dict[str, str] = {}
        examples: dict[tuple[str, str], list[str]] = defaultdict(list)
        for dw in self.datawindows:
            grouped: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
            for left, right in dw.joins:
                if "." not in left or "." not in right:
                    continue
                lt, lc = left.rsplit(".", 1)
                rt, rc = right.rsplit(".", 1)
                lt, rt = lt.split(".")[-1], rt.split(".")[-1]
                if lt.lower() == rt.lower():
                    continue
                names.setdefault(lt.lower(), lt)
                names.setdefault(rt.lower(), rt)
                if lt.lower() <= rt.lower():
                    key, pair = (lt.lower(), rt.lower()), (lc, rc)
                else:
                    key, pair = (rt.lower(), lt.lower()), (rc, lc)
                grouped[key].add(pair)
            for key, pairs in grouped.items():
                per_pair[key][tuple(sorted(pairs, key=lambda p: (p[0].lower(), p[1].lower())))] += 1
                if len(examples[key]) < 5:
                    examples[key].append(dw.name)
        out: dict[tuple[str, str], Edge] = {}
        for key, counter in per_pair.items():
            best, _n = max(counter.items(), key=lambda kv: (kv[1], len(kv[0])))
            a, b = names[key[0]], names[key[1]]
            out[key] = Edge(a, b, [(f"{a}.{x}", f"{b}.{y}") for x, y in best], sum(counter.values()), examples[key])
        return out

    # ------------------------------------------------------------------ search
    def search(self, query: str | list[str], limit: int | None = None) -> list[Hit]:
        terms = [t.lower() for t in (query.split() if isinstance(query, str) else query) if t.strip()]
        hits: list[Hit] = []
        for dw in self.datawindows:
            total = 0
            reasons: list[str] = []
            ok = True
            for term in terms:
                score, why = _match(dw, term)
                if not score:
                    ok = False
                    break
                total += score
                reasons += [w for w in why if w not in reasons]
            if ok and terms:
                hits.append(Hit(dw, total, reasons))
        hits.sort(key=lambda h: (-h.score, h.dw.name.lower()))
        return hits[:limit] if limit else hits

    def find_columns(self, term: str) -> list[tuple[DataWindow, Column]]:
        t = term.lower()
        out = []
        for dw in self.datawindows:
            for c in dw.columns:
                if t in c.name.lower() or t in c.dbname.lower() or t in c.label.lower():
                    out.append((dw, c))
        return out

    # ------------------------------------------------------------------ joins
    def path(self, start: str, goal: str) -> list[Edge] | None:
        """Cheapest chain of observed joins from table ``start`` to table ``goal``.

        Fewer hops win; among equal hop counts, joins the app uses more often win.
        """
        edges = self.edges()
        adj: dict[str, list[tuple[str, Edge]]] = defaultdict(list)
        for (a, b), e in edges.items():
            adj[a].append((b, e))
            adj[b].append((a, e))
        s, g = start.lower(), goal.lower()
        if s == g:
            return []
        dist = {s: 0.0}
        prev: dict[str, tuple[str, Edge]] = {}
        heap = [(0.0, s)]
        while heap:
            d, node = heapq.heappop(heap)
            if node == g:
                break
            if d > dist.get(node, math.inf):
                continue
            for nxt, e in adj[node]:
                nd = d + 1.0 + 1.0 / (1.0 + e.count)
                if nd < dist.get(nxt, math.inf):
                    dist[nxt] = nd
                    prev[nxt] = (node, e)
                    heapq.heappush(heap, (nd, nxt))
        if g not in prev:
            return None
        chain: list[Edge] = []
        node = g
        while node != s:
            node, e = prev[node]
            chain.append(e)
        return list(reversed(chain))

    def join_sql(self, tables: list[str], columns: list[str] | None = None) -> str:
        """SELECT joining all ``tables`` through observed joins (first table is the anchor)."""
        if not tables:
            raise ValueError("name at least one table")
        tinfo = self.tables()
        proper = {k: v["name"] for k, v in tinfo.items()}
        anchor = proper.get(tables[0].lower(), tables[0])
        placed = [anchor.lower()]
        lines = [f"FROM {anchor}"]
        missing: list[str] = []
        for t in tables[1:]:
            if t.lower() in placed:
                continue
            best: list[Edge] | None = None
            for p in placed:
                chain = self.path(p, t)
                if chain is not None and (best is None or len(chain) < len(best)):
                    best = chain
            if best is None:
                missing.append(t)
                continue
            for e in best:
                a_in, b_in = e.a.lower() in placed, e.b.lower() in placed
                if a_in and b_in:
                    continue
                new = e.b if a_in else e.a
                cond = " AND ".join(f"{x} = {y}" for x, y in e.pairs)
                lines.append(f"JOIN {new} ON {cond}")
                placed.append(new.lower())
        if columns:
            cols = columns
        else:
            cols = [f"{proper.get(p, p)}.*" for p in placed]
        sql = "SELECT " + ",\n       ".join(cols) + "\n" + "\n".join(lines)
        if missing:
            sql += "\n-- No join seen in Units' own SQL for: " + ", ".join(missing)
            sql += "\n-- Look for a shared key column (e.g. stock number, VIN, customer number) in the Tables sheet."
        return sql

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {
            "tool": "unitsmap",
            "version": __version__,
            "sources": self.sources,
            "errors": self.errors,
            "datawindows": [dw.to_dict() for dw in self.datawindows],
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        cat = cls(sources=d.get("sources", []), errors=d.get("errors", []))
        for raw in d.get("datawindows", []):
            cols = [Column(**c) for c in raw.pop("columns", [])]
            raw["arguments"] = [tuple(a) for a in raw.get("arguments", [])]
            raw["computes"] = [tuple(c) for c in raw.get("computes", [])]
            raw["joins"] = [tuple(j) for j in raw.get("joins", [])]
            cat.datawindows.append(DataWindow(columns=cols, **raw))
        return cat


def _match(dw: DataWindow, term: str) -> tuple[int, list[str]]:
    score, why = 0, []
    if term in dw.name.lower():
        score += 6
        why.append(f"name: {dw.name}")
    for c in dw.columns:
        bits = []
        if term in c.label.lower():
            bits.append(f"label '{c.label}'")
        if term in c.name.lower() or term in c.dbname.lower():
            bits.append(f"column {c.name}" + (f" = {c.dbname}" if c.dbname else ""))
        if bits:
            score += 5
            flag = " [hidden on screen]" if c.shown is False else ""
            why.append(", ".join(bits) + flag)
    for lab in dw.labels:
        if term in lab.lower():
            score += 3
            why.append(f"screen text '{lab}'")
            break
    for t in dw.tables:
        if term in t.lower():
            score += 3
            why.append(f"table {t}")
    if term in dw.comment.lower():
        score += 2
        why.append("comment")
    for name, expr in dw.computes:
        if term in name.lower() or term in expr.lower():
            score += 2
            why.append(f"computed field {name}")
            break
    if not score and term in dw.sql_text.lower():
        score += 1
        why.append("appears in SQL")
    if not score and any(term in i.lower() for i in dw.identifiers):
        score += 1
        why.append("internal name")
    return score, why[:6]


# ---------------------------------------------------------------------- building


def _iter_files(paths: list[str | Path]) -> list[Path]:
    wanted = LIBRARY_SUFFIXES | SOURCE_SUFFIXES | REPORT_SUFFIXES
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in ("$recycle.bin", "node_modules")]
                for f in files:
                    if Path(f).suffix.lower() in wanted:
                        out.append(Path(root) / f)
    return sorted(set(out), key=lambda x: str(x).lower())


def build(paths: list[str | Path], encoding: str = "cp1252", progress=None) -> Catalog:
    from . import psr  # local import: psr imports catalog-free modules only

    cat = Catalog()
    seen: dict[str, DataWindow] = {}

    def add(dw: DataWindow) -> None:
        key = dw.name.lower()
        old = seen.get(key)
        # Prefer readable source over compiled; otherwise keep the first copy found.
        if old is None or (old.form == "compiled" and dw.form == "source"):
            if old is not None:
                cat.datawindows.remove(old)
            seen[key] = dw
            cat.datawindows.append(dw)

    files = _iter_files(paths)
    for i, f in enumerate(files):
        if progress:
            progress(i + 1, len(files), f)
        suffix = f.suffix.lower()
        try:
            if f.stat().st_size > MAX_FILE:
                cat.errors.append(f"{f}: skipped, larger than {MAX_FILE // (1024 * 1024)} MB")
                continue
            if suffix in LIBRARY_SUFFIXES:
                if suffix in (".exe", ".dll") and not is_library(f):
                    continue
                lib = Library.open(f, encoding)
                dws = lib.datawindows()
                for e in dws:
                    if e.kind == "srd":
                        dw = parse_source(lib.text(e), e.stem, str(f))
                    else:
                        dw = parse_compiled(lib.body(e), e.stem, str(f), encoding)
                    dw.comment = _safe_comment(lib, e)
                    add(dw)
                cat.sources.append({
                    "path": str(f), "type": "library", "unicode": lib.unicode,
                    "objects": len(lib.entries), "datawindows": len(dws), "warnings": lib.warnings,
                })
            elif suffix in SOURCE_SUFFIXES:
                text = _read_text(f, encoding)
                if looks_like_syntax(text):
                    text = re.sub(r"^\s*(?:HA)?\$PBExportHeader\$.*\n", "", text)
                    text = re.sub(r"^\s*\$PBExportComments\$.*\n", "", text)
                    add(parse_source(text, f.stem, str(f)))
                    cat.sources.append({"path": str(f), "type": "source", "datawindows": 1})
            elif suffix in REPORT_SUFFIXES:
                rep = psr.read(f, encoding)
                if rep.datawindow is not None:
                    rep.datawindow.name = rep.datawindow.name or f.stem
                    add(rep.datawindow)
                cat.sources.append({"path": str(f), "type": "psr", "variant": rep.variant,
                                    "datawindows": int(rep.datawindow is not None)})
        except (LibraryError, OSError, ValueError) as exc:
            cat.errors.append(f"{f}: {exc}")

    # Cross-reference compiled DataWindows to the others they mention (dropdowns, nested reports).
    names = {dw.name.lower(): dw.name for dw in cat.datawindows}
    for dw in cat.datawindows:
        for ident in dw.identifiers:
            ref = names.get(ident.lower())
            if ref and ref.lower() != dw.name.lower() and ref not in dw.references:
                dw.references.append(ref)
    cat.datawindows.sort(key=lambda d: d.name.lower())
    return cat


def _safe_comment(lib: Library, e) -> str:
    try:
        return lib.comment_of(e).strip() if e.comment_len else ""
    except LibraryError:
        return ""


def _read_text(p: Path, encoding: str) -> str:
    raw = p.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", "replace")
    if len(raw) > 3 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(encoding, "replace")
