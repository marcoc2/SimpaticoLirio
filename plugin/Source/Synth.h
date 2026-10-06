#pragma once

#include <juce_audio_basics/juce_audio_basics.h>

#include <array>
#include <vector>

// Voice engines and effects, ported from lirio_proto/dsp.py and lirio_proto/synth.py.
namespace sl
{
enum class Engine : int { Analog = 0, FM = 1, EPiano = 2 };

struct VoiceParams
{
    Engine engine = Engine::Analog;
    float attack = 0.005f, decay = 0.5f, sustain = 0.7f, release = 0.4f;
    float cutoff = 4000.0f, resonance = 0.1f, fenvAmount = 0.0f, fenvDecay = 0.3f;
    float detune = 8.0f, osc2 = 0.7f, sub = 0.0f, shape = 0.0f;
    float fmRatio = 1.0f, fmIndex = 1.0f, fmDecay = 0.5f, fmSustainIndex = 0.3f;
    float lfoRate = 5.0f, vibrato = 0.0f, tremolo = 0.0f, lfoCutoff = 0.0f;
    float gain = 0.25f, velocitySens = 0.6f, tine = 0.0f, keytrack = 0.3f, noise = 0.0f;
};

struct Preset
{
    const char* name;
    VoiceParams params;
};

const std::vector<Preset>& getPresets();
const std::vector<Preset>& getBassPresets();

//==============================================================================
/** Polyphonic voice bank. All engines share the SVF low-pass and the amp envelope. */
class VoiceBank
{
public:
    explicit VoiceBank (int numVoices);

    void prepare (double sampleRate);
    void setParams (const VoiceParams& p)   { params = p; }
    void setCutoffScale (float s)           { cutoffScale = s; }

    void noteOn (int note, float velocity);
    void noteOff (int note);
    void allNotesOff();
    void reset();

    /** Adds numSamples of mono output into out. */
    void render (float* out, int numSamples);

private:
    enum Stage { Off, Attack, Decay, Release };

    struct Voice
    {
        Stage stage = Off;
        int note = -1;
        float freq = 440.0f, vel = 1.0f;
        float env = 0.0f, fenv = 0.0f, modenv = 0.0f, tineenv = 0.0f;
        double ph1 = 0, ph2 = 0, ph3 = 0, ph4 = 0;
        float ic1 = 0, ic2 = 0;
        int64_t age = 0;
    };

    std::vector<Voice> voices;
    VoiceParams params;
    double sr = 48000.0;
    double lfoPhase = 0.0;
    float cutoffScale = 1.0f;
    juce::Random random;
};

//==============================================================================
/** Mono in, stereo out modulated delay. */
class Chorus
{
public:
    void prepare (double sampleRate);
    void process (const float* mono, float* left, float* right, int n, float mix);

private:
    std::vector<float> buffer;
    int writeIndex = 0;
    double phase = 0.0, sr = 48000.0;
};

/** Tempo-synced ping-pong delay, in place. */
class PingPongDelay
{
public:
    void prepare (double sampleRate);
    void process (float* left, float* right, int n, float delaySamples, float feedback, float mix);
    void reset();

private:
    std::vector<float> bufL, bufR;
    int writeIndex = 0;
};
}
