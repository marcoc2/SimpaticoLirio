"""Real-time DSP kernels (numba-compiled).

Three voice engines, like the Orchid:
    0 = ANALOG  polyBLEP saw/square x2 + sub, resonant SVF low-pass
    1 = FM      two-operator FM with a decaying modulation index
    2 = EPIANO  FM tine model (1:1 body + 1:14 bark), the classic digital EP recipe
Every engine runs through the same filter and amp envelope.
"""

import math

import numpy as np
from numba import njit

TWO_PI = 2.0 * math.pi

# Voice state columns
S_STAGE, S_NOTE, S_FREQ, S_VEL, S_ENV, S_FENV, S_MODENV, S_TINEENV = 0, 1, 2, 3, 4, 5, 6, 7
S_PH1, S_PH2, S_PH3, S_PH4, S_IC1, S_IC2, S_AGE = 8, 9, 10, 11, 12, 13, 14
NUM_STATE = 16

# Envelope stages
STAGE_OFF, STAGE_ATTACK, STAGE_DECAY, STAGE_SUSTAIN, STAGE_RELEASE = 0, 1, 2, 3, 4

# Parameter slots
(P_ENGINE, P_ATTACK, P_DECAY, P_SUSTAIN, P_RELEASE, P_CUTOFF, P_RES, P_FENV_AMT,
 P_FENV_DECAY, P_DETUNE, P_OSC2, P_SUB, P_SHAPE, P_FM_RATIO, P_FM_INDEX, P_FM_DECAY,
 P_FM_SUS_INDEX, P_LFO_RATE, P_VIB, P_TREM, P_LFO_CUT, P_GAIN, P_VELSENS, P_TINE,
 P_KEYTRACK, P_NOISE) = range(26)
NUM_PARAMS = 32

SUB_BLOCK = 16


@njit(cache=True, fastmath=True, inline="always")
def _polyblep(t, dt):
    if t < dt:
        t = t / dt
        return t + t - t * t - 1.0
    if t > 1.0 - dt:
        t = (t - 1.0) / dt
        return t * t + t + t + 1.0
    return 0.0


@njit(cache=True, fastmath=True, inline="always")
def _osc(ph, dt, shape):
    saw = 2.0 * ph - 1.0 - _polyblep(ph, dt)
    if shape <= 0.0:
        return saw
    ph2 = ph + 0.5
    if ph2 >= 1.0:
        ph2 -= 1.0
    sq = (1.0 if ph < 0.5 else -1.0) + _polyblep(ph, dt) - _polyblep(ph2, dt)
    return saw * (1.0 - shape) + sq * shape


