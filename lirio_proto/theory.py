"""Chord logic modelled after the Telepathic Instruments Orchid.

Eight chord buttons:
    top row (chord types):     DIM  MIN  MAJ  SUS
    bottom row (extensions):   6    m7   M7   9

Rules (as described in the Orchid manual and reviews):
    * no button          -> the root note alone (or a diatonic chord in Key Mode)
    * type button        -> triad of that type
    * type + extension   -> extended chord (Min + m7 = m7, Min + 9 = m9, ...)
    * the 9 button implies a minor 7th unless 6 or M7 is also held (6 + 9 = 6/9)

Playstyles:
    SIMPLE    one chord type and one extension (the most recently pressed)
    ADVANCED  one chord type, any combination of extensions
    FREE      every pressed button adds its intervals; anything goes ("WTF")
"""

from __future__ import annotations

NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

TYPE_BUTTONS = ["dim", "min", "maj", "sus"]
EXT_BUTTONS = ["6", "m7", "M7", "9"]
ALL_BUTTONS = TYPE_BUTTONS + EXT_BUTTONS

BUTTON_LABELS = {
    "dim": "DIM", "min": "MIN", "maj": "MAJ", "sus": "SUS",
    "6": "6", "m7": "m7", "M7": "M7", "9": "9",
}

TYPE_INTERVALS = {
    "maj": (0, 4, 7),
    "min": (0, 3, 7),
    "dim": (0, 3, 6),
    "sus": (0, 5, 7),
}

EXT_INTERVALS = {"6": 9, "m7": 10, "M7": 11, "9": 14}

PLAYSTYLES = ["SIMPLE", "ADVANCED", "FREE"]

SCALES = {
    "major": ((0, 2, 4, 5, 7, 9, 11), ("maj", "min", "min", "maj", "maj", "min", "dim")),
    "minor": ((0, 2, 3, 5, 7, 8, 10), ("min", "dim", "maj", "min", "min", "maj", "maj")),
}


def note_name(midi_note: int, with_octave: bool = False) -> str:
    name = NOTE_NAMES[midi_note % 12]
    if with_octave:
        return f"{name}{midi_note // 12 - 1}"
    return name


def _ordered_held(held: list[str], group: list[str]) -> list[str]:
    """Buttons of a group in press order (held is ordered oldest -> newest)."""
    return [b for b in held if b in group]


def key_mode_chord(root_note: int, key_root: int, scale: str) -> tuple[int, str]:
    """Snap a played note into the key and return (snapped_note, diatonic chord type)."""
    degrees, qualities = SCALES[scale]
    rel = (root_note - key_root) % 12
    # Out-of-key notes snap down to the closest scale degree.
    best = 0
    for i, d in enumerate(degrees):
        if d <= rel:
            best = i
    snapped = root_note - (rel - degrees[best])
    return snapped, qualities[best]


def resolve_buttons(held: list[str], playstyle: str) -> tuple[list[str], list[str]]:
    """Reduce the held buttons to the active chord types and extensions."""
    types = _ordered_held(held, TYPE_BUTTONS)
    exts = _ordered_held(held, EXT_BUTTONS)
    if playstyle == "SIMPLE":
        return types[-1:], exts[-1:]
    if playstyle == "ADVANCED":
        return types[-1:], exts
    return types, exts


def chord_intervals(types: list[str], exts: list[str], playstyle: str,
                    default_type: str | None) -> list[int]:
    """Intervals (semitones above the root) for the resolved buttons."""
    if not types and default_type:
        types = [default_type]
    if not types and not exts:
        return [0]

    intervals: set[int] = set()
    if types:
        for t in types:
            intervals.update(TYPE_INTERVALS[t])
    else:
        # Extensions without a chord type sit on top of a major triad.
        intervals.update(TYPE_INTERVALS["maj"])

    for e in exts:
        intervals.add(EXT_INTERVALS[e])
    if "9" in exts and playstyle != "FREE" and not ({"6", "M7"} & set(exts)):
        intervals.add(EXT_INTERVALS["m7"])
    if "dim" in types and "6" in exts and playstyle != "FREE":
        intervals.add(9)  # dim + 6 = fully diminished 7th (bb7)

    return sorted(intervals)


