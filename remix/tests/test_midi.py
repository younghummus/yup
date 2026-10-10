from radcat.midi import _vlq, read_midi_summary, write_midi
from radcat.render import Note


def test_vlq_encoding():
    assert _vlq(0) == b"\x00"
    assert _vlq(0x7F) == b"\x7f"
    assert _vlq(0x80) == b"\x81\x00"
    assert _vlq(0x3FFF) == b"\xff\x7f"
    assert _vlq(0x200000) == b"\x81\x80\x80\x00"


def test_write_and_read_back(tmp_path):
    notes = [Note("chords", 0, 4, 60), Note("chords", 0, 4, 64), Note("bass", 0, 1, 36, 1.0),
             Note("drums", 0, 0.25, 36), Note("drums", 1, 0.25, 39), Note("chops", 2.5, 0.5, 76, 0.9)]
    p = write_midi(tmp_path / "x.mid", notes, 155.0, "Mind Over Matter (Rad Cat Remix)")
    s = read_midi_summary(p)
    assert s["format"] == 1 and s["ppq"] == 480
    assert s["tempo"] == __import__("pytest").approx(155.0, rel=1e-4)
    names = [t["name"] for t in s["tracks"]]
    assert names == ["Mind Over Matter (Rad Cat Remix)", "chords", "chops", "bass", "drums"]
    counts = {t["name"]: t["notes"] for t in s["tracks"]}
    assert counts == {"Mind Over Matter (Rad Cat Remix)": 0, "chords": 2, "chops": 1, "bass": 1, "drums": 2}


def test_repeated_notes_do_not_overlap(tmp_path):
    # Back-to-back same-pitch notes: the note-off must land before the next note-on.
    notes = [Note("bass", b, 1, 36) for b in range(8)]
    p = write_midi(tmp_path / "r.mid", notes, 120.0)
    data = p.read_bytes()
    assert data.count(bytes([0x92, 36])) == 8 and data.count(bytes([0x82, 36])) == 8
