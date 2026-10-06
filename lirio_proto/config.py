"""Configuration: defaults merged with a user JSON file."""

from __future__ import annotations

import copy
import json
from pathlib import Path

DEFAULT_CONFIG = {
    # Substrings of MIDI input port names to open. Empty list = open every input.
    "midi_inputs": [],
    # Substring of a MIDI output port (e.g. "loopMIDI") or null to disable MIDI out.
    "midi_output": None,
    # Orchid-style split: perform-mode notes, bass and plain chords on separate channels.
    "midi_out_channels": {"perform": 1, "bass": 2, "chord": 3},
    "audio": {
        "hostapi": "Windows WASAPI",  # falls back to the system default if missing
        "device": None,               # substring of an output device name
        "blocksize": 256,
        "latency": "low",
    },
    # Notes that are not mapped to a button or action play the root note.
    # channel: 1-16 or null for any. transpose in semitones.
    "keyboard": {"channel": None, "transpose": 0},
    # The eight chord buttons. Defaults fit 2x4 drum pads (notes 36-43 on channel 10):
    # top pad row = chord types, bottom pad row = extensions - the Orchid layout.
    "buttons": {
        "dim": {"note": 40, "channel": 10},
        "min": {"note": 41, "channel": 10},
        "maj": {"note": 42, "channel": 10},
        "sus": {"note": 43, "channel": 10},
        "6": {"note": 36, "channel": 10},
        "m7": {"note": 37, "channel": 10},
        "M7": {"note": 38, "channel": 10},
        "9": {"note": 39, "channel": 10},
    },
    # Voicing dials. mode: absolute | relative_offset (64 = no change) |
    # relative_twos (1..63 up, 127..65 down) | relative_signed (1..63 up, 65..127 down).
    # range: how many steps the full travel of an absolute knob covers in each direction.
    "dials": {
        # Absolute knobs are centred: 64 = no inversion.
        "voicing": {"cc": 70, "channel": None, "mode": "absolute", "range": 8},
        "bass_voicing": {"cc": 71, "channel": None, "mode": "absolute", "range": 4},
    },
    # Continuous controls: parameter name -> CC number (absolute 0-127).
    # Names: sound, perform, arp rate, pattern, cutoff, resonance, attack, release,
    # reverb, delay, chorus, drive, bpm, playstyle, key, scale, bass sound, bass vol,
    # beat, beat vol, loop vol, master.
    # Defaults follow the common 8-knob block on CC 70-77 (voicing dials take 70/71).
    "cc": {
        "cutoff": 72,
        "resonance": 73,
        "reverb": 74,
        "delay": 75,
        "chorus": 76,
        "perform": 77,
    },
    # Momentary actions: name -> {"note": n, "channel": c} or {"cc": n, "channel": c}.
    # Names: loop, loop_stop, loop_undo, loop_clear, beat, key_mode, bass, latch,
    # voicing_mode, next_sound, prev_sound, next_perform, prev_perform, panic.
    "actions": {},
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict) and key not in ("buttons", "cc", "actions"):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: Path) -> dict:
    if path.exists():
        with path.open(encoding="utf-8") as f:
            user = json.load(f)
        return _merge(DEFAULT_CONFIG, user)
    return copy.deepcopy(DEFAULT_CONFIG)


def save_config(path: Path, config: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
