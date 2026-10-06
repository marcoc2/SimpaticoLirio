#include "Synth.h"

#include <cmath>

namespace sl
{
namespace
{
constexpr double twoPi = juce::MathConstants<double>::twoPi;
constexpr int subBlock = 16;

inline float polyBlep (double t, double dt)
{
    if (t < dt)       { t /= dt;             return (float) (t + t - t * t - 1.0); }
    if (t > 1.0 - dt) { t = (t - 1.0) / dt;  return (float) (t * t + t + t + 1.0); }
    return 0.0f;
}

inline float oscillator (double ph, double dt, float shape)
{
    const float saw = (float) (2.0 * ph - 1.0) - polyBlep (ph, dt);
    if (shape <= 0.0f)
        return saw;
    double ph2 = ph + 0.5;
    if (ph2 >= 1.0) ph2 -= 1.0;
    const float square = (ph < 0.5 ? 1.0f : -1.0f) + polyBlep (ph, dt) - polyBlep (ph2, dt);
    return saw * (1.0f - shape) + square * shape;
}

inline void wrap (double& ph) { if (ph >= 1.0) ph -= 1.0; }

VoiceParams make (Engine e, std::initializer_list<std::pair<float VoiceParams::*, float>> values)
{
    VoiceParams p;
    p.engine = e;
    for (const auto& [member, value] : values) p.*member = value;
    return p;
}

using P = VoiceParams;
}

//==============================================================================
const std::vector<Preset>& getPresets()
{
    static const std::vector<Preset> presets {
        { "Dream Pad", make (Engine::Analog, { { &P::attack, 0.6f }, { &P::decay, 1.5f }, { &P::sustain, 0.8f }, { &P::release, 1.8f },
                                               { &P::cutoff, 1400.0f }, { &P::resonance, 0.2f }, { &P::fenvAmount, 1.0f }, { &P::fenvDecay, 1.5f },
                                               { &P::detune, 12.0f }, { &P::osc2, 0.9f }, { &P::sub, 0.2f }, { &P::lfoRate, 0.4f },
                                               { &P::lfoCutoff, 0.3f }, { &P::vibrato, 4.0f }, { &P::gain, 0.18f } }) },
        { "Tine Keys", make (Engine::EPiano, { { &P::attack, 0.002f }, { &P::decay, 2.5f }, { &P::sustain, 0.0f }, { &P::release, 0.35f },
                                               { &P::cutoff, 9000.0f }, { &P::fmIndex, 1.6f }, { &P::fmSustainIndex, 0.3f }, { &P::fmDecay, 0.8f },
                                               { &P::tine, 0.5f }, { &P::tremolo, 0.25f }, { &P::lfoRate, 4.5f }, { &P::velocitySens, 0.8f },
                                               { &P::gain, 0.3f } }) },
        { "Warm Poly", make (Engine::Analog, { { &P::attack, 0.01f }, { &P::decay, 0.8f }, { &P::sustain, 0.55f }, { &P::release, 0.5f },
                                                   { &P::cutoff, 900.0f }, { &P::resonance, 0.35f }, { &P::fenvAmount, 2.5f }, { &P::fenvDecay, 0.6f },
                                                   { &P::detune, 9.0f }, { &P::osc2, 0.8f }, { &P::shape, 0.3f }, { &P::vibrato, 3.0f },
                                                   { &P::lfoRate, 5.5f }, { &P::gain, 0.22f } }) },
        { "Glass Bell", make (Engine::FM, { { &P::attack, 0.002f }, { &P::decay, 3.0f }, { &P::sustain, 0.0f }, { &P::release, 1.2f },
                                            { &P::cutoff, 12000.0f }, { &P::fmRatio, 3.5f }, { &P::fmIndex, 3.0f }, { &P::fmSustainIndex, 0.4f },
                                            { &P::fmDecay, 1.0f }, { &P::gain, 0.22f } }) },
        { "Soft Brass", make (Engine::Analog, { { &P::attack, 0.08f }, { &P::decay, 0.6f }, { &P::sustain, 0.75f }, { &P::release, 0.3f },
                                                { &P::cutoff, 700.0f }, { &P::resonance, 0.15f }, { &P::fenvAmount, 2.8f }, { &P::fenvDecay, 0.35f },
                                                { &P::detune, 6.0f }, { &P::osc2, 0.8f }, { &P::gain, 0.22f } }) },
        { "String Machine", make (Engine::Analog, { { &P::attack, 0.35f }, { &P::decay, 1.0f }, { &P::sustain, 0.9f }, { &P::release, 1.0f },
                                                    { &P::cutoff, 3200.0f }, { &P::resonance, 0.05f }, { &P::detune, 18.0f }, { &P::osc2, 1.0f },
                                                    { &P::vibrato, 6.0f }, { &P::lfoRate, 5.0f }, { &P::gain, 0.16f } }) },
        { "Pluck", make (Engine::Analog, { { &P::attack, 0.001f }, { &P::decay, 0.35f }, { &P::sustain, 0.0f }, { &P::release, 0.3f },
                                           { &P::cutoff, 500.0f }, { &P::resonance, 0.4f }, { &P::fenvAmount, 4.0f }, { &P::fenvDecay, 0.18f },
                                           { &P::detune, 5.0f }, { &P::osc2, 0.6f }, { &P::shape, 0.5f }, { &P::gain, 0.3f } }) },
        { "FM Organ", make (Engine::FM, { { &P::attack, 0.005f }, { &P::decay, 0.2f }, { &P::sustain, 1.0f }, { &P::release, 0.08f },
                                          { &P::cutoff, 8000.0f }, { &P::fmRatio, 2.0f }, { &P::fmIndex, 0.9f }, { &P::fmSustainIndex, 0.9f },
                                          { &P::tremolo, 0.15f }, { &P::lfoRate, 6.5f }, { &P::velocitySens, 0.0f }, { &P::gain, 0.2f } }) },
        { "Velvet EP", make (Engine::EPiano, { { &P::attack, 0.003f }, { &P::decay, 3.5f }, { &P::sustain, 0.1f }, { &P::release, 0.5f },
                                               { &P::cutoff, 3500.0f }, { &P::fmIndex, 0.9f }, { &P::fmSustainIndex, 0.15f }, { &P::fmDecay, 1.2f },
                                               { &P::tine, 0.25f }, { &P::tremolo, 0.4f }, { &P::lfoRate, 3.5f }, { &P::gain, 0.32f } }) },
        { "Wobble Choir", make (Engine::Analog, { { &P::attack, 0.4f }, { &P::decay, 1.0f }, { &P::sustain, 0.85f }, { &P::release, 1.2f },
                                                  { &P::cutoff, 1100.0f }, { &P::resonance, 0.5f }, { &P::detune, 14.0f }, { &P::osc2, 1.0f },
                                                  { &P::shape, 0.6f }, { &P::lfoRate, 0.25f }, { &P::lfoCutoff, 0.8f }, { &P::vibrato, 8.0f },
                                                  { &P::gain, 0.17f } }) },
    };
    return presets;
}

const std::vector<Preset>& getBassPresets()
{
    static const std::vector<Preset> presets {
        { "Sub", make (Engine::Analog, { { &P::attack, 0.005f }, { &P::decay, 0.4f }, { &P::sustain, 0.9f }, { &P::release, 0.15f },
                                         { &P::cutoff, 400.0f }, { &P::osc2, 0.0f }, { &P::sub, 0.9f }, { &P::keytrack, 0.5f }, { &P::gain, 0.45f } }) },
        { "Round", make (Engine::Analog, { { &P::attack, 0.003f }, { &P::decay, 0.5f }, { &P::sustain, 0.6f }, { &P::release, 0.15f },
                                           { &P::cutoff, 300.0f }, { &P::resonance, 0.3f }, { &P::fenvAmount, 2.5f }, { &P::fenvDecay, 0.25f },
                                           { &P::osc2, 0.5f }, { &P::detune, 4.0f }, { &P::sub, 0.4f }, { &P::keytrack, 0.6f }, { &P::gain, 0.4f } }) },
        { "FM Bass", make (Engine::FM, { { &P::attack, 0.002f }, { &P::decay, 0.6f }, { &P::sustain, 0.5f }, { &P::release, 0.12f },
                                         { &P::cutoff, 2500.0f }, { &P::fmRatio, 1.0f }, { &P::fmIndex, 2.5f }, { &P::fmSustainIndex, 0.6f },
                                         { &P::fmDecay, 0.25f }, { &P::gain, 0.4f } }) },
        { "Square", make (Engine::Analog, { { &P::attack, 0.003f }, { &P::decay, 0.3f }, { &P::sustain, 0.7f }, { &P::release, 0.1f },
                                            { &P::cutoff, 900.0f }, { &P::resonance, 0.2f }, { &P::fenvAmount, 1.5f }, { &P::fenvDecay, 0.15f },
                                            { &P::shape, 1.0f }, { &P::osc2, 0.0f }, { &P::sub, 0.3f }, { &P::keytrack, 0.6f }, { &P::gain, 0.32f } }) },
    };
    return presets;
}

//==============================================================================
VoiceBank::VoiceBank (int numVoices) : voices ((size_t) numVoices) {}

void VoiceBank::prepare (double sampleRate)
{
    sr = sampleRate;
    reset();
}

void VoiceBank::reset()
{
    for (auto& v : voices) v = Voice {};
}

void VoiceBank::noteOn (int note, float velocity)
{
    Voice* target = nullptr;
    for (auto& v : voices)
        if (v.stage == Off) { target = &v; break; }

    if (target == nullptr)
    {
        // Steal the oldest releasing voice, otherwise the oldest voice.
        for (auto& v : voices)
            if (v.stage == Release && (target == nullptr || v.age > target->age)) target = &v;
        if (target == nullptr)
            for (auto& v : voices)
                if (target == nullptr || v.age > target->age) target = &v;
    }

    auto& v = *target;
    const bool stolen = v.stage != Off;
    v.stage = Attack;
    v.note = note;
    v.freq = (float) (440.0 * std::pow (2.0, (note - 69) / 12.0));
    v.vel = velocity;
    if (stolen)
        v.env *= 0.5f;
    else
    {
        v.env = 0.0f;
        v.ic1 = v.ic2 = 0.0f;
        v.ph1 = v.ph2 = v.ph3 = v.ph4 = 0.0;
    }
    v.fenv = v.modenv = v.tineenv = 1.0f;
    v.age = 0;
}

void VoiceBank::noteOff (int note)
{
    for (auto& v : voices)
        if (v.note == note && v.stage != Off && v.stage != Release)
            v.stage = Release;
}

void VoiceBank::allNotesOff()
{
    for (auto& v : voices)
        if (v.stage != Off) v.stage = Release;
}

void VoiceBank::render (float* out, int n)
{
    const auto& p = params;
    const double lfoInc = p.lfoRate / sr;
    const double nyquist = 0.45 * sr;

    const float aRate = (float) (1.0 / (std::max (p.attack, 0.001f) * sr));
    const float dCoef = (float) std::exp (-4.0 / (std::max (p.decay, 0.005f) * sr));
    const float rCoef = (float) std::exp (-4.0 / (std::max (p.release, 0.005f) * sr));
    const float fCoef = (float) std::exp (-4.0 / (std::max (p.fenvDecay, 0.005f) * sr));
    const float mCoef = (float) std::exp (-4.0 / (std::max (p.fmDecay, 0.005f) * sr));
    const float tCoef = (float) std::exp (-4.0 / (0.04 * sr));
    const float k = 2.0f - 1.95f * juce::jlimit (0.0f, 1.0f, p.resonance);
    const double detune = std::pow (2.0, p.detune / 1200.0);

    for (auto& v : voices)
    {
        if (v.stage == Off)
            continue;

        const float ampVel = 1.0f - p.velocitySens + p.velocitySens * v.vel;
        const float idxVel = 0.4f + 0.6f * v.vel;
        const float keytrack = (float) std::pow (v.freq / 261.63, (double) p.keytrack);

        float a1 = 0, a2 = 0, a3 = 0, trem = 1.0f;
        double dt1 = 0, dt2 = 0, dt3 = 0, dt4 = 0;

        for (int i = 0; i < n; ++i)
        {
            if (i % subBlock == 0)
            {
                const double lfo = std::sin (twoPi * (lfoPhase + i * lfoInc));
                const double f = v.freq * std::pow (2.0, p.vibrato * lfo / 1200.0);
                trem = 1.0f - p.tremolo * (float) (0.5 + 0.5 * lfo);
                double fc = p.cutoff * cutoffScale * keytrack
                            * std::pow (2.0, p.fenvAmount * v.fenv + p.lfoCutoff * lfo);
                fc = juce::jlimit (20.0, nyquist, fc);
                const float g = (float) std::tan (juce::MathConstants<double>::pi * fc / sr);
                a1 = 1.0f / (1.0f + g * (g + k));
                a2 = g * a1;
                a3 = g * a2;
                dt1 = f / sr;
                switch (p.engine)
                {
                    case Engine::Analog: dt2 = f * detune / sr; dt3 = 0.5 * f / sr; break;
                    case Engine::FM:     dt2 = f * p.fmRatio / sr; break;
                    case Engine::EPiano: dt2 = f / sr; dt3 = f / sr; dt4 = 14.0 * f / sr; break;
                }
            }

            if (v.stage == Attack)
            {
                v.env += aRate;
                if (v.env >= 1.0f) { v.env = 1.0f; v.stage = Decay; }
            }
            else if (v.stage == Decay)
                v.env = p.sustain + (v.env - p.sustain) * dCoef;
            else
            {
                v.env *= rCoef;
                if (v.env < 1.0e-4f) { v.stage = Off; break; }
            }
            v.fenv *= fCoef;
            v.modenv *= mCoef;
            v.tineenv *= tCoef;

            float x = 0.0f;
            switch (p.engine)
            {
                case Engine::Analog:
                    x = oscillator (v.ph1, dt1, p.shape) + p.osc2 * oscillator (v.ph2, dt2, p.shape)
                        + p.sub * (float) std::sin (twoPi * v.ph3);
                    if (p.noise > 0.0f) x += p.noise * (2.0f * random.nextFloat() - 1.0f);
                    x *= 0.5f;
                    break;
                case Engine::FM:
                {
                    const float index = (p.fmSustainIndex + (p.fmIndex - p.fmSustainIndex) * v.modenv) * idxVel;
                    x = (float) std::sin (twoPi * v.ph1 + index * std::sin (twoPi * v.ph2));
                    break;
                }
                case Engine::EPiano:
                {
                    const float index = (p.fmSustainIndex + (p.fmIndex - p.fmSustainIndex) * v.modenv) * idxVel;
                    const float body = (float) std::sin (twoPi * v.ph1 + index * std::sin (twoPi * v.ph2));
                    const float bark = (float) std::sin (twoPi * v.ph3 + 2.5 * v.tineenv * idxVel * std::sin (twoPi * v.ph4));
                    x = body + p.tine * v.tineenv * bark;
                    break;
                }
            }

            v.ph1 += dt1; wrap (v.ph1);
            v.ph2 += dt2; wrap (v.ph2);
            v.ph3 += dt3; wrap (v.ph3);
            v.ph4 += dt4; wrap (v.ph4);

            // TPT state-variable low-pass
            const float v3 = x - v.ic2;
            const float v1 = a1 * v.ic1 + a2 * v3;
            const float v2 = v.ic2 + a2 * v.ic1 + a3 * v3;
            v.ic1 = 2.0f * v1 - v.ic1;
            v.ic2 = 2.0f * v2 - v.ic2;

            out[i] += v2 * v.env * ampVel * trem * p.gain;
        }
        v.age += n;
    }

    lfoPhase = std::fmod (lfoPhase + n * lfoInc, 1.0);
}

//==============================================================================
void Chorus::prepare (double sampleRate)
{
    sr = sampleRate;
    buffer.assign ((size_t) (0.05 * sampleRate), 0.0f);
    writeIndex = 0;
}

void Chorus::process (const float* mono, float* left, float* right, int n, float mix)
{
    const int size = (int) buffer.size();
    const double inc = 0.6 / sr;
    const double base = 0.007 * sr, depth = 0.003 * sr;
    float* outs[2] = { left, right };

    for (int i = 0; i < n; ++i)
    {
        const float x = mono[i];
        buffer[(size_t) writeIndex] = x;
        for (int ch = 0; ch < 2; ++ch)
        {
            const double lfo = std::sin (twoPi * (phase + 0.5 * ch));
            double r = writeIndex - (base + depth * (0.5 + 0.5 * lfo));
            while (r < 0) r += size;
            const int i0 = (int) r;
            const float frac = (float) (r - i0);
            const float wet = buffer[(size_t) i0] * (1.0f - frac) + buffer[(size_t) ((i0 + 1) % size)] * frac;
            outs[ch][i] = x * (1.0f - 0.5f * mix) + wet * mix;
        }
        writeIndex = (writeIndex + 1) % size;
        phase += inc;
        if (phase >= 1.0) phase -= 1.0;
    }
}

//==============================================================================
void PingPongDelay::prepare (double sampleRate)
{
    bufL.assign ((size_t) (2.5 * sampleRate), 0.0f);
    bufR.assign ((size_t) (2.5 * sampleRate), 0.0f);
    writeIndex = 0;
}

void PingPongDelay::reset()
{
    std::fill (bufL.begin(), bufL.end(), 0.0f);
    std::fill (bufR.begin(), bufR.end(), 0.0f);
}

void PingPongDelay::process (float* left, float* right, int n, float delaySamples, float feedback, float mix)
{
    const int size = (int) bufL.size();
    const int d = juce::jlimit (1, size - 1, (int) delaySamples);
    for (int i = 0; i < n; ++i)
    {
        int r = writeIndex - d;
        if (r < 0) r += size;
        const float dl = bufL[(size_t) r], dr = bufR[(size_t) r];
        bufL[(size_t) writeIndex] = 0.5f * (left[i] + right[i]) + dr * feedback;
        bufR[(size_t) writeIndex] = dl * feedback;
        left[i] += dl * mix;
        right[i] += dr * mix;
        writeIndex = (writeIndex + 1) % size;
    }
}
}