@njit(cache=True, fastmath=True)
def render_voices(vs, p, g, out, sr):
    """Render all active voices, adding into mono `out`. g[0] holds the LFO phase."""
    n = out.shape[0]
    engine = int(p[P_ENGINE])
    lfo_inc = p[P_LFO_RATE] / sr
    nyq = 0.45 * sr

    a_rate = 1.0 / (max(p[P_ATTACK], 0.001) * sr)
    d_coef = math.exp(-4.0 / (max(p[P_DECAY], 0.005) * sr))
    r_coef = math.exp(-4.0 / (max(p[P_RELEASE], 0.005) * sr))
    f_coef = math.exp(-4.0 / (max(p[P_FENV_DECAY], 0.005) * sr))
    m_coef = math.exp(-4.0 / (max(p[P_FM_DECAY], 0.005) * sr))
    t_coef = math.exp(-4.0 / (0.04 * sr))
    sus = p[P_SUSTAIN]
    k = 2.0 - 1.95 * min(max(p[P_RES], 0.0), 1.0)
    detune = 2.0 ** (p[P_DETUNE] / 1200.0)

    for v in range(vs.shape[0]):
        stage = int(vs[v, S_STAGE])
        if stage == STAGE_OFF:
            continue
        vel = vs[v, S_VEL]
        base_f = vs[v, S_FREQ]
        amp_vel = 1.0 - p[P_VELSENS] + p[P_VELSENS] * vel
        idx_vel = 0.4 + 0.6 * vel
        env = vs[v, S_ENV]
        fenv = vs[v, S_FENV]
        modenv = vs[v, S_MODENV]
        tineenv = vs[v, S_TINEENV]
        ph1, ph2, ph3, ph4 = vs[v, S_PH1], vs[v, S_PH2], vs[v, S_PH3], vs[v, S_PH4]
        ic1, ic2 = vs[v, S_IC1], vs[v, S_IC2]
        keytrack = (base_f / 261.63) ** p[P_KEYTRACK]

        a1 = a2 = a3 = 0.0
        f = dt1 = dt2 = dt3 = dt4 = 0.0
        trem = 1.0
        for i in range(n):
            if i % SUB_BLOCK == 0:
                lfo = math.sin(TWO_PI * (g[0] + i * lfo_inc))
                f = base_f * 2.0 ** (p[P_VIB] * lfo / 1200.0)
                trem = 1.0 - p[P_TREM] * (0.5 + 0.5 * lfo)
                fc = p[P_CUTOFF] * keytrack * 2.0 ** (p[P_FENV_AMT] * fenv + p[P_LFO_CUT] * lfo)
                fc = min(max(fc, 20.0), nyq)
                gg = math.tan(math.pi * fc / sr)
                a1 = 1.0 / (1.0 + gg * (gg + k))
                a2 = gg * a1
                a3 = gg * a2
                dt1 = f / sr
                if engine == 0:
                    dt2 = f * detune / sr
                    dt3 = 0.5 * f / sr
                elif engine == 1:
                    dt2 = f * p[P_FM_RATIO] / sr
                else:
                    dt2 = f / sr
                    dt3 = f / sr
                    dt4 = 14.0 * f / sr

            # Amp envelope
            if stage == STAGE_ATTACK:
                env += a_rate
                if env >= 1.0:
                    env = 1.0
                    stage = STAGE_DECAY
            elif stage == STAGE_DECAY or stage == STAGE_SUSTAIN:
                env = sus + (env - sus) * d_coef
            else:
                env *= r_coef
                if env < 1e-4:
                    stage = STAGE_OFF
                    break
            fenv *= f_coef
            modenv *= m_coef
            tineenv *= t_coef

            # Oscillators
            if engine == 0:
                x = _osc(ph1, dt1, p[P_SHAPE])
                x += p[P_OSC2] * _osc(ph2, dt2, p[P_SHAPE])
                x += p[P_SUB] * math.sin(TWO_PI * ph3)
                if p[P_NOISE] > 0.0:
                    x += p[P_NOISE] * (2.0 * np.random.random() - 1.0)
                x *= 0.5
            elif engine == 1:
                index = (p[P_FM_SUS_INDEX] + (p[P_FM_INDEX] - p[P_FM_SUS_INDEX]) * modenv) * idx_vel
                x = math.sin(TWO_PI * ph1 + index * math.sin(TWO_PI * ph2))
            else:
                index = (p[P_FM_SUS_INDEX] + (p[P_FM_INDEX] - p[P_FM_SUS_INDEX]) * modenv) * idx_vel
                body = math.sin(TWO_PI * ph1 + index * math.sin(TWO_PI * ph2))
                bark = math.sin(TWO_PI * ph3 + 2.5 * tineenv * idx_vel * math.sin(TWO_PI * ph4))
                x = body + p[P_TINE] * tineenv * bark

            ph1 += dt1
            if ph1 >= 1.0:
                ph1 -= 1.0
            ph2 += dt2
            if ph2 >= 1.0:
                ph2 -= 1.0
            ph3 += dt3
            if ph3 >= 1.0:
                ph3 -= 1.0
            ph4 += dt4
            if ph4 >= 1.0:
                ph4 -= 1.0

            # TPT state-variable low-pass
            v3 = x - ic2
            v1 = a1 * ic1 + a2 * v3
            v2 = ic2 + a2 * ic1 + a3 * v3
            ic1 = 2.0 * v1 - ic1
            ic2 = 2.0 * v2 - ic2

            out[i] += v2 * env * amp_vel * trem * p[P_GAIN]

        vs[v, S_STAGE] = stage
        vs[v, S_ENV] = env
        vs[v, S_FENV] = fenv
        vs[v, S_MODENV] = modenv
        vs[v, S_TINEENV] = tineenv
        vs[v, S_PH1], vs[v, S_PH2], vs[v, S_PH3], vs[v, S_PH4] = ph1, ph2, ph3, ph4
        vs[v, S_IC1], vs[v, S_IC2] = ic1, ic2
        vs[v, S_AGE] += n

    g[0] = (g[0] + n * lfo_inc) % 1.0


