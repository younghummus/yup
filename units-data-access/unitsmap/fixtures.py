"""Build PowerBuilder-format files from scratch: libraries, compiled DataWindows, PSR reports.

Used by the test-suite and by ``python -m unitsmap demo``, which writes a small made-up
dealership application (vehicles, deals, salespeople, workshop repair orders) so you can see
what the tool produces before pointing it at real Units files. Nothing here is Auto-IT code
or data: the table and column names are invented.
"""

from __future__ import annotations

import math
import struct
import time
from pathlib import Path

BLOCK = 512
NODE = 3072
ENDOFCHAIN, FREESECT, FATSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF


# ----------------------------------------------------------------------------- libraries


def build_library(objects: dict[str, bytes | str], unicode: bool = False, comments: dict[str, str] | None = None,
                  per_node: int = 0, encoding: str = "cp1252", comment: str = "", timestamp: int | None = None) -> bytes:
    """Write a .pbl/.pbd image. ``objects`` maps entry name -> body (str bodies are encoded).

    ``per_node`` > 0 spreads entries over several directory nodes linked as a small tree
    (root -> left child -> right sibling), exercising directory traversal.
    """
    comments = comments or {}
    ts = int(time.time()) if timestamp is None else timestamp
    enc = "utf-16-le" if unicode else encoding
    hdr_size = 1024 if unicode else BLOCK

    names = list(objects)
    groups = [names] if per_node <= 0 else [names[i:i + per_node] for i in range(0, len(names), per_node)] or [[]]
    node_offsets = [hdr_size + BLOCK + i * NODE for i in range(len(groups))]
    data_start = hdr_size + BLOCK + len(groups) * NODE

    payloads: dict[str, bytes] = {}
    for n in names:
        body = objects[n]
        raw = body.encode(enc) if isinstance(body, str) else body
        payloads[n] = comments.get(n, "").encode(enc) + raw

    dat = bytearray()
    first_block: dict[str, int] = {}
    for n in names:
        p = payloads[n]
        chunks = [p[i:i + 502] for i in range(0, len(p), 502)] or [b""]
        first_block[n] = data_start + len(dat)
        for i, ch in enumerate(chunks):
            here = data_start + len(dat)
            nxt = here + BLOCK if i < len(chunks) - 1 else 0
            dat += b"DAT*" + struct.pack("<IH", nxt, len(ch)) + ch.ljust(502, b"\x00")

    # Header
    if unicode:
        hdr = b"HDR*" + "PowerBuilder\x00\x00".encode("utf-16-le") + "0600".encode("utf-16-le") + struct.pack("<I", ts)
        hdr += b"\x00\x00" + comment.encode("utf-16-le")[:510]
    else:
        hdr = b"HDR*" + b"PowerBuilder\x00\x00" + b"0600" + struct.pack("<I", ts) + b"\x00\x00" + comment.encode(encoding)[:255]
    hdr = hdr.ljust(hdr_size, b"\x00")
    fre = (b"FRE*" + struct.pack("<I", 0)).ljust(BLOCK, b"\xff")

    # Tree: node 0 is root; node 1 is its left child; node k>1 is the right sibling of node k-1.
    nodes = bytearray()
    for gi, group in enumerate(groups):
        left = node_offsets[1] if gi == 0 and len(groups) > 1 else 0
        parent = 0 if gi == 0 else node_offsets[0] if gi == 1 else node_offsets[gi - 1]
        right = node_offsets[gi + 1] if gi >= 1 and gi + 1 < len(groups) else 0
        ents = bytearray()
        for n in group:
            name_raw = n.encode(enc) + (b"\x00\x00" if unicode else b"\x00")
            clen = len(comments.get(n, ""))  # characters (Unicode) == bytes (ANSI single-byte)
            if not unicode:
                clen = len(comments.get(n, "").encode(encoding))
            ver = "0600".encode("utf-16-le") if unicode else b"0600"
            ents += b"ENT*" + ver + struct.pack("<IIIHH", first_block[n], len(payloads[n]), ts, clen, len(name_raw)) + name_raw
        if len(ents) > NODE - 32:
            raise ValueError("too many entries for one node; use per_node")
        head = b"NOD*" + struct.pack("<IIIHHHH", left, parent, right, NODE - 32 - len(ents), 32, len(group), 32) + b"\x00" * 8
        nodes += (head + ents).ljust(NODE, b"\x00")
    return bytes(hdr + fre + nodes + dat)


