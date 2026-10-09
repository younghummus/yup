"""Find where the Units database lives, from the settings files on a Units PC.

PowerBuilder applications keep their database connection in INI files (``DBMS=``,
``ServerName=``, ``Database=``, ``DBParm=``), OLE DB ``.udl`` files, ODBC ``.dsn`` files,
connection strings, or ODBC data sources in the Windows registry. This module reads those,
**masks every password**, and summarises which database engine and server Units talks to,
which is what IT needs to set up read-only reporting access.

It reads files only; it never connects to anything.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

TEXT_SUFFIXES = {".ini", ".udl", ".dsn", ".cfg", ".config", ".conf", ".xml", ".txt", ".reg", ".json", ".properties"}
MAX_TEXT = 4 * 1024 * 1024

#: PowerBuilder DBMS codes -> database engine
DBMS = {
    "mss": "Microsoft SQL Server", "msoledbsql": "Microsoft SQL Server", "snc": "Microsoft SQL Server",
    "ole db": "OLE DB (see Provider)", "odbc": "ODBC (see DSN / driver)", "ado.net": "ADO.NET (see provider)",
    "syc": "SAP/Sybase ASE", "syj": "SAP/Sybase ASE", "syb": "SAP/Sybase ASE", "ase": "SAP/Sybase ASE",
    "o10": "Oracle", "o90": "Oracle", "o84": "Oracle", "ora": "Oracle", "oracle": "Oracle",
    "in9": "Informix", "i10": "Informix", "jdb": "JDBC", "dir": "DirectConnect", "pgs": "PostgreSQL",
}
PROVIDERS = {
    "sqloledb": "Microsoft SQL Server", "sqlncli": "Microsoft SQL Server", "msoledbsql": "Microsoft SQL Server",
    "sql server": "Microsoft SQL Server", "odbc driver": "Microsoft SQL Server", "sqlserver": "Microsoft SQL Server",
    "sql anywhere": "SAP SQL Anywhere", "adaptive server anywhere": "SAP SQL Anywhere", "sybase iq": "SAP IQ",
    "adaptive server enterprise": "SAP/Sybase ASE", "ase": "SAP/Sybase ASE", "oracle": "Oracle", "oraoledb": "Oracle",
    "postgres": "PostgreSQL", "mysql": "MySQL",
}

_SECRET_KEY = re.compile(r"(pass|pwd|secret|token|credential)", re.I)
_INTEREST_KEY = re.compile(
    r"^(dbms|servername|server|database|dbname|logid|userid|user ?id|uid|dbparm|provider|data source|"
    r"initial catalog|dsn|driver|connectstring|host|hostname|port|address|database ?name|"
    r"logpass|logpassword|dbpass|password|pwd|lock|autocommit|connection ?string|datasource)$",
    re.I,
)
_CONN_STRING = re.compile(
    r"((?:provider|data source|server|initial catalog|database|dsn|driver|uid|user id)\s*=\s*[^;\"'\r\n]+\s*;\s*){2,}[^\"'\r\n]*",
    re.I,
)


@dataclass
class Setting:
    file: str
    section: str
    key: str
    value: str  # already masked if secret


@dataclass
class Finding:
    engine: str = ""
    server: str = ""
    database: str = ""
    dsn: str = ""
    driver: str = ""
    user: str = ""
    source: str = ""


@dataclass
class Result:
    settings: list[Setting] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    scanned: int = 0
    notes: list[str] = field(default_factory=list)


def mask(value: str) -> str:
    """Hide passwords, including ones embedded in connection strings."""
    def sub(m: re.Match) -> str:
        return m.group(1) + "****"
    v = re.sub(r"((?:pwd|password|pass|logpass|dbpass)\s*=\s*)('[^']*'|\"[^\"]*\"|[^;'\" ]+)", sub, value, flags=re.I)
    return v


def _engine_from(text: str) -> str:
    t = text.lower()
    for k, v in PROVIDERS.items():
        if k in t:
            return v
    return ""


def _parse_kv_string(s: str) -> dict[str, str]:
    out = {}
    for part in re.split(r";", s):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().strip("'\"").lower()] = v.strip().strip("'\"")
    return out


def _read_text(p: Path) -> str:
    raw = p.read_bytes()[:MAX_TEXT]
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    if len(raw) > 3 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def scan_text(text: str, file: str = "") -> tuple[list[Setting], list[Finding]]:
    settings: list[Setting] = []
    findings: list[Finding] = []
    section = ""
    current: dict[str, str] = {}

    def flush() -> None:
        if current:
            f = _finding_from(current, f"{file} [{section}]" if section else file)
            if f:
                findings.append(f)

    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        m = re.match(r"^\[([^\]]+)\]$", s)
        if m:
            flush()
            current = {}
            section = m.group(1)
            continue
        m = re.match(r'^"?([^"=]{1,60}?)"?\s*=\s*(.*)$', s)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip().strip('"')
            if _INTEREST_KEY.match(key):
                shown = "****" if _SECRET_KEY.search(key) and val else mask(val)
                settings.append(Setting(file, section, key, shown))
                current[key.lower()] = val
    flush()
    for m in _CONN_STRING.finditer(text):
        kv = _parse_kv_string(m.group(0))
        f = _finding_from(kv, f"{file} (connection string)")
        if f and f not in findings:
            findings.append(f)
            settings.append(Setting(file, "connection string", "string", mask(m.group(0).strip())))
    return settings, findings


def _finding_from(kv: dict[str, str], source: str) -> Finding | None:
    g = lambda *keys: next((kv[k] for k in keys if kv.get(k)), "")  # noqa: E731
    dbparm = g("dbparm")
    inner = {}
    if dbparm:
        cs = re.search(r"connectstring\s*=\s*'([^']*)'", dbparm, re.I)
        if cs:
            inner.update(_parse_kv_string(cs.group(1)))
        for k, v in re.findall(r"(\w+)\s*=\s*'([^']*)'", dbparm):
            inner.setdefault(k.lower(), v)
    both = {**inner, **kv}
    h = lambda *keys: next((both[k] for k in keys if both.get(k)), "")  # noqa: E731
    f = Finding(
        server=h("servername", "server", "data source", "datasource", "host", "hostname", "address"),
        database=h("database", "initial catalog", "dbname", "database name", "databasename"),
        dsn=h("dsn"),
        driver=h("driver", "provider"),
        user=h("logid", "userid", "user id", "uid"),
        source=source,
    )
    dbms = g("dbms").lower()
    f.engine = DBMS.get(dbms, "") if dbms else ""
    if not f.engine or "see" in f.engine:
        f.engine = _engine_from(" ".join([f.driver, dbparm, kv.get("provider", "")])) or f.engine
    if not (f.server or f.database or f.dsn or dbms):
        return None
    return f


def scan(paths: list[str | Path], registry: bool = False) -> Result:
    res = Result()
    for p in map(Path, paths):
        files = [p] if p.is_file() else [
            Path(r) / n for r, _d, fs in os.walk(p) for n in fs if Path(n).suffix.lower() in TEXT_SUFFIXES
        ] if p.is_dir() else []
        for f in files:
            try:
                if f.stat().st_size > MAX_TEXT:
                    continue
                s, fi = scan_text(_read_text(f), str(f))
            except OSError as exc:
                res.notes.append(f"{f}: {exc}")
                continue
            res.scanned += 1
            res.settings += s
            res.findings += fi
    if registry:
        s, fi, note = scan_registry()
        res.settings += s
        res.findings += fi
        if note:
            res.notes.append(note)
    return res


def scan_registry() -> tuple[list[Setting], list[Finding], str]:
    """ODBC data sources and PowerBuilder app keys from the Windows registry (Windows only)."""
    if sys.platform != "win32":
        return [], [], "registry scan skipped: only available on Windows"
    import winreg  # type: ignore[import-not-found]

    settings: list[Setting] = []
    findings: list[Finding] = []
    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\ODBC\ODBC.INI"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\ODBC\ODBC.INI"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\ODBC\ODBC.INI"),
    ]
    for hive, base in roots:
        try:
            with winreg.OpenKey(hive, base) as k:
                i = 0
                while True:
                    try:
                        dsn = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    if dsn == "ODBC Data Sources":
                        continue
                    kv: dict[str, str] = {"dsn": dsn}
                    try:
                        with winreg.OpenKey(k, dsn) as dk:
                            j = 0
                            while True:
                                try:
                                    name, val, _t = winreg.EnumValue(dk, j)
                                except OSError:
                                    break
                                j += 1
                                kv[str(name).lower()] = str(val)
                                if _INTEREST_KEY.match(str(name)) or str(name).lower() in ("driver", "server"):
                                    shown = "****" if _SECRET_KEY.search(str(name)) else mask(str(val))
                                    settings.append(Setting(f"registry {base}", dsn, str(name), shown))
                    except OSError:
                        continue
                    f = _finding_from(kv, f"ODBC data source '{dsn}'")
                    if f:
                        f.engine = f.engine or _engine_from(kv.get("driver", ""))
                        findings.append(f)
        except OSError:
            continue
    return settings, findings, ""


def summary(res: Result) -> list[str]:
    lines = []
    seen = set()
    for f in res.findings:
        key = (f.engine, f.server.lower(), f.database.lower(), f.dsn.lower())
        if key in seen:
            continue
        seen.add(key)
        bits = [f"engine: {f.engine or 'unknown'}"]
        if f.server:
            bits.append(f"server: {f.server}")
        if f.database:
            bits.append(f"database: {f.database}")
        if f.dsn:
            bits.append(f"ODBC DSN: {f.dsn}")
        if f.driver:
            bits.append(f"driver/provider: {f.driver}")
        if f.user:
            bits.append(f"login used by the app: {f.user}")
        lines.append(" | ".join(bits) + f"   (from {f.source})")
    return lines
