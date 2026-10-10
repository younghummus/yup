"""Standard MIDI File export of the arrangement (one track per part, GM drums on ch 10).

Drag the .mid into Ableton, put Serum on 'chords' and 'chops', an 808 on 'bass', and you
have the remix as a real project to keep producing.
"""
from __future__ import annotations

import struct
from pathlib import Path

PPQ = 480
TRACK_ORDER = ("chords", "chops", "bass", "keys", "pluck", "drums")
CHANNELS = {"chords": 0, "chops": 1, "bass": 2, "keys": 3, "pluck": 4, "drums": 9}
PROGRAMS = {"chords": 81, "chops": 85, "bass": 38, "keys": 4, "pluck": 45}  # GM: saw lead, voice, synth bass, EP, pizz


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def _track(events: list[tuple[int, bytes]]) -> bytes:
    events = sorted(events, key=lambda e: (e[0], e[1][0] & 0xF0 == 0x90))  # offs before ons
    body, now = b"", 0
    for tick, data in events:
        body += _vlq(tick - now) + data
        now = tick
    body += b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + body


def _meta_name(name: str) -> bytes:
    raw = name.encode()
    return b"\xff\x03" + _vlq(len(raw)) + raw


def write_midi(path: str | Path, notes, bpm: float, title: str = "") -> Path:
    """`notes`: iterable with .track, .beat, .beats, .midi, .vel (see render.Note)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tempo = int(round(60_000_000 / bpm))
    conductor = [(0, _meta_name(title or "Remix")),
                 (0, b"\xff\x51\x03" + tempo.to_bytes(3, "big")),
                 (0, b"\xff\x58\x04\x04\x02\x18\x08")]
    tracks = [_track(conductor)]
    by_track: dict[str, list] = {}
    for n in notes:
        by_track.setdefault(n.track, []).append(n)
    names = [t for t in TRACK_ORDER if t in by_track] + sorted(set(by_track) - set(TRACK_ORDER))
    for name in names:
        ch = CHANNELS.get(name, 5)
        ev: list[tuple[int, bytes]] = [(0, _meta_name(name))]
        if name in PROGRAMS:
            ev.append((0, bytes([0xC0 | ch, PROGRAMS[name]])))
        for n in by_track[name]:
            on = int(round(n.beat * PPQ))
            off = max(on + 1, int(round((n.beat + n.beats) * PPQ)) - 1)
            vel = max(1, min(127, int(round(n.vel * 127))))
            key = max(0, min(127, int(n.midi)))
            ev.append((on, bytes([0x90 | ch, key, vel])))
            ev.append((off, bytes([0x80 | ch, key, 0])))
        tracks.append(_track(ev))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ)
    path.write_bytes(header + b"".join(tracks))
    return path


def read_midi_summary(path: str | Path) -> dict:
    """Minimal SMF reader used by the tests: tracks, names, note-on counts, tempo."""
    data = Path(path).read_bytes()
    assert data[:4] == b"MThd"
    _, fmt, ntrk, ppq = struct.unpack(">IHHH", data[4:14])
    pos, out = 14, {"format": fmt, "ppq": ppq, "tracks": [], "tempo": None}
    for _ in range(ntrk):
        assert data[pos:pos + 4] == b"MTrk"
        (ln,) = struct.unpack(">I", data[pos + 4:pos + 8])
        trk, pos = data[pos + 8:pos + 8 + ln], pos + 8 + ln
        i, name, ons, status = 0, "", 0, 0
        while i < len(trk):
            while trk[i] & 0x80:  # delta-time VLQ
                i += 1
            i += 1
            b = trk[i]
            if b == 0xFF:
                typ, i = trk[i + 1], i + 2
                ln2 = 0
                while trk[i] & 0x80:
                    ln2 = (ln2 << 7) | (trk[i] & 0x7F)
                    i += 1
                ln2 = (ln2 << 7) | trk[i]
                i += 1
                payload = trk[i:i + ln2]
                if typ == 0x03:
                    name = payload.decode()
                elif typ == 0x51:
                    out["tempo"] = 60_000_000 / int.from_bytes(payload, "big")
                i += ln2
                continue
            if b & 0x80:
                status, i = b, i + 1
            kind = status & 0xF0
            if kind in (0xC0, 0xD0):
                i += 1
            else:
                if kind == 0x90 and trk[i + 1] > 0:
                    ons += 1
                i += 2
        out["tracks"].append({"name": name, "notes": ons})
    return out