def embed_in_exe(library: bytes, stub: bytes = b"MZ" + b"\x90" * 1022) -> bytes:
    """Mimic a PowerBuilder-built EXE/DLL: program bytes, then the library, then a TRL* block."""
    stub = stub.ljust(math.ceil(len(stub) / BLOCK) * BLOCK, b"\x00")
    off = len(stub)
    # Offsets inside an embedded library are absolute in the EXE.
    rebased = _rebase(library, off)
    trailer = (b"TRL*" + struct.pack("<I", off)).ljust(BLOCK, b"\x00")
    return stub + rebased + trailer


def _rebase(lib: bytes, delta: int) -> bytes:
    b = bytearray(lib)
    unicode = b[4:6] == b"P\x00"
    for pos in range(0, len(b), BLOCK):
        tag = bytes(b[pos:pos + 4])
        if tag == b"NOD*":
            for k in (4, 8, 12):
                (v,) = struct.unpack_from("<I", b, pos + k)
                if v:
                    struct.pack_into("<I", b, pos + k, v + delta)
            (count,) = struct.unpack_from("<H", b, pos + 20)
            p = pos + 32
            for _ in range(count):
                o = p + (12 if unicode else 8)
                (v,) = struct.unpack_from("<I", b, o)
                struct.pack_into("<I", b, o, v + delta)
                (nlen,) = struct.unpack_from("<H", b, o + 14)
                p += (28 if unicode else 24) + nlen
        elif tag == b"DAT*":
            (v,) = struct.unpack_from("<I", b, pos + 4)
            if v:
                struct.pack_into("<I", b, pos + 4, v + delta)
    return bytes(b)


# ----------------------------------------------------------------------------- compiled DataWindows


def build_dwo(strings: list[str], unicode: bool = False, release: str = "0900", encoding: str = "cp1252") -> bytes:
    """A stand-in for a compiled DataWindow: binary records with length-prefixed strings.

    Real compiled objects interleave strings with binary records the same way; the parser
    only relies on the strings and their order.
    """
    out = bytearray(f"PDW{release}".encode("ascii") + b"\x00" + struct.pack("<II", 0x97, 0x3AA) + b"pdw\x00")
    out += b"\x00" * 64
    for i, s in enumerate(strings):
        raw = s.encode("utf-16-le") + b"\x00\x00" if unicode else s.encode(encoding) + b"\x00"
        out += struct.pack("<IIII", 0x1C, 0x24, i * 2, 0) + struct.pack("<I", len(raw)) + raw
    out += b"\x00" * 32
    return bytes(out)


def compiled_strings(dw_columns: list[tuple[str, str]], sql: str, args: list[str] = (),
                     texts: dict[str, str] | None = None, shown: list[str] = (), extra: list[str] = ()) -> list[str]:
    """Strings in the order a compiled DataWindow stores them.

    Mirrors real objects: layout first (each heading ``<col>_t`` followed by its font, sizes,
    colours and text; each on-screen column by name), then argument names, then the table
    section as ``name, table.column`` pairs, then the SQL with \\x01 where each argument goes.
    """
    s: list[str] = []
    for col, text in (texts or {}).items():
        s += [f"{col}_t", "536870912", "Tahoma", "Tahoma", "-8", "400", "33554432", "9", text]
    for col in shown:
        s += [col, "[general]", "[general]"]
    s += list(extra)
    s += [f":{a}" for a in args] + list(args)
    for name, dbname in dw_columns:
        s += [name, dbname]
    hole_sql = sql
    for a in args:
        hole_sql = hole_sql.replace(f":{a}", "\x01")
    if sql:
        s.append(hole_sql)
    return s


# ----------------------------------------------------------------------------- PSR reports


