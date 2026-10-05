"""Polyphonic synth voice manager and the FX chain."""

from __future__ import annotations

import numpy as np

from . import dsp

PARAM_NAMES = {
    "engine": dsp.P_ENGINE, "attack": dsp.P_ATTACK, "decay": dsp.P_DECAY,
    "sustain": dsp.P_SUSTAIN, "release": dsp.P_RELEASE, "cutoff": dsp.P_CUTOFF,
    "resonance": dsp.P_RES, "fenv_amount": dsp.P_FENV_AMT, "fenv_decay": dsp.P_FENV_DECAY,
    "detune": dsp.P_DETUNE, "osc2": dsp.P_OSC2, "sub": dsp.P_SUB, "shape": dsp.P_SHAPE,
    "fm_ratio": dsp.P_FM_RATIO, "fm_index": dsp.P_FM_INDEX, "fm_decay": dsp.P_FM_DECAY,
    "fm_sustain_index": dsp.P_FM_SUS_INDEX, "lfo_rate": dsp.P_LFO_RATE,
    "vibrato": dsp.P_VIB, "tremolo": dsp.P_TREM, "lfo_cutoff": dsp.P_LFO_CUT,
    "gain": dsp.P_GAIN, "velocity_sens": dsp.P_VELSENS, "tine": dsp.P_TINE,
    "keytrack": dsp.P_KEYTRACK, "noise": dsp.P_NOISE,
}

DEFAULT_PARAMS = {
    "engine": 0, "attack": 0.005, "decay": 0.5, "sustain": 0.7, "release": 0.4,
    "cutoff": 4000.0, "resonance": 0.1, "fenv_amount": 0.0, "fenv_decay": 0.3,
    "detune": 8.0, "osc2": 0.7, "sub": 0.0, "shape": 0.0, "fm_ratio": 1.0,
    "fm_index": 1.0, "fm_decay": 0.5, "fm_sustain_index": 0.3, "lfo_rate": 5.0,
    "vibrato": 0.0, "tremolo": 0.0, "lfo_cutoff": 0.0, "gain": 0.25,
    "velocity_sens": 0.6, "tine": 0.0, "keytrack": 0.3, "noise": 0.0,
}


class Synth:
    def __init__(self, sr: int, voices: int):
        self.sr = sr
        self.vs = np.zeros((voices, dsp.NUM_STATE), dtype=np.float64)
        self.p = np.zeros(dsp.NUM_PARAMS, dtype=np.float64)
        self.g = np.zeros(4, dtype=np.float64)
        self.load(DEFAULT_PARAMS)

    def load(self, params: dict):
        merged = dict(DEFAULT_PARAMS)
        merged.update(params)
        for name, value in merged.items():
            if name in PARAM_NAMES:
                self.p[PARAM_NAMES[name]] = float(value)

    def get(self, name: str) -> float:
        return float(self.p[PARAM_NAMES[name]])

    def set(self, name: str, value: float):
        self.p[PARAM_NAMES[name]] = float(value)

    def note_on(self, note: int, velocity: float):
        vs = self.vs
        free = np.where(vs[:, dsp.S_STAGE] == dsp.STAGE_OFF)[0]
        if len(free):
            v = int(free[0])
        else:
            releasing = np.where(vs[:, dsp.S_STAGE] == dsp.STAGE_RELEASE)[0]
            pool = releasing if len(releasing) else np.arange(len(vs))
            v = int(pool[np.argmax(vs[pool, dsp.S_AGE])])
        row = vs[v]
        retrigger = row[dsp.S_STAGE] != dsp.STAGE_OFF
        row[dsp.S_STAGE] = dsp.STAGE_ATTACK
        row[dsp.S_NOTE] = note
        row[dsp.S_FREQ] = 440.0 * 2.0 ** ((note - 69) / 12.0)
        row[dsp.S_VEL] = velocity
        if not retrigger:
            row[dsp.S_ENV] = 0.0
            row[dsp.S_IC1] = row[dsp.S_IC2] = 0.0
            row[dsp.S_PH1] = row[dsp.S_PH2] = row[dsp.S_PH3] = row[dsp.S_PH4] = 0.0
        else:
            row[dsp.S_ENV] *= 0.5  # soften the click of a stolen voice
        row[dsp.S_FENV] = 1.0
        row[dsp.S_MODENV] = 1.0
        row[dsp.S_TINEENV] = 1.0
        row[dsp.S_AGE] = 0.0

    def note_off(self, note: int):
        vs = self.vs
        mask = (vs[:, dsp.S_NOTE] == note) & (vs[:, dsp.S_STAGE] != dsp.STAGE_OFF) \
            & (vs[:, dsp.S_STAGE] != dsp.STAGE_RELEASE)
        vs[mask, dsp.S_STAGE] = dsp.STAGE_RELEASE

    def all_off(self):
        active = self.vs[:, dsp.S_STAGE] != dsp.STAGE_OFF
        self.vs[active, dsp.S_STAGE] = dsp.STAGE_RELEASE

    def render(self, out: np.ndarray):
        dsp.render_voices(self.vs, self.p, self.g, out, float(self.sr))


