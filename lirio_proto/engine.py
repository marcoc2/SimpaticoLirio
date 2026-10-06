"""The Simpático Lírio engine: chord state, sound generation and the audio-thread clock.

Every state change goes through `post()`, so it runs on the audio thread at the
start of a block. MIDI and GUI threads never touch the synth directly.
"""

from __future__ import annotations

import math
import queue
from dataclasses import dataclass
from typing import Callable

import mido
import numpy as np

from . import theory
from .drums import PATTERNS as BEAT_PATTERNS, DrumMachine, Looper
from .perform import ARP_RATES, MODES as PERFORM_MODES, PATTERNS as PERFORM_PATTERNS, Performer
from .presets import BASS_PRESETS, PRESETS
from .synth import FXChain, Synth


@dataclass
class Param:
    """A knob: continuous (lo..hi) or an enum (list of options)."""
    name: str
    get: Callable[[], float]
    set: Callable[[float], None]
    lo: float = 0.0
    hi: float = 1.0
    step: float = 0.02
    log: bool = False
    options: Callable[[], list[str]] | None = None
    fmt: str = "{:.2f}"

    def display(self) -> str:
        value = self.get()
        if self.options:
            return self.options()[int(value)]
        return self.fmt.format(value)

    def normalized(self) -> float:
        value = self.get()
        if self.options:
            count = len(self.options())
            return value / max(1, count - 1)
        if self.log:
            return math.log(value / self.lo) / math.log(self.hi / self.lo)
        return (value - self.lo) / (self.hi - self.lo)

    def set_normalized(self, x: float):
        x = min(max(x, 0.0), 1.0)
        if self.options:
            count = len(self.options())
            self.set(min(count - 1, int(round(x * (count - 1)))))
        elif self.log:
            self.set(self.lo * (self.hi / self.lo) ** x)
        else:
            self.set(self.lo + x * (self.hi - self.lo))

    def nudge(self, steps: int):
        if self.options:
            count = len(self.options())
            self.set((int(self.get()) + steps) % count)
        else:
            self.set_normalized(self.normalized() + steps * self.step)