def build_psr_binary(dwo: bytes, values: list[str], encoding: str = "cp1252") -> bytes:
    out = bytearray(b"\x00" * 16 + b"Platform independent PSR File Format, Copyright Sybase, Inc. 1997\x00")
    out += struct.pack("<I", len(dwo)) + dwo
    out += b"\x00" * 16
    for v in values:
        raw = v.encode(encoding) + b"\x00"
        out += struct.pack("<HI", 1, len(raw)) + raw + struct.pack("<d", 0.0)
    return bytes(out)


def build_cfb(streams: dict[str, bytes]) -> bytes:
    """Write a version-3 OLE2 compound file with the given root-level streams."""
    sectors: list[bytes] = []
    fat: list[int] = []

    def alloc(data: bytes) -> int:
        if not data:
            return ENDOFCHAIN
        n = math.ceil(len(data) / BLOCK)
        start = len(sectors)
        for i in range(n):
            sectors.append(data[i * BLOCK:(i + 1) * BLOCK].ljust(BLOCK, b"\x00"))
            fat.append(start + i + 1 if i < n - 1 else ENDOFCHAIN)
        return start

    mini = bytearray()
    minifat: list[int] = []
    infos = []
    for name, data in streams.items():
        if len(data) < 4096:
            if data:
                start = len(mini) // 64
                n = math.ceil(len(data) / 64)
                minifat += [start + i + 1 if i < n - 1 else ENDOFCHAIN for i in range(n)]
                mini += data.ljust(n * 64, b"\x00")
            else:
                start = ENDOFCHAIN
        else:
            start = alloc(data)
        infos.append((name, start, len(data)))
    root_start = alloc(bytes(mini))
    mf_bytes = b"".join(struct.pack("<I", x) for x in minifat)
    mf_bytes = mf_bytes.ljust(math.ceil(len(mf_bytes) / BLOCK) * BLOCK, b"\xff") if mf_bytes else b""
    minifat_start = alloc(mf_bytes)
    n_minifat = len(mf_bytes) // BLOCK

    def entry(name: str, etype: int, left: int, right: int, child: int, start: int, size: int) -> bytes:
        nm = name.encode("utf-16-le")[:62]
        raw = nm.ljust(64, b"\x00") + struct.pack("<HBB", len(nm) + 2 if name else 0, etype, 1)
        raw += struct.pack("<III", left, right, child) + b"\x00" * 16 + b"\x00" * 4 + b"\x00" * 16
        raw += struct.pack("<IQ", start, size)
        return raw

    dir_bytes = entry("Root Entry", 5, NOSTREAM, NOSTREAM, 1 if infos else NOSTREAM, root_start, len(mini))
    for i, (name, start, size) in enumerate(infos):
        right = i + 2 if i + 1 < len(infos) else NOSTREAM
        dir_bytes += entry(name, 2, NOSTREAM, right, NOSTREAM, start, size)
    while len(dir_bytes) % BLOCK:
        dir_bytes += entry("", 0, NOSTREAM, NOSTREAM, NOSTREAM, 0, 0)
    dir_start = alloc(dir_bytes)

    nfat = 1
    while len(sectors) + nfat > nfat * 128:
        nfat += 1
    fat_ids = list(range(len(sectors), len(sectors) + nfat))
    fat += [FATSECT] * nfat
    fat += [FREESECT] * (nfat * 128 - len(fat))
    for i in range(nfat):
        sectors.append(b"".join(struct.pack("<I", x) for x in fat[i * 128:(i + 1) * 128]))

    header = bytearray(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16)
    header += struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
    header += struct.pack("<IIIIIIIII", 0, nfat, dir_start, 0, 4096, minifat_start, n_minifat, ENDOFCHAIN, 0)
    difat = fat_ids + [FREESECT] * (109 - len(fat_ids))
    header += b"".join(struct.pack("<I", x) for x in difat)
    return bytes(header.ljust(BLOCK, b"\x00")) + b"".join(sectors)


# ----------------------------------------------------------------------------- demo dealership app


