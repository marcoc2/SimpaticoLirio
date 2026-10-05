"""Synthesised drum kit, step patterns and the audio looper."""

from __future__ import annotations

import numpy as np


def _env(n, sr, decay):
    t = np.arange(n) / sr
    return np.exp(-t / decay)


def build_kit(sr: int, seed: int = 7) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    kit = {}

    n = int(0.5 * sr)
    t = np.arange(n) / sr
    freq = 45 + 110 * np.exp(-t / 0.035)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    kick = np.sin(phase) * _env(n, sr, 0.18)
    kick[: int(0.002 * sr)] += rng.uniform(-0.4, 0.4, int(0.002 * sr))
    kit["kick"] = np.tanh(kick * 1.8) * 0.9

    n = int(0.3 * sr)
    t = np.arange(n) / sr
    tone = np.sin(2 * np.pi * 185 * t) * _env(n, sr, 0.05)
    noise = rng.uniform(-1, 1, n)
    noise = np.diff(noise, prepend=0.0)  # crude high-pass
    kit["snare"] = (0.6 * tone + 0.45 * noise * _env(n, sr, 0.07)) * 0.7

    n = int(0.35 * sr)
    clap_env = np.zeros(n)
    for offset in (0.0, 0.011, 0.022):
        start = int(offset * sr)
        clap_env[start:] += _env(n - start, sr, 0.008 if offset < 0.02 else 0.09)
    noise = np.diff(rng.uniform(-1, 1, n), prepend=0.0)
    kit["clap"] = noise * clap_env * 0.35

    n = int(0.06 * sr)
    noise = np.diff(np.diff(rng.uniform(-1, 1, n), prepend=0.0), prepend=0.0)
    kit["hat"] = noise * _env(n, sr, 0.012) * 0.18

    n = int(0.4 * sr)
    noise = np.diff(np.diff(rng.uniform(-1, 1, n), prepend=0.0), prepend=0.0)
    kit["open"] = noise * _env(n, sr, 0.12) * 0.13

    n = int(0.15 * sr)
    t = np.arange(n) / sr
    kit["rim"] = np.sin(2 * np.pi * 820 * t) * _env(n, sr, 0.012) * 0.35

    n = int(0.5 * sr)
    t = np.arange(n) / sr
    freq = 95 + 60 * np.exp(-t / 0.05)
    kit["tom"] = np.sin(2 * np.pi * np.cumsum(freq) / sr) * _env(n, sr, 0.2) * 0.5
    return kit


# 16 steps per bar. "x" = hit, "X" = accent, "." = rest.
PATTERNS = [
    ("Four Floor", {"kick": "x...x...x...x...", "clap": "....x.......x...",
                    "hat": "..x...x...x...x.", "open": "..............x."}),
    ("Disco", {"kick": "x...x...x...x...", "snare": "....x.......x...",
               "hat": "xxxxxxxxxxxxxxxx", "open": "..x...x...x...x."}),
    ("Techno", {"kick": "X...x...X...x...", "hat": "..x...x...x...x.",
                "rim": "...x..x....x..x.", "clap": "....x.......x..."}),
    ("Boom Bap", {"kick": "x.........x.x...", "snare": "....X.......X...",
                  "hat": "x.x.x.x.x.x.x.xx"}),
    ("Halftime", {"kick": "x......x..x.....", "snare": "........X.......",
                  "hat": "x.x.x.x.x.x.x.x."}),
    ("Trap", {"kick": "x......x..x.....", "clap": "........X.......",
              "hat": "x.x.xxx.x.x.xxxx", "open": "...............x"}),
    ("Breakbeat", {"kick": "x.x.......x.....", "snare": "....x..x.x..x..x",
                   "hat": "x.x.x.x.x.x.x.x."}),
    ("Bossa", {"kick": "x..xx..xx..xx..x", "rim": "x..x..x...x..x..",
               "hat": "xxxxxxxxxxxxxxxx"}),
    ("Motorik", {"kick": "x.x...x.x.x...x.", "snare": "....x.......x...",
                 "hat": "x.x.x.x.x.x.x.x.", "tom": "..............x."}),
    ("Shuffle", {"kick": "x.....x.x.......", "snare": "....x.......x...",
                 "hat": "x..x.xx..x.xx..x"}),
]


