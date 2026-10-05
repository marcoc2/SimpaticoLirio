"""Perform modes: how a chord's notes are spread out in time.

Timing runs on the audio sample clock so arps and patterns lock to the drum machine.
"""

from __future__ import annotations

import heapq
import math
import random
from typing import Callable

MODES = ["OFF", "STRUM", "STRUM 2OCT", "SLOP", "ARP", "ARP 2OCT", "PATTERN", "HARP"]

# 16 steps; each step is a tuple of chord-tone indices (wrapping), "*" = whole chord,
# "^" = every tone but the lowest. Kept in sync with plugin/Source/Performer.cpp.
PATTERNS = [
    ("Pulse", ["*", "", "", "*", "", "", "*", "", "", "", "*", "", "*", "", "", ""]),
    ("Alberti", [(0,), (2,), (1,), (2,)] * 4),
    ("Bounce", [(0,), "", "^", "", (0,), "", "^", "^", (0,), "", "^", "", (0,), "^", "", "^"]),
    ("Offbeat", ["", "", "*", "", "", "", "*", "", "", "", "*", "", "", "", "*", "*"]),
    ("Ripple", [(0,), (1,), (2,), (3,), (2,), (1,), (0,), "",
                (0,), (1,), (2,), (3,), (4,), (3,), (2,), (1,)]),
]

ARP_RATES = [("1/4", 4), ("1/8", 2), ("1/8T", 4 / 3), ("1/16", 1), ("1/16T", 2 / 3), ("1/32", 0.5)]