def _syntax(columns: list[dict], retrieve: str, texts: dict[str, str], shown: list[str], args: list[tuple[str, str]] = (),
            update: str = "", extra: str = "", dddw: dict[str, tuple[str, str, str]] | None = None) -> str:
    dddw = dddw or {}
    esc = retrieve.replace('"', '~"')
    cols = "\n ".join(
        f'column=(type={c["type"]} updatewhereclause=yes {"key=yes " if c.get("key") else ""}name={c["name"]} dbname="{c["dbname"]}" )'
        for c in columns)
    arg = (" arguments=(" + ",".join(f'("{n}", {t})' for n, t in args) + ")") if args else ""
    upd = f' update="{update}" updatewhere=1 updatekeyinplace=no' if update else ""
    body = [
        "release 12.5;",
        'datawindow(units=0 timer_interval=0 color=1073741824 processing=1 print.documentname="" )',
        'header(height=80 color="536870912" )',
        'detail(height=72 color="536870912" )',
        f'table({cols}\n retrieve="{esc}"{upd}{arg} )',
    ]
    for name, text in texts.items():
        body.append(f'text(band=header alignment="0" text="{text}" border="0" color="33554432" x="9" y="8" height="64" width="300" name={name}_t visible="1" font.face="Tahoma" font.height="-8" )')
    for name in shown:
        dd = ""
        if name in dddw:
            dn, disp, data = dddw[name]
            dd = f" dddw.name={dn} dddw.displaycolumn={disp} dddw.datacolumn={data} dddw.percentwidth=0"
        body.append(f'column(band=detail id=1 alignment="0" tabsequence=10 border="0" color="33554432" x="9" y="4" height="64" width="300" format="[general]" name={name} visible="1"{dd} edit.limit=0 font.face="Tahoma" font.height="-8" )')
    body.append(extra)
    return "\n".join(b for b in body if b) + "\n"