class FXChain:
    """Drive -> chorus -> ping-pong delay -> reverb."""

    COMB_TUNING = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617]
    AP_TUNING = [556, 441, 341, 225]
    SPREAD = 23

    def __init__(self, sr: int):
        self.sr = sr
        self.drive = 0.0
        self.chorus_mix = 0.0
        self.chorus_rate = 0.6
        self.chorus_depth = 3.0
        self.delay_mix = 0.0
        self.delay_feedback = 0.35
        self.delay_beats = 0.75  # dotted eighth
        self.reverb_mix = 0.2
        self.reverb_size = 0.84
        self.reverb_damp = 0.3

        self._chorus_buf = np.zeros(int(0.05 * sr), dtype=np.float64)
        self._chorus_state = np.zeros(2, dtype=np.float64)
        self._delay_buf = np.zeros((int(2.5 * sr), 2), dtype=np.float64)
        self._delay_state = np.zeros(1, dtype=np.float64)

        scale = sr / 44100.0
        lens = [int(t * scale) for t in self.COMB_TUNING] + \
               [int((t + self.SPREAD) * scale) for t in self.COMB_TUNING]
        self._comb_len = np.array(lens, dtype=np.int64)
        self._comb_buf = np.zeros((16, max(lens) + 1), dtype=np.float64)
        self._comb_idx = np.zeros(16, dtype=np.int64)
        self._comb_store = np.zeros(16, dtype=np.float64)
        aps = [int(t * scale) for t in self.AP_TUNING] + \
              [int((t + self.SPREAD) * scale) for t in self.AP_TUNING]
        self._ap_len = np.array(aps, dtype=np.int64)
        self._ap_buf = np.zeros((8, max(aps) + 1), dtype=np.float64)
        self._ap_idx = np.zeros(8, dtype=np.int64)

    def load(self, fx: dict):
        for key, value in fx.items():
            if hasattr(self, key) and not key.startswith("_"):
                setattr(self, key, float(value))

    def process(self, mono: np.ndarray, out: np.ndarray, bpm: float):
        if self.drive > 0.01:
            d = 1.0 + 8.0 * self.drive
            mono[:] = np.tanh(mono * d) / np.tanh(d)
        dsp.chorus(mono, out, self._chorus_buf, self._chorus_state, self.chorus_rate,
                   self.chorus_depth, 7.0, self.chorus_mix, float(self.sr))
        if self.delay_mix > 0.001:
            delay_samples = self.delay_beats * 60.0 / bpm * self.sr
            dsp.stereo_delay(out, self._delay_buf, self._delay_state, delay_samples,
                             self.delay_feedback, self.delay_mix)
        if self.reverb_mix > 0.001:
            room = 0.7 + 0.28 * self.reverb_size
            dsp.freeverb(out, self._comb_buf, self._comb_len, self._comb_idx,
                         self._comb_store, self._ap_buf, self._ap_len, self._ap_idx,
                         room, self.reverb_damp, self.reverb_mix)