class DrumMachine:
    def __init__(self, sr: int):
        self.kit = build_kit(sr)
        self.pattern_index = 0
        self.running = False
        self.volume = 0.8
        self._voices: list[list] = []  # [sample, position, gain]

    @property
    def pattern_name(self) -> str:
        return PATTERNS[self.pattern_index][0]

    def step(self, step_index: int, offset: int = 0):
        """Trigger every instrument with a hit on this 16th step."""
        if not self.running:
            return
        _, lanes = PATTERNS[self.pattern_index]
        s = step_index % 16
        for inst, lane in lanes.items():
            ch = lane[s]
            if ch != ".":
                gain = 1.0 if ch == "X" else 0.75
                if inst == "hat":
                    self._voices = [vv for vv in self._voices if vv[0] is not self.kit["open"]]
                self._voices.append([self.kit[inst], -offset, gain])

    def render(self, out: np.ndarray):
        n = out.shape[0]
        alive = []
        for voice in self._voices:
            sample, pos, gain = voice
            start = max(0, -pos)
            src = max(0, pos)
            count = min(n - start, len(sample) - src)
            if count > 0:
                chunk = sample[src: src + count] * gain * self.volume
                out[start: start + count, 0] += chunk
                out[start: start + count, 1] += chunk
            voice[1] = pos + n
            if voice[1] < len(sample):
                alive.append(voice)
        self._voices = alive


class Looper:
    """Audio looper: record -> play -> overdub -> play ..., with one level of undo."""

    EMPTY, RECORDING, PLAYING, OVERDUB, STOPPED = "EMPTY", "REC", "PLAY", "DUB", "STOP"

    def __init__(self, sr: int, max_seconds: float = 90.0):
        self.sr = sr
        self.buf = np.zeros((int(max_seconds * sr), 2), dtype=np.float32)
        self.undo_buf: np.ndarray | None = None
        self.length = 0
        self.pos = 0
        self.state = self.EMPTY
        self.volume = 1.0

    def press(self, quantize_samples: int = 0):
        if self.state == self.EMPTY:
            self.buf[:] = 0.0
            self.pos = 0
            self.state = self.RECORDING
        elif self.state == self.RECORDING:
            length = self.pos
            if quantize_samples > 0:
                bars = max(1, round(length / quantize_samples))
                length = min(bars * quantize_samples, len(self.buf))
            self.length = max(length, 1)
            self.pos = self.pos % self.length
            self.state = self.PLAYING
        elif self.state == self.PLAYING:
            self.undo_buf = self.buf[: self.length].copy()
            self.state = self.OVERDUB
        elif self.state == self.OVERDUB:
            self.state = self.PLAYING
        elif self.state == self.STOPPED:
            self.pos = 0
            self.state = self.PLAYING

    def stop(self):
        if self.state in (self.PLAYING, self.OVERDUB):
            self.state = self.STOPPED
        elif self.state == self.RECORDING:
            self.press()
            self.state = self.STOPPED

    def undo(self):
        if self.undo_buf is not None and self.length:
            self.buf[: self.length] = self.undo_buf
            self.undo_buf = None
            if self.state == self.OVERDUB:
                self.state = self.PLAYING

    def clear(self):
        self.state = self.EMPTY
        self.length = 0
        self.pos = 0
        self.undo_buf = None

    def process(self, live: np.ndarray, out: np.ndarray):
        """live = what is being played now (gets recorded); loop playback is added to out."""
        n = live.shape[0]
        if self.state == self.RECORDING:
            end = min(self.pos + n, len(self.buf))
            self.buf[self.pos:end] = live[: end - self.pos]
            self.pos = end
            if end >= len(self.buf):
                self.press()
            return
        if self.state not in (self.PLAYING, self.OVERDUB) or self.length == 0:
            return
        idx = (self.pos + np.arange(n)) % self.length
        out += self.buf[idx] * self.volume
        if self.state == self.OVERDUB:
            self.buf[idx] += live
        self.pos = (self.pos + n) % self.length

    @property
    def progress(self) -> float:
        if self.length and self.state in (self.PLAYING, self.OVERDUB):
            return self.pos / self.length
        return 0.0