def demo_objects(compiled: bool = True) -> dict[str, bytes | str]:
    """A miniature dealership app. With ``compiled`` the DataWindows are .dwo (like a .pbd)."""
    dws: dict[str, dict] = {
        "d_vehicle_maint": dict(
            columns=[dict(name="stock_no", dbname="vehicle.stock_no", type="char(10)", key=True),
                     dict(name="vin", dbname="vehicle.vin", type="char(17)"),
                     dict(name="regn_no", dbname="vehicle.regn_no", type="char(10)"),
                     dict(name="make", dbname="vehicle.make", type="char(30)"),
                     dict(name="model", dbname="vehicle.model", type="char(40)"),
                     dict(name="odometer", dbname="vehicle.odometer", type="long")],
            retrieve='PBSELECT( VERSION(400) TABLE(NAME="vehicle" ) COLUMN(NAME="vehicle.stock_no") COLUMN(NAME="vehicle.vin") '
                     'COLUMN(NAME="vehicle.regn_no") COLUMN(NAME="vehicle.make") COLUMN(NAME="vehicle.model") '
                     'COLUMN(NAME="vehicle.odometer") WHERE( EXP1 ="vehicle.regn_no" OP ="=" EXP2 =":as_regn" ) ) '
                     'ARG(NAME = "as_regn" TYPE = string)',
            texts={"vin": "VIN", "regn_no": "Regn No.", "make": "Make", "model": "Model", "odometer": "Odometer"},
            shown=["vin", "regn_no", "make", "model", "odometer"], args=[("as_regn", "string")], update="vehicle"),
        "d_deal_search": dict(
            columns=[dict(name="deal_no", dbname="deal.deal_no", type="long", key=True),
                     dict(name="stock_no", dbname="deal.stock_no", type="char(10)"),
                     dict(name="deal_date", dbname="deal.deal_date", type="datetime"),
                     dict(name="customer_no", dbname="deal.customer_no", type="long"),
                     dict(name="salesperson_code", dbname="deal.salesperson_code", type="char(6)"),
                     dict(name="sale_price", dbname="deal.sale_price", type="decimal(2)"),
                     dict(name="vehicle_vin", dbname="vehicle.vin", type="char(17)")],
            retrieve='PBSELECT( VERSION(400) TABLE(NAME="deal" ) TABLE(NAME="vehicle" ) COLUMN(NAME="deal.deal_no") '
                     'COLUMN(NAME="deal.stock_no") COLUMN(NAME="deal.deal_date") COLUMN(NAME="deal.customer_no") '
                     'COLUMN(NAME="deal.salesperson_code") COLUMN(NAME="deal.sale_price") COLUMN(NAME="vehicle.vin") '
                     'JOIN (LEFT="deal.stock_no" OP ="=" RIGHT="vehicle.stock_no" ) '
                     'WHERE( EXP1 ="vehicle.vin" OP ="=" EXP2 =":as_vin" ) ) ARG(NAME = "as_vin" TYPE = string)',
            texts={"deal_no": "Deal No", "deal_date": "Deal Date", "sale_price": "Sale Price", "vehicle_vin": "VIN"},
            shown=["deal_no", "deal_date", "sale_price", "vehicle_vin"], args=[("as_vin", "string")]),
        "d_deal_maint": dict(
            columns=[dict(name="deal_no", dbname="deal.deal_no", type="long", key=True),
                     dict(name="customer_no", dbname="deal.customer_no", type="long"),
                     dict(name="salesperson_code", dbname="deal.salesperson_code", type="char(6)"),
                     dict(name="finance_co", dbname="deal.finance_co", type="char(20)"),
                     dict(name="delivery_date", dbname="deal.delivery_date", type="datetime")],
            retrieve='PBSELECT( VERSION(400) TABLE(NAME="deal" ) COLUMN(NAME="deal.deal_no") COLUMN(NAME="deal.customer_no") '
                     'COLUMN(NAME="deal.salesperson_code") COLUMN(NAME="deal.finance_co") COLUMN(NAME="deal.delivery_date") '
                     'WHERE( EXP1 ="deal.deal_no" OP ="=" EXP2 =":al_deal" ) ) ARG(NAME = "al_deal" TYPE = number)',
            texts={"deal_no": "Deal No", "salesperson_code": "Sold By", "finance_co": "Finance Co.", "delivery_date": "Delivered"},
            shown=["deal_no", "salesperson_code", "finance_co", "delivery_date"], args=[("al_deal", "number")],
            update="deal", dddw={"salesperson_code": ("d_dddw_staff", "staff_name", "staff_code")}),
        "d_dddw_staff": dict(
            columns=[dict(name="staff_code", dbname="staff.staff_code", type="char(6)", key=True),
                     dict(name="staff_name", dbname="staff.staff_name", type="char(40)"),
                     dict(name="branch", dbname="staff.branch", type="long")],
            retrieve="SELECT staff.staff_code, staff.staff_name, staff.branch FROM staff WHERE staff.active = 'Y' ORDER BY staff.staff_name",
            texts={}, shown=["staff_name"]),
        "d_customer_list": dict(
            columns=[dict(name="customer_no", dbname="customer.customer_no", type="long", key=True),
                     dict(name="name", dbname="customer.name", type="char(60)"),
                     dict(name="phone", dbname="customer.phone", type="char(20)"),
                     dict(name="email", dbname="customer.email", type="char(80)")],
            retrieve="SELECT c.customer_no, c.name, c.phone, c.email FROM dbo.customer c ORDER BY c.name",
            texts={"name": "Customer", "phone": "Phone"}, shown=["name", "phone"]),
        "d_wshop_outstanding_ro": dict(
            columns=[dict(name="branch", dbname="repair_order.branch", type="long"),
                     dict(name="ro_number", dbname="repair_order.ro_number", type="long", key=True),
                     dict(name="date_required", dbname="repair_order.date_required", type="datetime"),
                     dict(name="est_hours", dbname="ro_line.est_hours", type="decimal(4)"),
                     dict(name="est_labour", dbname="ro_line.est_labour", type="decimal(2)"),
                     dict(name="job_code", dbname="ro_line.job_code", type="char(20)"),
                     dict(name="advisor_code", dbname="repair_order.advisor_code", type="char(6)"),
                     dict(name="stock_no", dbname="repair_order.stock_no", type="char(10)")],
            retrieve="SELECT ro.branch, ro.ro_number, ro.date_required, l.est_hours, l.est_labour, l.job_code, "
                     "ro.advisor_code, ro.stock_no FROM repair_order ro JOIN ro_line l ON l.ro_number = ro.ro_number "
                     "WHERE ro.stock_no = :as_stock AND ro.status = 'O'",
            texts={"branch": "Branch", "ro_number": "Ro Number", "date_required": "Date Required", "est_hours": "Est. Hours",
                   "est_labour": "Est. Labour", "job_code": "Job Code"},
            shown=["branch", "ro_number", "date_required", "est_hours", "est_labour", "job_code"],
            args=[("as_stock", "string")]),
        "d_ro_vehicle": dict(
            columns=[dict(name="ro_number", dbname="repair_order.ro_number", type="long"),
                     dict(name="regn_no", dbname="vehicle.regn_no", type="char(10)")],
            retrieve="SELECT repair_order.ro_number, vehicle.regn_no FROM repair_order, vehicle "
                     "WHERE repair_order.stock_no *= vehicle.stock_no",
            texts={"regn_no": "Regn No."}, shown=["ro_number", "regn_no"]),
    }
    objects: dict[str, bytes | str] = {}
    for name, spec in dws.items():
        syntax = _syntax(spec["columns"], spec["retrieve"], spec["texts"], spec["shown"], spec.get("args", ()),
                         spec.get("update", ""), dddw=spec.get("dddw"))
        if compiled:
            strings = compiled_strings([(c["name"], c["dbname"]) for c in spec["columns"]], spec["retrieve"],
                                       [a for a, _ in spec.get("args", ())], spec["texts"], spec["shown"],
                                       extra=[d[0] for d in (spec.get("dddw") or {}).values()])
            objects[f"{name}.dwo"] = build_dwo(strings)
        else:
            objects[f"{name}.srd"] = syntax
    objects["w_vehicle_maint.win"] = b"\x00" * 300 + b"compiled window" + b"\x00" * 100
    objects["n_cst_appmanager.sru"] = "forward\nglobal type n_cst_appmanager from nonvisualobject\nend type\n"
    return objects