@njit(cache=True, fastmath=True)
def chorus(mono, out, buf, state, rate, depth_ms, base_ms, mix, sr):
    """Mono in, stereo out. state = [write_index, lfo_phase]."""
    n = mono.shape[0]
    size = buf.shape[0]
    w = int(state[0])
    ph = state[1]
    inc = rate / sr
    base = base_ms * 0.001 * sr
    depth = depth_ms * 0.001 * sr
    for i in range(n):
        x = mono[i]
        buf[w] = x
        for ch in range(2):
            lfo = math.sin(TWO_PI * (ph + 0.5 * ch))
            d = base + depth * (0.5 + 0.5 * lfo)
            r = w - d
            while r < 0:
                r += size
            i0 = int(r)
            frac = r - i0
            i1 = (i0 + 1) % size
            wet = buf[i0] * (1.0 - frac) + buf[i1] * frac
            out[i, ch] = x * (1.0 - 0.5 * mix) + wet * mix
        w = (w + 1) % size
        ph += inc
        if ph >= 1.0:
            ph -= 1.0
    state[0] = w
    state[1] = ph


@njit(cache=True, fastmath=True)
def stereo_delay(io, buf, state, delay_samples, feedback, mix):
    """Ping-pong delay, processed in place. state = [write_index]."""
    n = io.shape[0]
    size = buf.shape[0]
    w = int(state[0])
    d = int(min(max(delay_samples, 1), size - 1))
    for i in range(n):
        r = w - d
        if r < 0:
            r += size
        dl = buf[r, 0]
        dr = buf[r, 1]
        inl = io[i, 0]
        inr = io[i, 1]
        buf[w, 0] = 0.5 * (inl + inr) + dr * feedback
        buf[w, 1] = dl * feedback
        io[i, 0] = inl + dl * mix
        io[i, 1] = inr + dr * mix
        w = (w + 1) % size
    state[0] = w


@njit(cache=True, fastmath=True)
def freeverb(io, comb_buf, comb_len, comb_idx, comb_store, ap_buf, ap_len, ap_idx,
             room, damp, mix):
    """Freeverb (8 combs + 4 allpasses per side), processed in place.

    Arrays are laid out with the left channel in rows 0..7 / 0..3 and the right
    channel in rows 8..15 / 4..7.
    """
    n = io.shape[0]
    for i in range(n):
        x = (io[i, 0] + io[i, 1]) * 0.015
        for ch in range(2):
            acc = 0.0
            for c in range(8):
                row = ch * 8 + c
                j = comb_idx[row]
                y = comb_buf[row, j]
                comb_store[row] = y * (1.0 - damp) + comb_store[row] * damp
                comb_buf[row, j] = x + comb_store[row] * room
                j += 1
                if j >= comb_len[row]:
                    j = 0
                comb_idx[row] = j
                acc += y
            for a in range(4):
                row = ch * 4 + a
                j = ap_idx[row]
                b = ap_buf[row, j]
                ap_buf[row, j] = acc + b * 0.5
                acc = b - acc
                j += 1
                if j >= ap_len[row]:
                    j = 0
                ap_idx[row] = j
            io[i, ch] = io[i, ch] * (1.0 - 0.5 * mix) + acc * mix * 3.0
