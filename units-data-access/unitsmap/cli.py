"""Command line: ``python -m unitsmap <command> ...``  (run with no arguments for a guided mode)."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import webbrowser
from pathlib import Path

from . import __version__, catalog as catalog_mod, connection, export, psr, report_html
from .pblib import Library, LibraryError

DEFAULT_OUT = "units-map"
COMMON_INSTALL_DIRS = [r"C:\Units", r"C:\Program Files (x86)\Auto-IT", r"C:\Program Files\Auto-IT",
                       r"C:\Program Files (x86)\Units", r"C:\Program Files\Units", r"C:\AutoIT", r"C:\Auto-IT"]


def _p(*a) -> None:
    print(*a, flush=True)


def _progress(i: int, n: int, f: Path) -> None:
    if sys.stderr.isatty():
        sys.stderr.write(f"\r  reading {i}/{n}: {f.name[:50]:<50}")
        if i == n:
            sys.stderr.write("\n")
        sys.stderr.flush()


def _load(path: str) -> catalog_mod.Catalog:
    p = Path(path)
    if p.is_dir():
        p = p / "catalog.json"
    if not p.exists():
        raise SystemExit(f"No catalog at {p}. Run 'scan' first, e.g.:  python -m unitsmap scan \"C:\\Units\"")
    return catalog_mod.Catalog.load(p)


# ----------------------------------------------------------------------------- commands


def cmd_scan(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    _p(f"Scanning {', '.join(a.paths)} ...")
    cat = catalog_mod.build(a.paths, a.encoding, progress=_progress)
    if not cat.datawindows:
        _p("No DataWindows found. Point me at the folder holding Units' .pbd files (often the install folder).")
        for e in cat.errors[:10]:
            _p("  ! " + e)
        return 1
    cat.save(out / "catalog.json")
    export.write_xlsx(cat, out / "units-map.xlsx")
    export.write_csv(cat, out / "csv")
    nsql = export.write_sql(cat, out / "sql")
    report_html.write(cat, out / "units-map.html")
    hidden = sum(len(d.hidden_columns) for d in cat.datawindows)
    enc = sum(1 for d in cat.datawindows if d.sql_encrypted)
    _p("")
    _p(f"  DataWindows (screens, lists, reports): {len(cat.datawindows)}")
    _p(f"  Tables seen:                           {len(cat.tables())}")
    _p(f"  Columns:                               {sum(len(d.columns) for d in cat.datawindows)}"
       f"  ({hidden} fetched but hidden on screen)")
    _p(f"  Joins learned from Units' own SQL:     {len(cat.edges())}")
    if enc:
        _p(f"  DataWindows with encrypted SQL:        {enc} (columns still listed)")
    if cat.errors:
        _p(f"  Files that could not be read:          {len(cat.errors)} (listed in the 'Files read' sheet)")
    _p("")
    _p(f"  Open this in your browser:  {out / 'units-map.html'}")
    _p(f"  Or in Excel:                {out / 'units-map.xlsx'}")
    _p(f"  One .sql file per screen:   {out / 'sql'} ({nsql} files)")
    if a.open:
        webbrowser.open((out / "units-map.html").resolve().as_uri())
    return 0


def cmd_search(a) -> int:
    cat = _load(a.catalog)
    hits = cat.search(a.terms, a.limit)
    if not hits:
        _p("No DataWindow matches every word. Try fewer or shorter words.")
        return 1
    for h in hits:
        dw = h.dw
        _p(f"{dw.name}  [{Path(dw.library).name}]  tables: {', '.join(dw.tables) or '-'}")
        for r in h.reasons:
            _p(f"    - {r}")
    _p(f"\n{len(hits)} match(es). See one in full with:  python -m unitsmap show {a.catalog} <name>")
    return 0


def cmd_show(a) -> int:
    cat = _load(a.catalog)
    dw = cat.get(a.name)
    if dw is None:
        _p(f"No DataWindow called {a.name}. Try: python -m unitsmap search {a.catalog} {a.name}")
        return 1
    _p(f"{dw.name}   ({dw.form}, from {dw.library})")
    if dw.comment:
        _p(f"  {dw.comment}")
    _p(f"  Tables: {', '.join(dw.tables) or '-'}")
    if dw.arguments:
        _p("  Inputs: " + ", ".join(f":{n}" + (f" ({t})" if t else "") for n, t in dw.arguments))
    _p("")
    w = max([len(c.name) for c in dw.columns] + [6])
    for c in dw.columns:
        flag = {True: "", False: "  << HIDDEN on screen", None: ""}[c.shown]
        look = f"  lookup {c.dddw} shows {c.dddw_display}" if c.dddw else ""
        label = f"  \"{c.label}\"" if c.label else ""
        _p(f"  {c.name:<{w}}  {c.dbname or '-'}{label}{look}{flag}")
    for n, e in dw.computes:
        _p(f"  {n:<{w}}  = {e}  (computed)")
    if dw.references:
        _p(f"\n  Uses: {', '.join(dw.references)}")
    for warn in dw.warnings:
        _p(f"  ! {warn}")
    if dw.sql_text:
        _p("\nSQL:\n" + dw.sql_text)
    return 0


def cmd_sql(a) -> int:
    cat = _load(a.catalog)
    dw = cat.get(a.name)
    if dw is None:
        _p(f"No DataWindow called {a.name}")
        return 1
    if not dw.sql_text:
        _p("-- No SQL recovered for this DataWindow" + (" (it is encrypted)" if dw.sql_encrypted else ""))
        return 1
    _p(fill_inputs(dw.sql_text, a.set or []))
    return 0


def fill_inputs(sql: str, assignments: list[str]) -> str:
    """Replace ``:name`` inputs with literal values. Text is quoted; plain numbers are not."""
    for item in assignments:
        if "=" not in item:
            raise SystemExit(f"--set needs NAME=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        k = k.strip().lstrip(":")
        numeric = re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", v) is not None
        lit = v if numeric else "'" + v.replace("'", "''") + "'"
        sql = re.sub(rf"(?<![\w:]):{re.escape(k)}(?!\w)", lambda _m: lit, sql, flags=re.I)
    return sql


def cmd_join(a) -> int:
    cat = _load(a.catalog)
    known = {t.lower() for t in cat.tables()}
    for t in a.tables:
        if t.lower() not in known:
            close = [x for x in known if t.lower() in x][:8]
            _p(f"-- note: table '{t}' was not seen in any DataWindow" + (f"; similar: {', '.join(close)}" if close else ""))
    if len(a.tables) == 2 and not a.columns:
        chain = cat.path(a.tables[0], a.tables[1])
        if chain:
            nodes, cur = [a.tables[0]], a.tables[0].lower()
            for e in chain:
                nxt = e.b if e.a.lower() == cur else e.a
                nodes.append(nxt)
                cur = nxt.lower()
            _p("-- Path: " + " -> ".join(nodes))
    _p(cat.join_sql(a.tables, a.columns))
    return 0


def cmd_psr(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rc = 0
    for f in a.files:
        try:
            rep = psr.read(f, a.encoding)
        except (OSError, ValueError) as exc:
            _p(f"{f}: {exc}")
            rc = 1
            continue
        stem = Path(f).stem
        _p(f"{f}: {rep.variant} PSR")
        for n in rep.notes:
            _p(f"  - {n}")
        dw = rep.datawindow
        if dw:
            _p(f"  columns: {', '.join(c.name for c in dw.columns) or '-'}")
            _p(f"  tables:  {', '.join(dw.tables) or '-'}")
            with open(out / f"{stem}-columns.csv", "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["Column", "Database name", "Label", "Type", "On screen"])
                for c in dw.columns:
                    w.writerow([c.name, c.dbname, c.label, c.type, {True: "yes", False: "HIDDEN", None: ""}[c.shown]])
            if dw.sql_text:
                (out / f"{stem}.sql").write_text(dw.sql_text + "\n", encoding="utf-8")
        with open(out / f"{stem}-text-values.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["#", "Text value (in file order)"])
            for i, v in enumerate(rep.values, 1):
                w.writerow([i, v])
        _p(f"  {len(rep.values)} text values saved; files in {out}")
    return rc


def cmd_connection(a) -> int:
    paths = a.paths or [d for d in COMMON_INSTALL_DIRS if Path(d).exists()]
    if not paths:
        _p("Tell me where Units is installed, e.g.:  python -m unitsmap connection \"C:\\Units\"")
        return 1
    res = connection.scan(paths, registry=a.registry)
    _p(f"Scanned {res.scanned} settings file(s). Passwords are always shown as ****.\n")
    lines = connection.summary(res)
    if lines:
        _p("Database connection(s) found:")
        for ln in lines:
            _p("  * " + ln)
    else:
        _p("No database connection settings found in those files.")
        if not a.registry and sys.platform == "win32":
            _p("Try adding --registry to also check ODBC data sources in Windows.")
    if a.verbose and res.settings:
        _p("\nAll settings seen:")
        for s in res.settings:
            _p(f"  {s.file} [{s.section}] {s.key} = {s.value}")
    for n in res.notes:
        _p("  note: " + n)
    return 0


def cmd_dump(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        lib = Library.open(a.library, a.encoding)
    except (LibraryError, OSError) as exc:
        _p(f"{a.library}: {exc}")
        return 1
    _p(f"{a.library}: {'Unicode' if lib.unicode else 'ANSI'} library, {len(lib.entries)} objects")
    for e in lib.entries:
        if a.list:
            m = e.modified.strftime("%Y-%m-%d") if e.modified else ""
            _p(f"  {e.name:<45} {e.size:>9,}  {m}")
            continue
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in e.name)
        if e.is_source:
            (out / safe).write_text(lib.text(e), encoding="utf-8")
        else:
            (out / safe).write_bytes(lib.body(e))
    if not a.list:
        _p(f"Wrote {len(lib.entries)} objects to {out}")
    return 0


def cmd_demo(a) -> int:
    from .fixtures import write_demo

    folder = Path(a.folder)
    files = write_demo(folder)
    _p(f"Wrote a made-up dealership app to {folder} ({len(files)} files). Now mapping it:\n")
    rc = cmd_scan(argparse.Namespace(paths=[str(folder)], out=a.out, encoding="cp1252", open=a.open))
    _p("")
    cmd_connection(argparse.Namespace(paths=[str(folder)], registry=False, verbose=False))
    _p(f"\nTry:  python -m unitsmap search {a.out} sold by")
    _p(f"      python -m unitsmap join {a.out} vehicle staff")
    return rc


def guided() -> int:
    _p(f"unitsmap {__version__}: maps the tables and columns behind every Units screen.")
    _p("It only reads files on this computer. It never connects to or changes the Units database.\n")
    found = [d for d in COMMON_INSTALL_DIRS if Path(d).exists()]
    hint = f" [{found[0]}]" if found else ""
    try:
        folder = input(f"Folder that holds Units' .pbd files{hint}: ").strip().strip('"') or (found[0] if found else "")
    except EOFError:
        folder = found[0] if found else ""
    if not folder or not Path(folder).exists():
        _p("That folder does not exist. Tip: right-click the Units shortcut > Open file location.")
        return 1
    out = str(Path.cwd() / DEFAULT_OUT)
    rc = cmd_scan(argparse.Namespace(paths=[folder], out=out, encoding="cp1252", open=True))
    _p("")
    cmd_connection(argparse.Namespace(paths=[folder], registry=sys.platform == "win32", verbose=False))
    return rc


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return guided()
    ap = argparse.ArgumentParser(prog="unitsmap", description="Map the tables and columns behind a PowerBuilder app such as Auto-IT Units. Read-only.")
    ap.add_argument("--version", action="version", version=f"unitsmap {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="read .pbd/.pbl/.exe/.dll/.srd/.psr files and build the map")
    s.add_argument("paths", nargs="+", help="files or folders (folders are searched recursively)")
    s.add_argument("-o", "--out", default=DEFAULT_OUT, help=f"output folder (default: {DEFAULT_OUT})")
    s.add_argument("--encoding", default="cp1252", help="code page for pre-Unicode files (default cp1252)")
    s.add_argument("--open", action="store_true", help="open the HTML map when done")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("search", help="find DataWindows by label, column, table or SQL text")
    s.add_argument("catalog", help="catalog.json or the scan output folder")
    s.add_argument("terms", nargs="+")
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("show", help="columns, hidden fields and SQL for one DataWindow")
    s.add_argument("catalog")
    s.add_argument("name")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("sql", help="print a DataWindow's SQL, optionally filling in its inputs")
    s.add_argument("catalog")
    s.add_argument("name")
    s.add_argument("--set", action="append", metavar="NAME=VALUE", help="fill an input, e.g. --set as_vin=JT123")
    s.set_defaults(fn=cmd_sql)

    s = sub.add_parser("join", help="write SQL joining tables the way Units joins them")
    s.add_argument("catalog")
    s.add_argument("tables", nargs="+")
    s.add_argument("--columns", nargs="+", help="columns to select, e.g. vehicle.vin deal.salesperson")
    s.set_defaults(fn=cmd_join)

    s = sub.add_parser("psr", help="read saved reports (.psr): columns, SQL and text values")
    s.add_argument("files", nargs="+")
    s.add_argument("-o", "--out", default="psr-out")
    s.add_argument("--encoding", default="cp1252")
    s.set_defaults(fn=cmd_psr)

    s = sub.add_parser("connection", help="find which database server Units uses (passwords masked)")
    s.add_argument("paths", nargs="*", help="Units install folder(s) or settings files")
    s.add_argument("--registry", action="store_true", help="also read ODBC data sources (Windows)")
    s.add_argument("-v", "--verbose", action="store_true", help="list every setting seen")
    s.set_defaults(fn=cmd_connection)

    s = sub.add_parser("demo", help="build a made-up dealership app and map it, to see what you get")
    s.add_argument("folder", nargs="?", default="unitsmap-demo")
    s.add_argument("-o", "--out", default="unitsmap-demo-map")
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("dump", help="list or extract every object in one library")
    s.add_argument("library")
    s.add_argument("-o", "--out", default="dump")
    s.add_argument("--list", action="store_true", help="only list objects")
    s.add_argument("--encoding", default="cp1252")
    s.set_defaults(fn=cmd_dump)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
