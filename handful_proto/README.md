# Handful prototype (Python)

The first version of the chord synth, written in Python: pygame front panel, numba DSP,
MIDI in and out through mido. The VST3 plugin in `../plugin` is a C++ port of this code, and
`plugin/tests/TheoryTest.cpp` checks that both produce the same chords.

Unlike the plugin, the prototype also has a beat machine and an audio looper.

## Install

Run everything from the repository root.

```
pip install -r requirements.txt
```

## Run

```
python -m handful_proto                 # front panel + audio
python -m handful_proto --list          # list MIDI and audio devices
python -m handful_proto --learn         # map your controller (writes handful_config.json)
python -m handful_proto --no-gui        # headless, MIDI only
python -m handful_proto --midi-out loopMIDI --no-audio   # drive a DAW instead of the built-in synth
```

The first start compiles the DSP with numba, which takes a few seconds. Later starts use the cache.

## Using a MIDI controller

By default:

- **Keys**: any note that isn't mapped to a button plays the root note.
- **Chord buttons**: drum pads on channel 10, notes 36-43. The top pad row is DIM MIN MAJ SUS and the bottom row is 6 m7 M7 9.
- **Voicing / bass voicing dials**: CC 70 / 71. A knob centred at 64 means no inversion.
- **Knobs**: CC 72-77 for cutoff, resonance, reverb, delay, chorus and perform mode.
- **Sustain pedal (CC 64)**: latches the chord.

If your controller differs, run `python -m handful_proto --learn`. It asks you to press and turn
each control, detects relative encoders on its own, and saves the mapping to
`handful_config.json`. You can also edit that file by hand. `config.py` documents
every key.

## Computer keyboard

| Keys | Action |
|---|---|
| `Z S X D C V G B H N J M ,` | the 12 keys (root note) |
| `1 2 3 4` | DIM MIN MAJ SUS (hold) |
| `Q W E R` | 6 m7 M7 9 (hold) |
| Left / Right | voicing dial |
| Up / Down | bass voicing dial |
| PgUp / PgDn | octave |
| `T` / `Y` | perform mode / sound (Shift = back) |
| `U` / `I` / `O` | key mode on/off / key root / major-minor |
| `P` | playstyle |
| `5` `6` `7` | bass on/off, voicing mode, latch |
| `8` / `9` `0` | beat on/off / beat pattern |
| `-` `=` | BPM (Shift = ±10) |
| Space / `L` / Backspace / Delete | loop rec-play-dub / stop / undo / clear |
| `[` `]` then `;` `'` | select knob / turn knob |
| Esc | panic (all notes off) |
| F1 | help overlay |

The mouse works too: click and hold chord buttons and piano keys, scroll over any knob or
dial, click a dial to switch voicing mode or toggle the bass.

## Layout

```
handful_proto/
  theory.py    chord buttons, playstyles, key mode, voicing and bass logic
  dsp.py       numba kernels: voices (analog / FM / EP), SVF filter, chorus, delay, reverb
  synth.py     voice allocation, FX chain
  presets.py   factory sounds
  perform.py   perform modes on the sample clock
  drums.py     drum kit, beat patterns, looper
  engine.py    state, chord generation, audio mixing, knob definitions
  midi_io.py   controller mapping and MIDI output
  learn.py     interactive MIDI learn
  gui.py       pygame front panel
```
