"""Read PowerBuilder libraries: .pbl, .pbd, and the libraries embedded in PB-built .exe/.dll files.

A PowerBuilder library is a little filesystem of 512-byte blocks:

    HDR*  library header (512 bytes; 1024 in Unicode libraries, PB 10 and later)
    FRE*  free-block bitmap
    NOD*  directory node (3072 bytes), holding ENT* entries, linked as a tree
    DAT*  data block: 4-byte next-block offset, 2-byte length, up to 502 bytes of data

Each ENT* entry names one object (``d_vehicle_list.dwo``, ``w_main.win``, ...) and points
at the first DAT* block of a forward-linked chain that holds its bytes. A PB-built EXE or
DLL carries the same structure at its end, located through a ``TRL*`` trailer block.

All integers are little-endian. Offsets are absolute file offsets for .pbl/.pbd files; for
libraries embedded in an EXE/DLL they may be relative to the embedded header, so both are tried.

Format notes: Arnd Schmidt's "PBL File Format" write-up (PB 5 to 11.5), checked against
real ANSI (PB 9) and Unicode (PB 2019+) libraries. See docs/FILE-FORMATS.md.
"""

from __future__ import annotations

import datetime as _dt
import struct
from dataclasses import dataclass, field
from pathlib import Path

BLOCK = 512
NODE_SIZE = 3072
ENTRY_HEADER_ANSI = 24
ENTRY_HEADER_UNICODE = 28
MAX_OBJECT_SIZE = 64 * 1024 * 1024

#: Entry suffixes that hold exported source text rather than compiled objects.
SOURCE_SUFFIXES = (".srd", ".srw", ".sru", ".srf", ".srm", ".srs", ".srx", ".srj", ".srp", ".srq", ".sra", ".srq")


class LibraryError(ValueError):
    """The file is not a readable PowerBuilder library."""