class Engine:
    def __init__(self, sr: int, config: dict):
        self.sr = sr
        self.config = config
        self.events: queue.SimpleQueue = queue.SimpleQueue()
        self.midi_out_queue: queue.SimpleQueue | None = None

        ch = config.get("midi_out_channels", {})
        self.ch_perform = int(ch.get("perform", 1)) - 1
        self.ch_bass = int(ch.get("bass", 2)) - 1
        self.ch_chord = int(ch.get("chord", 3)) - 1

        self.synth = Synth(sr, voices=16)
        self.bass_synth = Synth(sr, voices=3)
        self.fx = FXChain(sr)
        self.drums = DrumMachine(sr)
        self.looper = Looper(sr)
        self.performer = Performer(sr, self._perform_on, self._perform_off)

        # Chord state
        self.held_keys: list[tuple[int, int]] = []  # (note, velocity), press order
        self.held_buttons: list[str] = []
        self.latch = False
        self.sustain = False
        self.latched_key: tuple[int, int] | None = None
        self.key_mode = False
        self.key_root = 0
        self.scale = "major"
        self.playstyle = "ADVANCED"
        self.voicing = 0
        self.voicing_mode = "OCTAVE"
        self.bass_on = True
        self.bass_voicing = 0
        self.bass_volume = 0.8
        self.master = 0.8
        self.bpm = 100.0

        self.root: int | None = None
        self.chord_notes: list[int] = []
        self.chord_label = ""
        self.bass_current: int | None = None
        self.sounding_bass: int | None = None

        self.preset_index = 0
        self.bass_preset_index = 0
        self.load_preset(0)
        self.load_bass_preset(0)

        self.clock = 0
        self.transport_origin = 0
        self._last_drum_tick = -1
        self.peak = 0.0
        self.params = self._build_params()

    # --- thread-safe entry point --------------------------------------------------------
    def post(self, fn: Callable, *args):
        self.events.put((fn, args))

    def _drain(self):
        while True:
            try:
                fn, args = self.events.get_nowait()
            except queue.Empty:
                return
            fn(*args)

    # --- MIDI out ------------------------------------------------------------------------
    def _send(self, msg: mido.Message):
        if self.midi_out_queue is not None:
            self.midi_out_queue.put(msg)

    def _perform_on(self, note: int, vel: int):
        self.synth.note_on(note, vel / 127.0)
        self._send(mido.Message("note_on", note=note, velocity=vel, channel=self.ch_perform))

    def _perform_off(self, note: int):
        self.synth.note_off(note)
        self._send(mido.Message("note_off", note=note, velocity=0, channel=self.ch_perform))

    # --- presets -------------------------------------------------------------------------
    def load_preset(self, index: int):
        self.preset_index = index % len(PRESETS)
        preset = PRESETS[self.preset_index]
        self.synth.load(preset["synth"])
        fx = {"drive": 0.0, "chorus_mix": 0.0, "chorus_depth": 3.0, "delay_mix": 0.0,
              "reverb_mix": 0.2, "reverb_size": 0.84}
        fx.update(preset.get("fx", {}))
        self.fx.load(fx)

    def load_bass_preset(self, index: int):
        self.bass_preset_index = index % len(BASS_PRESETS)
        self.bass_synth.load(BASS_PRESETS[self.bass_preset_index]["synth"])

    # --- keyboard and buttons ------------------------------------------------------------
    def key_down(self, note: int, velocity: int):
        self.held_keys = [k for k in self.held_keys if k[0] != note]
        self.held_keys.append((note, velocity))
        self.latched_key = None
        self._update_chord(retrigger=True)

    def key_up(self, note: int):
        was_top = bool(self.held_keys) and self.held_keys[-1][0] == note
        if not self.held_keys or note not in [k[0] for k in self.held_keys]:
            return
        if len(self.held_keys) == 1 and (self.latch or self.sustain):
            self.latched_key = self.held_keys[-1]
        self.held_keys = [k for k in self.held_keys if k[0] != note]
        if was_top:
            self._update_chord(retrigger=bool(self.held_keys))

    def button_down(self, name: str):
        if name not in self.held_buttons:
            self.held_buttons.append(name)
            self._update_chord()

    def button_up(self, name: str):
        if name in self.held_buttons:
            self.held_buttons.remove(name)
            self._update_chord()

    def set_sustain(self, on: bool):
        self.sustain = on
        if not on and not self.latch:
            self._release_latch()

    def toggle_latch(self):
        self.latch = not self.latch
        if not self.latch and not self.sustain:
            self._release_latch()

    def _release_latch(self):
        if self.latched_key is not None:
            self.latched_key = None
            self._update_chord()

    def set_voicing(self, value: int):
        self.voicing = max(-24, min(24, int(value)))
        self._update_chord()

    def set_bass_voicing(self, value: int):
        self.bass_voicing = max(-8, min(8, int(value)))
        self._update_chord()

    def toggle_voicing_mode(self):
        self.voicing_mode = "SPLIT" if self.voicing_mode == "OCTAVE" else "OCTAVE"
        self._update_chord()

    def toggle_bass(self):
        self.bass_on = not self.bass_on
        self._update_chord()

    def toggle_key_mode(self):
        self.key_mode = not self.key_mode
        self._update_chord()

    def set_perform_mode(self, index: int):
        self.performer.all_off()
        self.performer.notes = []
        self.performer.mode = PERFORM_MODES[int(index) % len(PERFORM_MODES)]
        if self.chord_notes:
            self.performer.chord_changed(self.chord_notes, self._velocity())

    def panic(self):
        self.performer.all_off()
        self.synth.all_off()
        self.bass_synth.all_off()
        for channel in {self.ch_perform, self.ch_bass, self.ch_chord}:
            self._send(mido.Message("control_change", control=123, value=0, channel=channel))

    # --- chord generation ----------------------------------------------------------------
    def _active_key(self) -> tuple[int, int] | None:
        if self.held_keys:
            return self.held_keys[-1]
        return self.latched_key

    def _velocity(self) -> int:
        key = self._active_key()
        return key[1] if key else 100

    def _update_chord(self, retrigger: bool = False):
        key = self._active_key()
        if key is None:
            self._apply_chord(None, [], [], "", retrigger)
            return
        note, _ = key
        types, exts = theory.resolve_buttons(self.held_buttons, self.playstyle)
        default_type = None
        root = note
        if self.key_mode:
            root, default_type = theory.key_mode_chord(note, self.key_root, self.scale)
        intervals = theory.chord_intervals(types, exts, self.playstyle, default_type)
        notes = theory.clamp_notes(
            theory.apply_voicing(root, intervals, self.voicing, self.voicing_mode))
        label = theory.chord_name(root, intervals)
        bass = None
        if self.bass_on:
            bass = theory.bass_note(root, intervals, self.bass_voicing, 36)
            if bass % 12 != root % 12 and len(intervals) > 1:
                label += "/" + theory.note_name(bass)
        self._apply_chord(root, notes, intervals, label, retrigger, bass)

    def _apply_chord(self, root, notes, intervals, label, retrigger, bass=None):
        vel = self._velocity()
        changed = notes != self.chord_notes
        old = self.chord_notes
        self.root = root
        self.chord_label = label
        self.chord_notes = notes
        if retrigger and notes:
            # A new key press always re-articulates the chord.
            self.performer.chord_changed([], vel)
            for n in old:
                self._send(mido.Message("note_off", note=n, channel=self.ch_chord))
            old = []
            changed = True
        if changed:
            for n in old:
                if n not in notes:
                    self._send(mido.Message("note_off", note=n, channel=self.ch_chord))
            for n in notes:
                if n not in old:
                    self._send(mido.Message("note_on", note=n, velocity=vel, channel=self.ch_chord))
            self.performer.chord_changed(notes, vel)

        if bass != self.sounding_bass or (retrigger and bass is not None):
            if self.sounding_bass is not None:
                self.bass_synth.note_off(self.sounding_bass)
                self._send(mido.Message("note_off", note=self.sounding_bass, channel=self.ch_bass))
            if bass is not None:
                self.bass_synth.note_on(bass, vel / 127.0)
                self._send(mido.Message("note_on", note=bass, velocity=vel, channel=self.ch_bass))
            self.sounding_bass = bass
        self.bass_current = bass

    # --- transport -----------------------------------------------------------------------
    @property
    def sixteenth(self) -> float:
        return self.sr * 60.0 / self.bpm / 4.0

    def toggle_beat(self):
        self.drums.running = not self.drums.running
        if self.drums.running:
            self.transport_origin = self.clock
            self._last_drum_tick = -1

    def loop_press(self):
        quantize = int(self.sixteenth * 16) if self.drums.running else 0
        if self.looper.state == Looper.EMPTY and self.drums.running:
            # Start recording on the bar line feel: restart the beat with the loop.
            self.transport_origin = self.clock
            self._last_drum_tick = -1
        self.looper.press(quantize)

    # --- audio ---------------------------------------------------------------------------
    def process(self, frames: int, render: bool = True) -> np.ndarray | None:
        self._drain()
        start = self.clock
        six = self.sixteenth

        tick = math.ceil((start - self.transport_origin) / six)
        t = self.transport_origin + tick * six
        while t < start + frames:
            if tick != self._last_drum_tick:
                self._last_drum_tick = tick
                self.drums.step(tick, offset=int(t - start))
            tick += 1
            t = self.transport_origin + tick * six

        self.performer.process(start, frames, six, self.transport_origin)
        self.clock += frames
        if not render:
            return None

        mono = np.zeros(frames, dtype=np.float64)
        self.synth.render(mono)
        stereo = np.zeros((frames, 2), dtype=np.float64)
        self.fx.process(mono, stereo, self.bpm)

        bass = np.zeros(frames, dtype=np.float64)
        self.bass_synth.render(bass)
        stereo += bass[:, None] * self.bass_volume

        live = stereo.astype(np.float32)
        out = live.copy()
        self.looper.process(live, out)

        drums = np.zeros((frames, 2), dtype=np.float64)
        self.drums.render(drums)
        out += drums.astype(np.float32)

        out = np.tanh(out * self.master)
        self.peak = max(self.peak * 0.9, float(np.max(np.abs(out))))
        return out

    # --- knobs ---------------------------------------------------------------------------
    def _build_params(self) -> list[Param]:
        s, fx = self.synth, self.fx

        def synth_param(name, lo, hi, log=False, fmt="{:.2f}"):
            return Param(name, lambda n=name: s.get(n), lambda v, n=name: s.set(n, v),
                         lo, hi, log=log, fmt=fmt)

        def fx_param(label, attr, lo=0.0, hi=1.0):
            return Param(label, lambda a=attr: getattr(fx, a),
                         lambda v, a=attr: setattr(fx, a, v), lo, hi)

        def setter(fn):
            return lambda v: self.post(fn, v)

        return [
            Param("sound", lambda: self.preset_index, setter(lambda v: self.load_preset(int(v))),
                  options=lambda: [p["name"] for p in PRESETS]),
            Param("perform", lambda: PERFORM_MODES.index(self.performer.mode),
                  setter(self.set_perform_mode), options=lambda: PERFORM_MODES),
            Param("arp rate", lambda: self.performer.arp_rate_index,
                  lambda v: setattr(self.performer, "arp_rate_index", int(v)),
                  options=lambda: [r[0] for r in ARP_RATES]),
            Param("pattern", lambda: self.performer.pattern_index,
                  lambda v: setattr(self.performer, "pattern_index", int(v)),
                  options=lambda: [p[0] for p in PERFORM_PATTERNS]),
            synth_param("cutoff", 60.0, 16000.0, log=True, fmt="{:.0f} Hz"),
            synth_param("resonance", 0.0, 0.95),
            synth_param("attack", 0.001, 3.0, log=True, fmt="{:.3f} s"),
            synth_param("release", 0.01, 5.0, log=True, fmt="{:.2f} s"),
            fx_param("reverb", "reverb_mix"),
            fx_param("delay", "delay_mix"),
            fx_param("chorus", "chorus_mix"),
            fx_param("drive", "drive"),
            Param("bpm", lambda: self.bpm, lambda v: setattr(self, "bpm", float(round(v))),
                  40.0, 220.0, step=1 / 180, fmt="{:.0f}"),
            Param("playstyle", lambda: theory.PLAYSTYLES.index(self.playstyle),
                  setter(lambda v: (setattr(self, "playstyle", theory.PLAYSTYLES[int(v)]),
                                    self._update_chord())),
                  options=lambda: theory.PLAYSTYLES),
            Param("key", lambda: self.key_root,
                  setter(lambda v: (setattr(self, "key_root", int(v)), self._update_chord())),
                  options=lambda: theory.NOTE_NAMES),
            Param("scale", lambda: 0 if self.scale == "major" else 1,
                  setter(lambda v: (setattr(self, "scale", "major" if int(v) == 0 else "minor"),
                                    self._update_chord())),
                  options=lambda: ["major", "minor"]),
            Param("bass sound", lambda: self.bass_preset_index,
                  setter(lambda v: self.load_bass_preset(int(v))),
                  options=lambda: [p["name"] for p in BASS_PRESETS]),
            Param("bass vol", lambda: self.bass_volume,
                  lambda v: setattr(self, "bass_volume", v), 0.0, 1.5),
            Param("beat", lambda: self.drums.pattern_index,
                  lambda v: setattr(self.drums, "pattern_index", int(v)),
                  options=lambda: [p[0] for p in BEAT_PATTERNS]),
            Param("beat vol", lambda: self.drums.volume,
                  lambda v: setattr(self.drums, "volume", v), 0.0, 1.5),
            Param("loop vol", lambda: self.looper.volume,
                  lambda v: setattr(self.looper, "volume", v), 0.0, 1.5),
            Param("master", lambda: self.master, lambda v: setattr(self, "master", v), 0.0, 1.5),
        ]

    def param(self, name: str) -> Param | None:
        for p in self.params:
            if p.name == name:
                return p
        return None