class Performer:
    def __init__(self, sr: int, note_on: Callable[[int, int], None],
                 note_off: Callable[[int], None]):
        self.sr = sr
        self._on = note_on
        self._off = note_off
        self.mode = "OFF"
        self.pattern_index = 0
        self.arp_rate_index = 3
        self.strum_ms = 28.0
        self.slop_ms = 70.0
        self.harp_ms = 22.0
        self.gate = 0.6

        self.notes: list[int] = []
        self.velocity = 100
        self._sounding: dict[int, int] = {}  # note -> count
        self._queue: list[tuple[int, int, str, int, int]] = []
        self._seq = 0
        self._arp_index = 0
        self._last_tick = -1
        self.now = 0

    # --- low level -------------------------------------------------------------------
    def _schedule(self, when: int, kind: str, note: int, vel: int = 0):
        self._seq += 1
        heapq.heappush(self._queue, (when, self._seq, kind, note, vel))

    def _note_on(self, note: int, vel: int):
        if note in self._sounding:
            self._off(note)
        self._sounding[note] = 1
        self._on(note, vel)

    def _note_off(self, note: int):
        if self._sounding.pop(note, None) is not None:
            self._off(note)

    def _cancel_pending_ons(self):
        self._queue = [e for e in self._queue if e[2] != "on"]
        heapq.heapify(self._queue)

    def all_off(self):
        self._queue.clear()
        for note in list(self._sounding):
            self._note_off(note)

    # --- chord input -----------------------------------------------------------------
    def chord_changed(self, notes: list[int], velocity: int):
        """Called whenever the generated chord changes. An empty list means release."""
        prev = self.notes
        self.notes = list(notes)
        self.velocity = velocity
        now = self.now
        mode = self.mode

        if not notes:
            if mode == "HARP":
                self._cancel_pending_ons()
            else:
                self.all_off()
            return

        if mode == "OFF":
            self._queue.clear()
            for n in list(self._sounding):
                if n not in notes:
                    self._note_off(n)
            for n in notes:
                if n not in self._sounding:
                    self._note_on(n, velocity)
            return

        if mode in ("STRUM", "STRUM 2OCT", "SLOP"):
            self.all_off()
            seq = sorted(notes)
            if mode == "STRUM 2OCT":
                seq = seq + [n + 12 for n in seq]
            gap = self.strum_ms * 0.001 * self.sr
            for i, n in enumerate(seq):
                if mode == "SLOP":
                    t = now + int(random.uniform(0, self.slop_ms) * 0.001 * self.sr)
                    v = max(1, min(127, velocity + random.randint(-25, 10)))
                else:
                    t = now + int(i * gap)
                    v = velocity
                self._schedule(t, "on", n, v)
            return

        if mode == "HARP":
            self._cancel_pending_ons()
            base = sorted({n % 12 for n in notes})
            start = min(notes)
            seq = []
            octave = start - start % 12
            while len(seq) < 3 * len(base) + 1:
                for pc in base:
                    n = octave + pc
                    if n >= start:
                        seq.append(n)
                octave += 12
            gap = self.harp_ms * 0.001 * self.sr
            ring = int(0.35 * self.sr)
            for i, n in enumerate(seq[: 3 * len(base) + 1]):
                t = now + int(i * gap)
                self._schedule(t, "on", n, velocity)
                self._schedule(t + ring, "off", n)
            return

        # ARP / PATTERN: continuous, driven by the grid. Fire immediately on a new press
        # and swallow the next grid tick if it is too close to this one.
        if not prev:
            self._arp_index = 0
            step_len = self._step_len_for_mode()
            pos = (now - self._origin) / step_len
            next_tick = math.ceil(pos)
            if next_tick - pos < 0.5:
                self._last_tick = next_tick
                step_number = int(round(next_tick * step_len / self._sixteenth))
            else:
                step_number = int(pos * step_len / self._sixteenth)
            self._fire_step(now, step_len, step_number)

    # --- clocked modes ---------------------------------------------------------------
    def _arp_sequence(self) -> list[int]:
        seq = sorted(self.notes)
        if self.mode == "ARP 2OCT":
            seq = seq + [n + 12 for n in seq]
        return seq

    def _step_len_for_mode(self) -> float:
        return self._sixteenth * (ARP_RATES[self.arp_rate_index][1] if self.mode != "PATTERN" else 1)

    def _fire_step(self, when: int, step_len: float, step_number: int):
        if not self.notes:
            return
        gate_len = max(1, int(step_len * self.gate))
        if self.mode in ("ARP", "ARP 2OCT"):
            seq = self._arp_sequence()
            n = seq[self._arp_index % len(seq)]
            self._arp_index += 1
            self._schedule(when, "on", n, self.velocity)
            self._schedule(when + gate_len, "off", n)
        elif self.mode == "PATTERN":
            _, steps = PATTERNS[self.pattern_index]
            step = steps[step_number % 16]
            if not step:
                return
            chord = sorted(self.notes)
            if step == "*":
                targets = chord
            elif step == "^":
                targets = chord[1:]
            else:
                targets = [chord[i % len(chord)] for i in step]
            accent = self.velocity if step_number % 4 == 0 else int(self.velocity * 0.8)
            for n in targets:
                self._schedule(when, "on", n, accent)
                self._schedule(when + gate_len, "off", n)

    _sixteenth = 1.0
    _origin = 0

    def process(self, block_start: int, block_len: int, sixteenth_samples: float,
                transport_origin: int):
        """Run all events that fall inside [block_start, block_start + block_len)."""
        self.now = block_start
        self._sixteenth = sixteenth_samples
        self._origin = transport_origin
        end = block_start + block_len

        if self.mode in ("ARP", "ARP 2OCT", "PATTERN") and self.notes:
            step_len = self._step_len_for_mode()
            first = math.ceil((block_start - transport_origin) / step_len)
            t = transport_origin + first * step_len
            while t < end:
                tick = first
                if tick != self._last_tick:
                    self._last_tick = tick
                    step_number = int(round((t - transport_origin) / sixteenth_samples))
                    self._fire_step(int(t), step_len, step_number)
                first += 1
                t = transport_origin + first * step_len

        while self._queue and self._queue[0][0] < end:
            _, _, kind, note, vel = heapq.heappop(self._queue)
            if kind == "on":
                self._note_on(note, vel)
            else:
                self._note_off(note)