DEMO_INI = """; Demo settings file in the style of a PowerBuilder application. Not real.
[Database]
DBMS=MSS
ServerName=DEALER-SQL01\\UNITS
Database=units_live
LogId=units_app
LogPassword=SuperSecret123
AutoCommit=False
DBParm=AppName='Units',Host='WS01'

[Reporting]
ConnectString=Provider=MSOLEDBSQL;Data Source=DEALER-SQL02;Initial Catalog=units_reporting;User ID=report_ro;Password=AlsoSecret!;
"""


def write_demo(folder: str | Path) -> list[Path]:
    """Write a demo 'install folder' (compiled .pbd + source .pbl + .psr + .ini)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    compiled = demo_objects(compiled=True)
    source = demo_objects(compiled=False)
    out = []
    p = folder / "dealer_sales.pbd"
    p.write_bytes(build_library({k: v for k, v in compiled.items() if "deal" in k or "staff" in k or k.endswith(".win")},
                                unicode=True, per_node=3))
    out.append(p)
    p = folder / "dealer_workshop.pbd"
    p.write_bytes(build_library({k: v for k, v in compiled.items() if "deal" not in k and "staff" not in k}, unicode=False))
    out.append(p)
    p = folder / "dealer_customer_src.pbl"
    p.write_bytes(build_library({"d_customer_list.srd": source["d_customer_list.srd"],
                                 "d_customer_list.dwo": compiled["d_customer_list.dwo"]},
                                comments={"d_customer_list.srd": "Customer list for marketing"}))
    out.append(p)
    p = folder / "sold_vehicles.psr"
    dwo = compiled["d_deal_search.dwo"]
    p.write_bytes(build_psr_binary(dwo if isinstance(dwo, bytes) else dwo.encode(), ["JTDBR32E720012345", "Alex Smith", "Approved"]))
    out.append(p)
    p = folder / "units.ini"
    p.write_text(DEMO_INI, encoding="utf-8")
    out.append(p)
    return out
