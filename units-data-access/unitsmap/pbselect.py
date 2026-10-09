"""Turn PowerBuilder's ``PBSELECT(...)`` notation into ordinary SQL.

DataWindows painted with PowerBuilder's graphical SQL painter store their query as PBSELECT,
a PowerBuilder-only notation, for example::

    PBSELECT( VERSION(400) TABLE(NAME="vehicle") TABLE(NAME="deal")
      COLUMN(NAME="vehicle.vin") COLUMN(NAME="deal.salesperson")
      JOIN(LEFT="vehicle.stock_no" OP="=" RIGHT="deal.stock_no")
      WHERE(EXP1="vehicle.vin" OP="=" EXP2=":as_vin")
      ORDER(NAME="deal.deal_date" ASC=no) ARG(NAME="as_vin" TYPE=string))

which becomes::

    SELECT vehicle.vin, deal.salesperson
    FROM vehicle
    JOIN deal ON vehicle.stock_no = deal.stock_no
    WHERE vehicle.vin = :as_vin
    ORDER BY deal.deal_date DESC

The database never sees PBSELECT: PowerBuilder converts it like this at run time. The SQL
this module writes can be pasted into Excel Power Query, SSMS or any SQL tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class PBSelectError(ValueError):
    pass


@dataclass
class Call:
    """``NAME( key=value ... nested(...) )``: one PBSELECT clause."""

    name: str
    attrs: dict[str, object] = field(default_factory=dict)
    children: list["Call"] = field(default_factory=list)

    def get(self, key: str, default: str = "") -> str:
        v = self.attrs.get(key.upper(), default)
        return v if isinstance(v, str) else default

    def all(self, name: str) -> list["Call"]:
        return [c for c in self.children if c.name == name.upper()]


@dataclass
class Join:
    left: str
    op: str
    right: str
    kind: str = "JOIN"  # JOIN, LEFT OUTER JOIN, RIGHT OUTER JOIN, FULL OUTER JOIN


@dataclass
class Select:
    tables: list[tuple[str, str]] = field(default_factory=list)  # (name, alias)
    columns: list[str] = field(default_factory=list)
    computes: list[str] = field(default_factory=list)
    distinct: bool = False
    joins: list[Join] = field(default_factory=list)
    where: list[tuple[str, str, str, str]] = field(default_factory=list)  # exp1, op, exp2, logic
    group: list[str] = field(default_factory=list)
    having: list[tuple[str, str, str, str]] = field(default_factory=list)
    order: list[tuple[str, bool]] = field(default_factory=list)
    arguments: list[tuple[str, str]] = field(default_factory=list)
    unions: list[tuple[str, "Select"]] = field(default_factory=list)


# ----------------------------------------------------------------------------- lexer
_TOKEN = re.compile(
    r"""\s*(?:
        (?P<str>"(?:[^"~]|~.)*")      # "quoted", ~ escapes
      | (?P<sq>'(?:[^']|'')*')        # 'quoted'
      | (?P<punct>[()=,])
      | (?P<word>[^\s()=,"']+)
    )""",
    re.VERBOSE | re.DOTALL,
)

_TILDE = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "'": "'", "~": "~"}


def unescape(s: str) -> str:
    """Undo PowerBuilder ``~`` escaping (``~"`` -> ``"``, ``~t`` -> tab ...)."""
    return re.sub(r"~(.)", lambda m: _TILDE.get(m.group(1), m.group(1)), s, flags=re.DOTALL)


def _lex(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip() == "":
                break
            raise PBSelectError(f"unexpected character at {pos}: {text[pos:pos + 20]!r}")
        pos = m.end()
        if m.group("str") is not None:
            out.append(("str", unescape(m.group("str")[1:-1])))
        elif m.group("sq") is not None:
            out.append(("str", m.group("sq")[1:-1].replace("''", "'")))
        elif m.group("punct") is not None:
            out.append((m.group("punct"), m.group("punct")))
        elif m.group("word") is not None:
            out.append(("word", m.group("word")))
    return out


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.t = tokens
        self.i = 0

    def peek(self, k: int = 0) -> tuple[str, str]:
        j = self.i + k
        return self.t[j] if j < len(self.t) else ("eof", "")

    def take(self, kind: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if kind and tok[0] != kind:
            raise PBSelectError(f"expected {kind}, got {tok[1]!r}")
        self.i += 1
        return tok

    def call(self) -> Call:
        name = self.take("word")[1].upper()
        self.take("(")
        node = Call(name)
        while True:
            kind, val = self.peek()
            if kind == ")":
                self.take()
                return node
            if kind == "eof":  # PowerBuilder tolerates a missing final ")"; so do we
                return node
            if kind == ",":
                self.take()
                continue
            if kind == "word" and self.peek(1)[0] == "=":
                key = self.take()[1].upper()
                self.take("=")
                vk, vv = self.peek()
                if vk == "word" and self.peek(1)[0] == "(":
                    node.attrs[key] = self.call()
                elif vk in ("str", "word"):
                    self.take()
                    node.attrs[key] = vv
                elif vk == "=":  # OP = = (unquoted operator, rare)
                    self.take()
                    node.attrs[key] = "="
                else:
                    raise PBSelectError(f"bad value for {key}: {vv!r}")
            elif kind == "word" and self.peek(1)[0] == "(":
                node.children.append(self.call())
            else:  # stray token: keep going rather than fail on PB oddities
                self.take()


def parse(text: str) -> Call:
    """Parse PBSELECT text (already un-tilde-escaped or not) into a Call tree."""
    s = text.strip()
    start = s.upper().find("PBSELECT")
    if start < 0:
        raise PBSelectError("not a PBSELECT statement")
    p = _Parser(_lex(s[start:]))
    return p.call()


def _join_kind(left: str, right: str, o1: str, o2: str) -> str:
    outer = {x.lower() for x in (o1, o2) if x}
    lo, ro = left.lower() in outer, right.lower() in outer
    if lo and ro:
        return "FULL OUTER JOIN"
    if lo:
        return "LEFT OUTER JOIN"
    if ro:
        return "RIGHT OUTER JOIN"
    return "JOIN"


def to_select(call: Call) -> Select:
    sel = Select()
    for c in call.children:
        n = c.name
        if n == "DISTINCT":
            sel.distinct = True
        elif n == "TABLE":
            sel.tables.append((c.get("NAME"), c.get("ALIAS")))
        elif n == "COLUMN":
            name = c.get("NAME")
            alias = c.get("ALIAS")
            sel.columns.append(f"{name} AS {alias}" if alias and alias != name else name)
        elif n == "COMPUTE":
            name = c.get("NAME")
            alias = c.get("ALIAS")
            sel.computes.append(f"{name} AS {alias}" if alias else name)
        elif n == "JOIN":
            left, right = c.get("LEFT"), c.get("RIGHT")
            sel.joins.append(Join(left, c.get("OP", "=") or "=", right,
                                  _join_kind(left, right, c.get("OUTER1"), c.get("OUTER2"))))
        elif n in ("WHERE", "HAVING"):
            exp2 = c.get("EXP2")
            nest = c.attrs.get("NEST")
            if isinstance(nest, Call):
                exp2 = "(" + render(to_select(nest), indent="    ") + ")"
            row = (c.get("EXP1"), c.get("OP"), exp2, c.get("LOGIC"))
            (sel.where if n == "WHERE" else sel.having).append(row)
        elif n == "GROUP":
            sel.group.append(c.get("NAME"))
        elif n == "ORDER":
            sel.order.append((c.get("NAME"), c.get("ASC", "yes").lower() not in ("no", "n", "false", "0")))
        elif n == "ARG":
            sel.arguments.append((c.get("NAME"), c.get("TYPE")))
        elif n == "UNION" or n == "UNIONALL" or n == "UNION_ALL":
            inner = c.all("PBSELECT")
            if inner:
                sel.unions.append(("UNION ALL" if "ALL" in n else "UNION", to_select(inner[0])))
        elif n == "PBSELECT":  # some versions nest UNION members directly
            sel.unions.append(("UNION", to_select(c)))
    return sel


def _qualify(t: tuple[str, str]) -> str:
    name, alias = t
    return f"{name} {alias}" if alias and alias != name else name


def _owner(expr: str) -> str:
    """Table (or alias) that a ``table.column`` expression belongs to, lower-cased."""
    parts = expr.strip().strip("()").split(".")
    return parts[-2].strip().lower() if len(parts) >= 2 else ""


def _conditions(rows: list[tuple[str, str, str, str]]) -> str:
    out = []
    for i, (e1, op, e2, logic) in enumerate(rows):
        out.append(f"{e1} {op} {e2}".strip())
        if logic and i < len(rows) - 1:
            out.append(logic.upper())
    return " ".join(out)


def render(sel: Select, indent: str = "") -> str:
    where = list(sel.where)
    cols = sel.columns + sel.computes or ["*"]
    lines = [("SELECT DISTINCT " if sel.distinct else "SELECT ") + (",\n" + indent + "       ").join(cols)]

    # FROM + JOINs: walk the join list attaching each table once, ANSI style.
    names = {(alias or name).lower(): (name, alias) for name, alias in sel.tables}
    for name, alias in sel.tables:
        names.setdefault(name.lower(), (name, alias))
    placed: list[str] = []
    pending = list(sel.joins)
    from_lines: list[str] = []
    if sel.tables:
        first = sel.tables[0]
        placed.append((first[1] or first[0]).lower())
        from_lines.append("FROM " + _qualify(first))
    progress = True
    while pending and progress:
        progress = False
        for j in list(pending):
            lo, ro = _owner(j.left), _owner(j.right)
            l_in, r_in = lo in placed or lo == "", ro in placed or ro == ""
            if l_in and r_in:
                # Both sides already present: extra condition on the latest join, or WHERE.
                if len(from_lines) > 1:
                    from_lines[-1] += f" AND {j.left} {j.op} {j.right}"
                else:
                    where.insert(0, (j.left, j.op, j.right, "and"))
                pending.remove(j)
                progress = True
            elif l_in or r_in:
                new = ro if l_in else lo
                kind = j.kind
                if not l_in:  # we are attaching the left-hand table: mirror the outer side
                    kind = {"LEFT OUTER JOIN": "RIGHT OUTER JOIN", "RIGHT OUTER JOIN": "LEFT OUTER JOIN"}.get(kind, kind)
                table = names.get(new, (new, ""))
                from_lines.append(f"{kind} {_qualify(table)} ON {j.left} {j.op} {j.right}")
                placed.append(new)
                pending.remove(j)
                progress = True
    for j in pending:  # joins between tables we could not place (no qualifier): treat as filters
        where.insert(0, (j.left, j.op, j.right, "and"))
    for name, alias in sel.tables[1:]:
        if (alias or name).lower() not in placed:
            from_lines.append("CROSS JOIN " + _qualify((name, alias)))
            placed.append((alias or name).lower())
    lines += from_lines

    if where:
        # Make sure every WHERE row except the last has a connective.
        rows = [(a, b, c, d or ("and" if i < len(where) - 1 else "")) for i, (a, b, c, d) in enumerate(where)]
        lines.append("WHERE " + _conditions(rows))
    if sel.group:
        lines.append("GROUP BY " + ", ".join(sel.group))
    if sel.having:
        lines.append("HAVING " + _conditions(sel.having))
    sql = ("\n" + indent).join(lines)
    for kind, other in sel.unions:
        sql += f"\n{indent}{kind}\n{indent}" + render(other, indent)
    if sel.order:
        sql += f"\n{indent}ORDER BY " + ", ".join(f"{n} {'ASC' if asc else 'DESC'}" for n, asc in sel.order)
    return sql


def pbselect_to_sql(text: str) -> str:
    """Convenience: PBSELECT text in, SQL text out."""
    return render(to_select(parse(text)))


def is_pbselect(text: str) -> bool:
    return text.lstrip().upper().startswith("PBSELECT")