@dataclass
class Entry:
    """One object stored in a library."""

    name: str
    first_block: int
    size: int
    timestamp: int
    comment_len: int
    version: str = ""
    library: str = ""

    @property
    def kind(self) -> str:
        """Lower-case suffix without the dot: ``dwo``, ``srd``, ``win``..."""
        return self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""

    @property
    def stem(self) -> str:
        return self.name.rsplit(".", 1)[0] if "." in self.name else self.name

    @property
    def is_source(self) -> bool:
        return self.name.lower().endswith(SOURCE_SUFFIXES)

    @property
    def modified(self) -> _dt.datetime | None:
        if not self.timestamp:
            return None
        try:
            return _dt.datetime.fromtimestamp(self.timestamp, tz=_dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None


@dataclass
class Library:
    """A parsed PowerBuilder library held in memory."""

    data: bytes
    path: str = ""
    encoding: str = "cp1252"
    base: int = 0
    unicode: bool = False
    version: str = ""
    comment: str = ""
    entries: list[Entry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # ----------------------------------------------------------------- loading
    @classmethod
    def open(cls, path: str | Path, encoding: str = "cp1252") -> "Library":
        p = Path(path)
        return cls.from_bytes(p.read_bytes(), str(p), encoding)

    @classmethod
    def from_bytes(cls, data: bytes, path: str = "", encoding: str = "cp1252") -> "Library":
        lib = cls(data=data, path=path, encoding=encoding)
        lib.base = _find_header(data)
        lib._read_header()
        lib._read_directory()
        return lib

    def _read_header(self) -> None:
        d, b = self.data, self.base
        self.unicode = d[b + 4 : b + 6] == b"P\x00"
        if self.unicode:
            self.version = _clean(d[b + 32 : b + 40].decode("utf-16-le", "replace"))
            self.comment = _clean(d[b + 46 : b + 558].decode("utf-16-le", "replace"))
        else:
            self.version = _clean(d[b + 18 : b + 22].decode("ascii", "replace"))
            self.comment = _clean(d[b + 28 : b + 284].decode(self.encoding, "replace"))

    def _abs(self, offset: int, magic: bytes) -> int | None:
        """Resolve a stored offset to an absolute one whose block starts with ``magic``."""
        for cand in (offset, self.base + offset) if self.base else (offset,):
            if 0 < cand <= len(self.data) - 4 and self.data[cand : cand + 4] == magic:
                return cand
        return None

    def _read_directory(self) -> None:
        start = self._first_node()
        if start is None:
            raise LibraryError(f"{self.path or 'library'}: no directory (NOD*) block found")
        seen: set[int] = set()
        todo = [start]
        names: dict[str, Entry] = {}
        while todo:
            node = todo.pop()
            if node in seen:
                continue
            seen.add(node)
            try:
                left, parent, right = struct.unpack_from("<III", self.data, node + 4)
                for e in self._node_entries(node):
                    names.setdefault(e.name, e)
            except (struct.error, LibraryError) as exc:
                self.warnings.append(f"directory node at {node}: {exc}")
                continue
            for link in (left, parent, right):
                if link:
                    resolved = self._abs(link, b"NOD*")
                    if resolved is not None and resolved not in seen:
                        todo.append(resolved)
        self.entries = sorted(names.values(), key=lambda e: e.name.lower())

    def _first_node(self) -> int | None:
        pos = self.base + BLOCK
        end = min(len(self.data), self.base + 64 * BLOCK)
        while pos < end:
            if self.data[pos : pos + 4] == b"NOD*":
                return pos
            pos += BLOCK
        return None

    def _node_entries(self, node: int) -> list[Entry]:
        d = self.data
        (count,) = struct.unpack_from("<H", d, node + 20)
        p, limit = node + 32, node + NODE_SIZE
        out: list[Entry] = []
        for _ in range(count):
            if d[p : p + 4] != b"ENT*":
                raise LibraryError(f"expected ENT* at {p}")
            if self.unicode:
                version = d[p + 4 : p + 12].decode("utf-16-le", "replace")
                first, size, ts, clen, nlen = struct.unpack_from("<IIIHH", d, p + 12)
                raw = d[p + ENTRY_HEADER_UNICODE : p + ENTRY_HEADER_UNICODE + nlen]
                name = raw.decode("utf-16-le", "replace")
                p += ENTRY_HEADER_UNICODE + nlen
            else:
                version = d[p + 4 : p + 8].decode("ascii", "replace")
                first, size, ts, clen, nlen = struct.unpack_from("<IIIHH", d, p + 8)
                raw = d[p + ENTRY_HEADER_ANSI : p + ENTRY_HEADER_ANSI + nlen]
                name = raw.decode(self.encoding, "replace")
                p += ENTRY_HEADER_ANSI + nlen
            if p > limit:
                raise LibraryError("entry runs past the end of its directory node")
            out.append(Entry(_clean(name), first, size, ts, clen, _clean(version), self.path))
        return out

    # ----------------------------------------------------------------- reading
    def read(self, entry: Entry | str) -> bytes:
        """Return an object's raw bytes (comment included), following its DAT* chain."""
        if isinstance(entry, str):
            entry = self.get(entry)
        out = bytearray()
        block = self._abs(entry.first_block, b"DAT*") if entry.first_block else None
        if entry.first_block and block is None:
            raise LibraryError(f"{entry.name}: data block {entry.first_block} is not a DAT* block")
        seen: set[int] = set()
        cap = min(entry.size or MAX_OBJECT_SIZE, MAX_OBJECT_SIZE)
        while block is not None and len(out) < cap:
            if block in seen:
                raise LibraryError(f"{entry.name}: data chain loops at {block}")
            seen.add(block)
            nxt, length = struct.unpack_from("<IH", self.data, block + 4)
            out += self.data[block + 10 : block + 10 + min(length, BLOCK - 10)]
            block = self._abs(nxt, b"DAT*") if nxt else None
        return bytes(out[:cap]) if entry.size else bytes(out)

    def comment_of(self, entry: Entry) -> str:
        raw = self.read(entry)
        if self.unicode:
            return raw[: entry.comment_len * 2].decode("utf-16-le", "replace")
        return raw[: entry.comment_len].decode(self.encoding, "replace")

    def body(self, entry: Entry | str) -> bytes:
        """Object bytes with the leading comment removed."""
        if isinstance(entry, str):
            entry = self.get(entry)
        raw = self.read(entry)
        skip = entry.comment_len * (2 if self.unicode else 1)
        return raw[skip:] if skip <= len(raw) else raw

    def text(self, entry: Entry | str) -> str:
        """Decode a source entry (``.srd`` and friends) to text."""
        body = self.body(entry)
        if self.unicode:
            return body.decode("utf-16-le", "replace").rstrip("\x00")
        return body.decode(self.encoding, "replace").rstrip("\x00")

    def get(self, name: str) -> Entry:
        for e in self.entries:
            if e.name.lower() == name.lower():
                return e
        raise KeyError(name)

    def datawindows(self) -> list[Entry]:
        """DataWindow entries: source ``.srd`` when present, else compiled ``.dwo``."""
        by_stem: dict[str, Entry] = {}
        for e in self.entries:
            if e.kind not in ("srd", "dwo"):
                continue
            key = e.stem.lower()
            prev = by_stem.get(key)
            if prev is None or (e.kind == "srd" and prev.kind == "dwo"):
                by_stem[key] = e
        return sorted(by_stem.values(), key=lambda e: e.name.lower())


def _find_header(data: bytes) -> int:
    if data[:4] == b"HDR*":
        return 0
    # PB-built EXE/DLL: a TRL* block in the last 512 bytes points at the HDR*.
    tail = data[-BLOCK:] if len(data) >= BLOCK else data
    t = tail.rfind(b"TRL*")
    if t >= 0 and t + 8 <= len(tail):
        (off,) = struct.unpack_from("<I", tail, t + 4)
        if data[off : off + 4] == b"HDR*":
            return off
    # Last resort: any HDR*PowerBuilder signature on a block boundary.
    for sig in (b"HDR*PowerBuilder", b"HDR*P\x00o\x00w\x00e\x00r\x00B\x00"):
        i = data.find(sig)
        if i >= 0:
            return i
    raise LibraryError("not a PowerBuilder library (no HDR* header found)")


def _clean(s: str) -> str:
    return s.split("\x00", 1)[0].strip()


def is_library(path: str | Path) -> bool:
    """Cheap check: does this file contain a PowerBuilder library?"""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
            if head[:4] == b"HDR*":
                return True
            f.seek(0, 2)
            size = f.tell()
            if size < BLOCK:
                return False
            f.seek(size - BLOCK)
            return b"TRL*" in f.read(BLOCK)
    except OSError:
        return False
