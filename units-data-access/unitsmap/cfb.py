"""Minimal reader for Microsoft Compound File Binary (OLE2 "DocFile") containers.

Some PowerBuilder saved reports (.psr) are compound files holding streams such as
``object``, ``source`` and ``data``. This reader lists and extracts streams; it follows
[MS-CFB] (version 3 and 4 files, regular and mini streams) and needs no third-party package.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREESECT, ENDOFCHAIN, FATSECT, DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF


class CFBError(ValueError):
    pass


@dataclass
class DirEntry:
    sid: int
    name: str
    type: int  # 1 storage, 2 stream, 5 root
    left: int
    right: int
    child: int
    start: int
    size: int
    path: str = ""


class CompoundFile:
    def __init__(self, data: bytes):
        if data[:8] != SIGNATURE:
            raise CFBError("not a compound file")
        self.data = data
        (self.major,) = struct.unpack_from("<H", data, 0x1A)
        (shift,) = struct.unpack_from("<H", data, 0x1E)
        (mini_shift,) = struct.unpack_from("<H", data, 0x20)
        self.sector_size = 1 << shift
        self.mini_size = 1 << mini_shift
        n_fat, first_dir = struct.unpack_from("<II", data, 0x2C)
        self.cutoff, first_minifat, n_minifat, first_difat, n_difat = struct.unpack_from("<IIIII", data, 0x38)
        if self.sector_size not in (512, 4096):
            raise CFBError(f"unsupported sector size {self.sector_size}")

        difat = [x for x in struct.unpack_from("<109I", data, 0x4C)]
        sect, guard = first_difat, 0
        while sect not in (ENDOFCHAIN, FREESECT) and guard < n_difat + 1:
            vals = struct.unpack_from(f"<{self.sector_size // 4}I", data, self._off(sect))
            difat.extend(vals[:-1])
            sect = vals[-1]
            guard += 1
        fat_sectors = [s for s in difat if s not in (FREESECT, ENDOFCHAIN)][:n_fat]
        self.fat: list[int] = []
        for s in fat_sectors:
            self.fat.extend(struct.unpack_from(f"<{self.sector_size // 4}I", data, self._off(s)))

        dir_bytes = self._chain(first_dir)
        self.entries: list[DirEntry] = []
        for sid in range(len(dir_bytes) // 128):
            raw = dir_bytes[sid * 128 : sid * 128 + 128]
            (name_len,) = struct.unpack_from("<H", raw, 64)
            name = raw[: max(0, name_len - 2)].decode("utf-16-le", "replace")
            etype = raw[66]
            left, right, child = struct.unpack_from("<III", raw, 68)
            (start,) = struct.unpack_from("<I", raw, 116)
            (size,) = struct.unpack_from("<Q", raw, 120)
            if self.major == 3:
                size &= 0xFFFFFFFF
            self.entries.append(DirEntry(sid, name, etype, left, right, child, start, size))
        if not self.entries or self.entries[0].type != 5:
            raise CFBError("missing root entry")

        root = self.entries[0]
        self.ministream = self._chain(root.start)[: root.size] if root.start != ENDOFCHAIN else b""
        self.minifat: list[int] = []
        if n_minifat and first_minifat != ENDOFCHAIN:
            mf = self._chain(first_minifat)
            self.minifat = list(struct.unpack_from(f"<{len(mf) // 4}I", mf))
        self._assign_paths(root.child, "")

    def _off(self, sect: int) -> int:
        return (sect + 1) * self.sector_size

    def _chain(self, start: int) -> bytes:
        out = bytearray()
        sect, seen = start, set()
        while sect not in (ENDOFCHAIN, FREESECT) and sect < len(self.fat):
            if sect in seen:
                raise CFBError("sector chain loops")
            seen.add(sect)
            off = self._off(sect)
            out += self.data[off : off + self.sector_size]
            sect = self.fat[sect]
        return bytes(out)

    def _mini_chain(self, start: int, size: int) -> bytes:
        out = bytearray()
        sect, seen = start, set()
        while sect not in (ENDOFCHAIN, FREESECT) and sect < len(self.minifat) and len(out) < size:
            if sect in seen:
                raise CFBError("mini chain loops")
            seen.add(sect)
            off = sect * self.mini_size
            out += self.ministream[off : off + self.mini_size]
            sect = self.minifat[sect]
        return bytes(out[:size])

    def _assign_paths(self, sid: int, prefix: str) -> None:
        stack = [(sid, prefix)]
        visited: set[int] = set()
        while stack:
            s, pre = stack.pop()
            if s == NOSTREAM or s >= len(self.entries) or s in visited:
                continue
            visited.add(s)
            e = self.entries[s]
            e.path = f"{pre}{e.name}"
            stack.append((e.left, pre))
            stack.append((e.right, pre))
            if e.type == 1:
                stack.append((e.child, e.path + "/"))

    def streams(self) -> list[DirEntry]:
        return [e for e in self.entries if e.type == 2 and e.path]

    def read(self, entry: DirEntry | str) -> bytes:
        if isinstance(entry, str):
            match = [e for e in self.streams() if e.path.lower() == entry.lower() or e.name.lower() == entry.lower()]
            if not match:
                raise KeyError(entry)
            entry = match[0]
        if entry.size < self.cutoff:
            return self._mini_chain(entry.start, entry.size)
        return self._chain(entry.start)[: entry.size]


def is_compound(data: bytes) -> bool:
    return data[:8] == SIGNATURE
