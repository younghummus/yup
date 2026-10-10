import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

# A compact form that still visits every section type (and both drop variants).
SHORT_FORM = (
    ("intro", "drop", 2, 1),
    ("verse", "verse", 2, 1),
    ("build", "drop", 2, 1),
    ("drop", "drop", 4, 1),
    ("break", "break", 2, 1),
    ("drop", "drop2", 4, 2),
    ("outro", "drop", 2, 1),
)


@pytest.fixture(scope="session")
def short_form():
    return SHORT_FORM


@pytest.fixture(scope="session")
def song_150(tmp_path_factory):
    """Synthetic band recording: 150 BPM, C major, 1.3 s lead-in (a pickup bar)."""
    from fixtures import make_song
    from radcat.dsp import write_wav

    mix, vocal, truth = make_song(150.0, 1.3)
    d = tmp_path_factory.mktemp("song")
    path = write_wav(d / "song.wav", mix)
    vpath = write_wav(d / "vocal.wav", vocal)
    return path, vpath, mix, vocal, truth


@pytest.fixture(scope="session")
def analysis_150(song_150):
    from radcat.analysis import analyse

    return analyse(song_150[0], vocal_method="centre")
