#pragma once

#include "Theory.h"

#include <juce_core/juce_core.h>

#include <array>
#include <cstdint>

// Perform modes, ported from handful_proto/perform.py. Timing runs on an absolute sample clock;
// clocked modes (arp, pattern) lock to a sixteenth grid derived from the host tempo.
namespace hf
{
enum class PerformMode : int { Block, Strum, Strum2Oct, Slop, Arp, Arp2Oct, Pattern, Harp, NumModes };

class NoteSink
{
public:
    virtual ~NoteSink() = default;
    virtual void performNoteOn (int note, int velocity, int64_t time) = 0;
    virtual void performNoteOff (int note, int64_t time) = 0;
};

class Performer
{
public:
    static constexpr int numArpRates = 6;
    static constexpr int numPatterns = 5;
    static const char* arpRateName (int index);
    static const char* patternName (int index);

    explicit Performer (NoteSink& sink) : sink (sink) {}

    void prepare (double sampleRate)      { sr = sampleRate; allOff(); }
    void setMode (PerformMode m);
    PerformMode getMode() const           { return mode; }
    void setArpRate (int index)           { arpRate = juce::jlimit (0, numArpRates - 1, index); }
    void setPattern (int index)           { pattern = juce::jlimit (0, numPatterns - 1, index); }

    /** Called whenever the generated chord changes. An empty list means release. */
    void chordChanged (const NoteList& notes, int velocity);
    void allOff();

    /** Emits every event inside [blockStart, blockStart + numSamples). */
    void process (int64_t blockStart, int numSamples, double sixteenthSamples, double gridOrigin);

    bool isSounding (int note) const      { return note >= 0 && note < 128 && sounding[(size_t) note]; }

private:
    struct Event { int64_t time; uint32_t seq; bool on; int note; int velocity; };

    void schedule (int64_t time, bool on, int note, int velocity = 0);
    void cancelPendingNoteOns();
    void noteOn (int note, int velocity, int64_t time);
    void noteOff (int note, int64_t time);
    double stepLength() const;
    void fireStep (int64_t time, double stepLen, int64_t stepNumber);
    bool isClocked() const { return mode == PerformMode::Arp || mode == PerformMode::Arp2Oct || mode == PerformMode::Pattern; }

    NoteSink& sink;
    double sr = 48000.0;
    PerformMode mode = PerformMode::Block;
    int arpRate = 3, pattern = 0;
    float strumMs = 28.0f, slopMs = 70.0f, harpMs = 22.0f, gate = 0.6f;

    NoteList notes;
    int velocity = 100;
    std::array<bool, 128> sounding {};
    std::array<Event, 512> queue {};
    int queueSize = 0;
    uint32_t seq = 0;
    int arpIndex = 0;
    int64_t lastTick = INT64_MIN;
    int64_t now = 0;
    double sixteenth = 1.0, origin = 0.0;
    juce::Random random;
};
}
