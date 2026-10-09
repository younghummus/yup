"""Write .xlsx workbooks with nothing but the standard library.

Each sheet gets a bold, frozen header row, an AutoFilter (so Excel's filter dropdowns are
ready to use), and sensible column widths. Values are written as text or numbers.
"""

from __future__ import annotations

import re
import zipfile
from xml.sax.saxutils import escape

_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v, style: int = 0) -> str:
    st = f' s="{style}"' if style else ""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="inlineStr"{st}><is><t>{"yes" if v else "no"}</t></is></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    text = _BAD.sub("", str(v))[:32767]
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _sheet_xml(rows: list[list]) -> str:
    ncols = max((len(r) for r in rows), default=1)
    widths = [10] * ncols
    for r in rows[:2000]:
        for i, v in enumerate(r):
            ln = max((len(x) for x in str(v if v is not None else "").splitlines()), default=0)
            widths[i] = min(max(widths[i], ln + 2), 60)
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    body = []
    for ri, r in enumerate(rows):
        cells = "".join(_cell(f"{_col(ci)}{ri + 1}", v, 1 if ri == 0 else 0) for ci, v in enumerate(r))
        body.append(f'<row r="{ri + 1}">{cells}</row>')
    last = f"{_col(ncols - 1)}{max(len(rows), 1)}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        f"<cols>{cols}</cols><sheetData>{''.join(body)}</sheetData>"
        + (f'<autoFilter ref="A1:{last}"/>' if _filtered(rows) else "")
        + "</worksheet>"
    )


def _width(rows: list[list]) -> int:
    return max((len(r) for r in rows), default=1) or 1


def _filtered(rows: list[list]) -> bool:
    return len(rows) > 1 and _width(rows) > 1


def _defined_names(names: list[str], sheets: dict[str, list[list]]) -> str:
    items = [
        f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
        f"'{escape(n.replace(chr(39), chr(39) * 2))}'!$A$1:${_col(_width(sheets[k]) - 1)}${len(sheets[k])}</definedName>"
        for i, (n, k) in enumerate(zip(names, sheets)) if _filtered(sheets[k])
    ]
    return f"<definedNames>{''.join(items)}</definedNames>" if items else ""


def _safe_name(name: str, used: set[str]) -> str:
    n = re.sub(r"[\[\]:*?/\\]", "_", name)[:31] or "Sheet"
    base, i = n, 2
    while n.lower() in used:
        suffix = f" ({i})"
        n = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(n.lower())
    return n


def write(path, sheets: dict[str, list[list]]) -> None:
    """``sheets`` maps sheet name -> rows (first row = header)."""
    used: set[str] = set()
    names = [_safe_name(n, used) for n in sheets]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(names)))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
                   + "</sheets>" + _defined_names(names, sheets) + "</workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                             for i in range(len(names)))
                   + f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
                   '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/><bgColor indexed="64"/></patternFill></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                   "</styleSheet>")
        for i, key in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet_xml(sheets[key]))
