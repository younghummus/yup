import pytest

from radcat.theory import Chord, Key, default_progressions, midi_to_hz, parse_note, voice_lead


def test_note_parsing_and_frequency():
    assert parse_note("C4") == 60
    assert parse_note("A4") == 69
    assert parse_note("F#3") == 54
    assert parse_note("Bb2") == 46
    assert midi_to_hz(69) == pytest.approx(440.0)
    assert midi_to_hz(81) == pytest.approx(880.0)
    with pytest.raises(ValueError):
        parse_note("H2")


@pytest.mark.parametrize("text,root,quality,name", [
    ("C", 0, "maj", "C"), ("Am", 9, "min", "Am"), ("Fmaj9", 5, "maj9", "Fmaj9"),
    ("Em7", 4, "min7", "Em7"), ("Bb", 10, "maj", "A#"), ("G6", 7, "6", "G6"),
])
def test_chord_parse(text, root, quality, name):
    c = Chord.parse(text)
    assert (c.root, c.quality, c.name) == (root, quality, name)


def test_chord_pitch_classes_and_flavour():
    assert Chord.parse("Fmaj9").pcs == {5, 9, 0, 4, 7}
    assert Chord.parse("Am").is_minor and not Chord.parse("C").is_minor
    assert Chord.parse("C").flavoured().quality == "maj9"
    assert Chord.parse("Am").flavoured().quality == "min9"
    assert Chord.parse("C").flavoured(False).quality == "add9"
    assert Chord.parse("G6").flavoured() == Chord.parse("G6")  # already coloured
    assert Chord.parse("Am9").triad == Chord.parse("Am")


def test_voicing_contains_chord_and_sits_in_register():
    for name in ("Fmaj9", "G6", "Em7", "Am9", "C#m11"):
        c = Chord.parse(name)
        v = c.voicing(center=64)
        assert {n % 12 for n in v} == c.pcs
        assert abs(sum(v) / len(v) - 64) <= 6
        assert v == sorted(v)
    wide = Chord.parse("Am9").voicing(64, spread=2)
    assert len(wide) == 7 and max(wide) - min(wide) > 12


def test_voice_leading_moves_less_than_root_position():
    prev = Chord.parse("Fmaj9").voicing(64)
    nxt = voice_lead(prev, Chord.parse("G6"), center=64)
    mean = lambda v: sum(v) / len(v)  # noqa: E731
    assert abs(mean(nxt) - mean(prev)) <= 6


def test_key_parse_and_diatonic_triads():
    assert Key.parse("C") == Key(0, "major")
    assert Key.parse("Am") == Key(9, "minor")
    assert Key.parse("F# minor") == Key(6, "minor")
    names = [c.name for c in Key.parse("C").diatonic_triads()]
    assert names == ["C", "Dm", "Em", "F", "G", "Am", "Bdim"]
    assert Key.parse("C").transpose(2) == Key.parse("D")
    with pytest.raises(ValueError):
        Key(0, "dorian")


@pytest.mark.parametrize("key", ["C", "Eb", "A minor", "F# minor"])
def test_default_progressions_are_diatonic(key):
    k = Key.parse(key)
    scale = set(k.scale)
    for prog in default_progressions(k).values():
        assert len(prog) == 4
        for chord in prog:
            assert chord.root in scale


def test_demo_hook_harmony_in_c_is_iv_v_iii_vi():
    drop = default_progressions(Key.parse("C"))["drop"]
    assert [c.name for c in drop] == ["Fmaj9", "G6", "Em7", "Am9"]


def test_chord_tones_pool():
    assert Chord.parse("C").tones(60, 72) == [60, 64, 67, 72]
