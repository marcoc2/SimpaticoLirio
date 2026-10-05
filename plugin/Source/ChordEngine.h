#pragma once

#include "Performer.h"
#include "Synth.h"
#include "Theory.h"

#include <juce_audio_basics/juce_audio_basics.h>

#include <array>

// The instrument: chord state, MIDI in/out, perform modes, sound. Ported from handful_proto/engine.py.
// Everything here runs on the audio thread, except postUiEvent() and getSnapshot().
namespace hf
{
/** Values read from the plugin parameters at the start of every block. */
struct EngineSettings
{
    int sound = 2, bassSound = 0;
    PerformMode perform = PerformMode::Block;
    int arpRate = 3, pattern = 0;
    int keyIndex = 0;          // 0-11 major, 12-23 minor
    bool keyMode = false;
    Playstyle style = Playstyle::Advanced;
    int voicing = 0;
    bool splitVoicing = false;
    int bassVoicing = 0;
    bool bassOn = true;
    bool latch = false;
    float tone = 0.5f, chorus = 0.5f, delay = 0.2f, space = 0.4f, drive = 0.0f;
    float bassLevel = 0.8f, level = 0.8f;
    int chordInput = 0;        // 0 = pads ch.10 notes 36-43, 1 = keys 24-31
    bool midiOut = true;
};

struct TransportInfo
{
    double bpm = 110.0;
    bool playing = false;
    bool hasPpq = false;
    double ppq = 0.0;
};

struct UiEvent
{
    enum Type : int { Key, ButtonToggle, Panic } type;
    int a = 0;   // note or button
    int b = 0;   // velocity (0 = release) or on/off
};

/** What the editor shows. Plain data so it can be copied out of the audio thread. */
struct Snapshot
{
    char label[32] {};
    std::array<int, 24> notes {};
    int numNotes = 0;
    int root = -1;
    int bass = -1;
    uint32_t buttons = 0;
    int keyNote = -1;
    double bpm = 110.0;
    bool hostPlaying = false;
    float peak = 0.0f;
};

class ChordEngine : private NoteSink
{
public:
    ChordEngine();

    void prepare (double sampleRate, int maxBlockSize);
    void process (juce::AudioBuffer<float>& audio, juce::MidiBuffer& midi,
                  const EngineSettings& settings, const TransportInfo& transport);

    /** Message thread: queue a key / button press coming from the editor. */
    void postUiEvent (const UiEvent& e);
    /** Message thread: latest state for the editor. */
    Snapshot getSnapshot() const;

private:
    // NoteSink (perform output)
    void performNoteOn (int note, int velocity, int64_t time) override;
    void performNoteOff (int note, int64_t time) override;

    void applySettings (const EngineSettings& s);
    void handleMidi (const juce::MidiMessage& m);
    void handleUiEvent (const UiEvent& e);
    void keyDown (int note, int velocity);
    void keyUp (int note);
    void buttonDown (int b);
    void buttonUp (int b);
    void releaseLatch();
    void updateChord (bool retrigger);
    void sendMidi (const juce::MidiMessage& m, int64_t time);
    void panic();
    int activeKey (int& velocity) const;
    void writeSnapshot();
    void updateCutoff();

    double sr = 48000.0;
    int64_t clock = 0, blockStart = 0;
    int blockSize = 0;
    double gridOrigin = 0.0;
    double sixteenth = 1.0;
    TransportInfo transport;

    EngineSettings settings;
    bool firstSettings = true;

    VoiceBank voices { 16 }, bass { 3 };
    Performer performer { *this };
    Chorus chorus;
    PingPongDelay delay;
    juce::Reverb reverb;
    juce::AudioBuffer<float> monoBuffer, bassBuffer;
    juce::MidiBuffer midiInput;

    // Chord state
    struct HeldKey { int note; int velocity; };
    std::array<HeldKey, 16> heldKeys {};
    int numHeldKeys = 0;
    ButtonStack buttons;
    bool sustainPedal = false;
    int voicingBend = 0;        // joystick X (pitch bend): temporary voicing offset
    float joystickTone = 0.0f;  // joystick Y (CC 1): opens the filter
    float toneScale = 1.0f;
    int latchedNote = -1, latchedVelocity = 100;
    NoteList chordNotes;
    int chordRoot = -1, soundingBass = -1;
    char chordLabel[32] {};

    juce::MidiBuffer* midiOut = nullptr;
    int64_t currentTime = 0;
    float peak = 0.0f;

    // UI -> audio
    juce::AbstractFifo uiFifo { 256 };
    std::array<UiEvent, 256> uiEvents {};
    juce::SpinLock uiWriteLock;

    // audio -> UI
    mutable juce::SpinLock snapshotLock;
    Snapshot snapshot;
};
}