# Interval set -> suffix. Covers every combination Simple/Advanced can produce.
_SUFFIXES = {
    (0,): "",
    (0, 4, 7): "", (0, 3, 7): "m", (0, 3, 6): "dim", (0, 5, 7): "sus4",
    (0, 4, 7, 9): "6", (0, 3, 7, 9): "m6", (0, 3, 6, 9): "dim7", (0, 5, 7, 9): "6sus4",
    (0, 4, 7, 10): "7", (0, 3, 7, 10): "m7", (0, 3, 6, 10): "m7b5", (0, 5, 7, 10): "7sus4",
    (0, 4, 7, 11): "maj7", (0, 3, 7, 11): "m(maj7)", (0, 3, 6, 11): "dim(maj7)",
    (0, 5, 7, 11): "maj7sus4",
    (0, 4, 7, 10, 14): "9", (0, 3, 7, 10, 14): "m9", (0, 3, 6, 10, 14): "m9b5",
    (0, 5, 7, 10, 14): "9sus4",
    (0, 4, 7, 11, 14): "maj9", (0, 3, 7, 11, 14): "m(maj9)", (0, 5, 7, 11, 14): "maj9sus4",
    (0, 4, 7, 9, 14): "6/9", (0, 3, 7, 9, 14): "m6/9", (0, 5, 7, 9, 14): "6/9sus4",
    (0, 3, 6, 9, 14): "dim7(9)",
    (0, 4, 7, 9, 10): "7(13)", (0, 3, 7, 9, 10): "m7(13)", (0, 3, 6, 9, 10): "dim7",
    (0, 4, 7, 9, 11): "maj7(13)", (0, 3, 7, 9, 11): "m(maj7)(13)",
    (0, 4, 7, 10, 11): "7(maj7)", (0, 3, 7, 10, 11): "m7(maj7)",
    (0, 4, 7, 9, 10, 14): "13", (0, 3, 7, 9, 10, 14): "m13",
    (0, 4, 7, 9, 11, 14): "maj13", (0, 3, 7, 9, 11, 14): "m(maj13)",
    (0, 4, 7, 10, 11, 14): "9(maj7)", (0, 3, 7, 10, 11, 14): "m9(maj7)",
    (0, 4, 7, 9, 10, 11, 14): "13(maj7)", (0, 3, 7, 9, 10, 11, 14): "m13(maj7)",
}


def chord_name(root_note: int, intervals: list[int]) -> str:
    suffix = _SUFFIXES.get(tuple(sorted(intervals)))
    root = note_name(root_note)
    if suffix is None:
        return f"{root} WTF"
    return root + suffix


def apply_voicing(root_note: int, intervals: list[int], voicing: int, mode: str) -> list[int]:
    """Turn intervals into MIDI notes and apply the Voicing Dial.

    OCTAVE mode: each step moves the lowest note up an octave (positive) or the
    highest note down an octave (negative) - a continuous cascade of inversions.
    SPLIT mode: every chord tone is folded into the octave starting at the split
    point, which moves one semitone per step.
    """
    notes = sorted(root_note + i for i in intervals)
    if len(notes) == 1:
        return notes
    if mode == "SPLIT":
        split = root_note + voicing
        folded = sorted({split + (n - split) % 12 for n in notes})
        return folded
    for _ in range(abs(voicing)):
        if voicing > 0:
            notes.append(notes.pop(0) + 12)
        else:
            notes.insert(0, notes.pop() - 12)
        notes.sort()
    return notes


def bass_note(root_note: int, intervals: list[int], bass_voicing: int, base_octave_note: int) -> int:
    """Bass note: the root by default; the Bass Voicing Dial walks through chord tones.

    bass_voicing 0 = root, 1 = next chord tone up, -1 = chord tone below the root, ...
    The result is placed in the octave starting at base_octave_note (e.g. 36 = C2).
    """
    tones = sorted({i % 12 for i in intervals})
    octave, idx = divmod(bass_voicing, len(tones))
    root_low = base_octave_note + (root_note - base_octave_note) % 12
    note = root_low + tones[idx] + 12 * octave
    while note < 24:
        note += 12
    while note > 64:
        note -= 12
    return note


def clamp_notes(notes: list[int], low: int = 12, high: int = 120) -> list[int]:
    out = []
    for n in notes:
        while n < low:
            n += 12
        while n > high:
            n -= 12
        out.append(n)
    return sorted(set(out))
