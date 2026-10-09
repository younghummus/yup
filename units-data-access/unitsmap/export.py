"""Turn a Catalog into things people use: an Excel workbook, CSV files, and .sql files."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from . import xlsx
from .catalog import Catalog


def _shown(v) -> str:
    return {True: "yes", False: "HIDDEN", None: "unknown"}[v]


def tables_rows(cat: Catalog) -> dict[str, list[list]]:
    dws = [["DataWindow", "File", "Form", "Tables", "Columns", "Hidden columns", "Arguments",
            "SQL encrypted", "Comment", "Uses (dropdowns / nested)"]]
    cols = [["DataWindow", "Column", "Database name (table.column)", "Table", "Type", "Screen label",
             "On screen", "Dropdown lookup", "Lookup shows", "Lookup stores", "Key", "Updatable", "Code values"]]
    sql = [["DataWindow", "Arguments", "SQL (ready to paste)", "As stored by Units"]]
    for dw in cat.datawindows:
        dws.append([dw.name, Path(dw.library).name, dw.form, ", ".join(dw.tables), len(dw.columns),
                    len(dw.hidden_columns), ", ".join(a for a, _ in dw.arguments),
                    "yes" if dw.sql_encrypted else "", dw.comment, ", ".join(dw.references)])
        for c in dw.columns:
            cols.append([dw.name, c.name, c.dbname, c.table, c.type, c.label, _shown(c.shown), c.dddw,
                         c.dddw_display, c.dddw_data, "yes" if c.key else "", "yes" if c.updatable else "", c.codes])
        if dw.sql_text or dw.sql:
            sql.append([dw.name, ", ".join(a for a, _ in dw.arguments), dw.sql_text,
                        dw.sql if dw.sql != dw.sql_text else ""])
    tbl = [["Table", "Columns seen", "Column count", "Used by DataWindows", "DataWindow names"]]
    for info in cat.tables().values():
        names = info["datawindows"]
        tbl.append([info["name"], ", ".join(sorted(info["columns"], key=str.lower)), len(info["columns"]),
                    len(names), ", ".join(names[:40]) + (" ..." if len(names) > 40 else "")])
    joins = [["Table A", "Table B", "Join condition", "Used by # DataWindows", "Examples"]]
    for e in sorted(cat.edges().values(), key=lambda e: (-e.count, e.a.lower(), e.b.lower())):
        joins.append([e.a, e.b, " AND ".join(f"{x} = {y}" for x, y in e.pairs), e.count, ", ".join(e.examples)])
    src = [["File", "Type", "Objects", "DataWindows", "Notes"]]
    for s in cat.sources:
        src.append([s.get("path"), s.get("type"), s.get("objects", ""), s.get("datawindows", ""),
                    "; ".join(s.get("warnings", []) or []) + (f" variant={s['variant']}" if s.get("variant") else "")])
    for e in cat.errors:
        src.append(["", "error", "", "", e])
    return {"DataWindows": dws, "Columns": cols, "Tables": tbl, "Joins": joins, "SQL": sql, "Files read": src}


START_HERE = [
    ["How to use this workbook"],
    ["Every Units screen, list and report is a 'DataWindow'. This workbook lists all of them and what is behind them."],
    ["Columns sheet: filter 'Screen label' or 'Column' for the field you want (e.g. 'sold', 'sales', 'VIN')."],
    ["   'Database name' tells you the real table.column it comes from."],
    ["   'On screen' = HIDDEN means the screen fetches that field but does not show it."],
    ["   'Dropdown lookup' means the screen shows a name but stores a code; the lookup DataWindow translates it."],
    ["Tables sheet: every table seen, with the columns Units reads from it."],
    ["Joins sheet: how Units itself links tables (e.g. vehicle to deal). Use these in your own queries."],
    ["SQL sheet: the exact query behind each DataWindow, converted to plain SQL you can paste into Excel Power Query."],
    ["Lines starting with ':' in SQL (e.g. :as_vin) are inputs; replace them with a value in quotes, e.g. 'JTDBR32E...'."],
    ["See units-data-access/README.md for the full guide."],
]


def write_xlsx(cat: Catalog, path: str | Path) -> None:
    sheets = {"Start here": START_HERE}
    sheets.update(tables_rows(cat))
    xlsx.write(path, sheets)


def write_csv(cat: Catalog, folder: str | Path) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, rows in tables_rows(cat).items():
        p = folder / (re.sub(r"\W+", "_", name.lower()).strip("_") + ".csv")
        with open(p, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel opens UTF-8 correctly
            csv.writer(f).writerows(rows)
        out.append(p)
    return out


def write_sql(cat: Catalog, folder: str | Path) -> int:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    for dw in cat.datawindows:
        if not (dw.sql_text or dw.sql):
            continue
        head = [f"-- DataWindow: {dw.name}", f"-- From: {dw.library}"]
        if dw.comment:
            head.append(f"-- Comment: {dw.comment}")
        if dw.tables:
            head.append(f"-- Tables: {', '.join(dw.tables)}")
        if dw.arguments:
            head.append("-- Inputs to replace before running: " + ", ".join(f":{a}" for a, _ in dw.arguments))
        hidden = [c.name for c in dw.hidden_columns]
        if hidden:
            head.append("-- Fetched but hidden on screen: " + ", ".join(hidden))
        body = dw.sql_text or dw.sql
        if dw.sql and dw.sql != dw.sql_text:
            body += "\n\n/* As stored by Units:\n" + dw.sql.replace("*/", "* /") + "\n*/"
        safe = re.sub(r"[^\w.-]+", "_", dw.name)
        (folder / f"{safe}.sql").write_text("\n".join(head) + "\n\n" + body + "\n", encoding="utf-8")
        n += 1
    return n
