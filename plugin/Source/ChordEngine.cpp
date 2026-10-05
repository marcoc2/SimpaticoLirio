#include "ChordEngine.h"

#include <cmath>
#include <cstdio>
#include <cstring>

namespace hf
{
namespace
{
constexpr int chunkSize = 32;
constexpr int chPerform = 1, chBass = 2, chChord = 3;

// Pads on channel 10, notes 36-43: top row (40-43) = chord types, bottom row (36-39) = extensions.
int padButton (int note)
{
    if (note >= 40 && note <= 43) return Dim + (note - 40);
    if (note >= 36 && note <= 39) return Six + (note - 36);
    return -1;
}

// Lowest keys, notes 24-27 = chord types, 28-31 = extensions.
int lowKeyButton (int note)
{
    if (note >= 24 && note <= 31) return note - 24;
    return -1;
}
}

ChordEngine::ChordEngine() = default;

void ChordEngine::prepare (double sampleRate, int maxBlockSize)
{
    sr = sampleRate;
    voices.prepare (sr);
    bass.prepare (sr);
    performer.prepare (sr);
    chorus.prepare (sr);
    delay.prepare (sr);
    reverb.setSampleRate (sr);
    reverb.reset();
    monoBuffer.setSize (1, maxBlockSize);
    bassBuffer.setSize (1, maxBlockSize);
    midiInput.ensureSize (4096);
    firstSettings = true;
}

//==============================================================================
void ChordEngine::postUiEvent (const UiEvent& e)
{
    const juce::SpinLock::ScopedLockType lock (uiWriteLock);
    const auto scope = uiFifo.write (1);
    if (scope.blockSize1 > 0) uiEvents[(size_t) scope.startIndex1] = e;
    else if (scope.blockSize2 > 0) uiEvents[(size_t) scope.startIndex2] = e;
}

Snapshot ChordEngine::getSnapshot() const
{
    const juce::SpinLock::ScopedLockType lock (snapshotLock);
    return snapshot;
}

void ChordEngine::writeSnapshot()
{
    const juce::SpinLock::ScopedTryLockType lock (snapshotLock);
    if (! lock.isLocked())
        return;
    std::memcpy (snapshot.label, chordLabel, sizeof (chordLabel));
    snapshot.numNotes = chordNotes.size;
    for (int i = 0; i < chordNotes.size; ++i) snapshot.notes[(size_t) i] = chordNotes[i];
    snapshot.root = chordRoot;
    snapshot.bass = soundingBass;
    snapshot.buttons = buttons.mask();
    int vel = 0;
    snapshot.keyNote = activeKey (vel);
    snapshot.bpm = transport.bpm;
    snapshot.hostPlaying = transport.playing;
    snapshot.peak = peak;
}

//==============================================================================
void ChordEngine::sendMidi (const juce::MidiMessage& m, int64_t time)
{
    if (midiOut == nullptr || ! settings.midiOut)
        return;
    const int offset = (int) juce::jlimit<int64_t> (0, std::max (0, blockSize - 1), time - blockStart);
    midiOut->addEvent (m, offset);
}

void ChordEngine::performNoteOn (int note, int velocity, int64_t time)
{
    voices.noteOn (note, (float) velocity / 127.0f);
    sendMidi (juce::MidiMessage::noteOn (chPerform, note, (juce::uint8) velocity), time);
}

void ChordEngine::performNoteOff (int note, int64_t time)
{
    voices.noteOff (note);
    sendMidi (juce::MidiMessage::noteOff (chPerform, note), time);
}

void ChordEngine::panic()
{
    performer.allOff();
    voices.allNotesOff();
    bass.allNotesOff();
    numHeldKeys = 0;
    latchedNote = -1;
    voicingBend = 0;
    joystickTone = 0.0f;
    updateCutoff();
    for (int ch : { chPerform, chBass, chChord })
        sendMidi (juce::MidiMessage::allNotesOff (ch), currentTime);
    chordNotes = {};
    chordRoot = -1;
    soundingBass = -1;
    chordLabel[0] = 0;
}

//==============================================================================
void ChordEngine::applySettings (const EngineSettings& s)
{
    const auto old = settings;
    settings = s;
    const bool first = firstSettings;
    firstSettings = false;

    const auto& presets = getPresets();
    const auto& bassPresets = getBassPresets();
    if (first || s.sound != old.sound)
        voices.setParams (presets[(size_t) juce::jlimit (0, (int) presets.size() - 1, s.sound)].params);
    if (first || s.bassSound != old.bassSound)
        bass.setParams (bassPresets[(size_t) juce::jlimit (0, (int) bassPresets.size() - 1, s.bassSound)].params);
    toneScale = (float) std::pow (2.0, (s.tone - 0.5) * 5.0);
    updateCutoff();

    performer.setArpRate (s.arpRate);
    performer.setPattern (s.pattern);
    if (s.perform != performer.getMode())
        performer.setMode (s.perform);

    if (! first && old.midiOut && ! s.midiOut && midiOut != nullptr)
        for (int ch : { chPerform, chBass, chChord })
            midiOut->addEvent (juce::MidiMessage::allNotesOff (ch), 0);

    if (old.latch && ! s.latch && ! sustainPedal)
        releaseLatch();

    const bool chordChanged = first || s.keyIndex != old.keyIndex || s.keyMode != old.keyMode
                              || s.style != old.style || s.voicing != old.voicing
                              || s.splitVoicing != old.splitVoicing || s.bassVoicing != old.bassVoicing
                              || s.bassOn != old.bassOn;
    if (chordChanged)
        updateChord (false);
}

void ChordEngine::updateCutoff()
{
    voices.setCutoffScale (toneScale * (float) std::pow (2.0, 3.0 * joystickTone));
}

//==============================================================================
void ChordEngine::handleUiEvent (const UiEvent& e)
{
    switch (e.type)
    {
        case UiEvent::Key:
            if (e.b > 0) keyDown (e.a, e.b); else keyUp (e.a);
            break;
        case UiEvent::ButtonToggle:
            if (e.a >= 0 && e.a < NumButtons)
            {
                if (e.b != 0) buttonDown (e.a); else buttonUp (e.a);
            }
            break;
        case UiEvent::Panic:
            panic();
            break;
    }
}

void ChordEngine::handleMidi (const juce::MidiMessage& m)
{
    if (m.isNoteOnOrOff())
    {
        const bool down = m.isNoteOn();
        const int note = m.getNoteNumber();
        int button = -1;
        if (settings.chordInput == 0 && m.getChannel() == 10) button = padButton (note);
        if (settings.chordInput == 1) button = lowKeyButton (note);

        if (button >= 0)
        {
            if (down) buttonDown (button); else buttonUp (button);
            return;
        }
        if (settings.chordInput == 0 && m.getChannel() == 10)
            return; // other drum pads do nothing
        if (down) keyDown (note, m.getVelocity());
        else      keyUp (note);
    }
    else if (m.isSustainPedalOn())
        sustainPedal = true;
    else if (m.isSustainPedalOff())
    {
        sustainPedal = false;
        if (! settings.latch) releaseLatch();
    }
    else if (m.isPitchWheel())
    {
        // Joystick X: sweep through inversions while held, back to the dial when released.
        const int bend = (int) std::lround ((m.getPitchWheelValue() - 8192) / 8192.0 * 4.0);
        if (bend != voicingBend)
        {
            voicingBend = bend;
            updateChord (false);
        }
    }
    else if (m.isController() && m.getControllerNumber() == 1)
    {
        // Joystick Y / mod wheel: open the filter.
        joystickTone = (float) m.getControllerValue() / 127.0f;
        updateCutoff();
    }
    else if (m.isAllNotesOff() || m.isAllSoundOff())
        panic();
}

void ChordEngine::keyDown (int note, int velocity)
{
    int w = 0;
    for (int i = 0; i < numHeldKeys; ++i)
        if (heldKeys[(size_t) i].note != note) heldKeys[(size_t) w++] = heldKeys[(size_t) i];
    numHeldKeys = w;
    if (numHeldKeys == (int) heldKeys.size())
    {
        for (int i = 1; i < numHeldKeys; ++i) heldKeys[(size_t) i - 1] = heldKeys[(size_t) i];
        --numHeldKeys;
    }
    heldKeys[(size_t) numHeldKeys++] = { note, velocity };
    latchedNote = -1;
    updateChord (true);
}

void ChordEngine::keyUp (int note)
{
    int index = -1;
    for (int i = 0; i < numHeldKeys; ++i)
        if (heldKeys[(size_t) i].note == note) index = i;
    if (index < 0)
        return;

    const bool wasTop = index == numHeldKeys - 1;
    if (numHeldKeys == 1 && (settings.latch || sustainPedal))
    {
        latchedNote = heldKeys[0].note;
        latchedVelocity = heldKeys[0].velocity;
    }
    for (int i = index + 1; i < numHeldKeys; ++i) heldKeys[(size_t) i - 1] = heldKeys[(size_t) i];
    --numHeldKeys;
    if (wasTop)
        updateChord (numHeldKeys > 0);
}

void ChordEngine::buttonDown (int b)
{
    if (! buttons.contains (b)) { buttons.push (b); updateChord (false); }
}

void ChordEngine::buttonUp (int b)
{
    if (buttons.contains (b)) { buttons.remove (b); updateChord (false); }
}

void ChordEngine::releaseLatch()
{
    if (latchedNote >= 0)
    {
        latchedNote = -1;
        updateChord (false);
    }
}

int ChordEngine::activeKey (int& velocity) const
{
    if (numHeldKeys > 0)
    {
        velocity = heldKeys[(size_t) numHeldKeys - 1].velocity;
        return heldKeys[(size_t) numHeldKeys - 1].note;
    }
    velocity = latchedVelocity;
    return latchedNote;
}

void ChordEngine::updateChord (bool retrigger)
{
    int velocity = 100;
    const int key = activeKey (velocity);

    NoteList notes;
    int root = -1, newBass = -1;
    char label[32] {};

    if (key >= 0)
    {
        int defaultType = -1;
        root = key;
        if (settings.keyMode)
            keyModeChord (key, settings.keyIndex % 12, settings.keyIndex >= 12, root, defaultType);
        const auto ivs = chordIntervals (buttons, settings.style, defaultType);
        const int voicing = juce::jlimit (-24, 24, settings.voicing + voicingBend);
        notes = applyVoicing (root, ivs, voicing, settings.splitVoicing);
        chordName (root, ivs, label, (int) sizeof (label));
        if (settings.bassOn)
        {
            newBass = bassNote (root, ivs, settings.bassVoicing);
            if (newBass % 12 != root % 12 && ivs.size > 1)
            {
                const auto len = std::strlen (label);
                std::snprintf (label + len, sizeof (label) - len, "/%s", noteName (newBass));
            }
        }
    }

    const auto old = chordNotes;
    bool changed = ! (notes == old);
    NoteList previous = old;

    if (retrigger && notes.size > 0)
    {
        performer.chordChanged ({}, velocity);
        for (int i = 0; i < previous.size; ++i)
            sendMidi (juce::MidiMessage::noteOff (chChord, previous[i]), currentTime);
        previous = {};
        changed = true;
    }
    if (changed)
    {
        for (int i = 0; i < previous.size; ++i)
            if (! notes.contains (previous[i]))
                sendMidi (juce::MidiMessage::noteOff (chChord, previous[i]), currentTime);
        for (int i = 0; i < notes.size; ++i)
            if (! previous.contains (notes[i]))
                sendMidi (juce::MidiMessage::noteOn (chChord, notes[i], (juce::uint8) velocity), currentTime);
        performer.chordChanged (notes, velocity);
    }

    if (newBass != soundingBass || (retrigger && newBass >= 0))
    {
        if (soundingBass >= 0)
        {
            bass.noteOff (soundingBass);
            sendMidi (juce::MidiMessage::noteOff (chBass, soundingBass), currentTime);
        }
        if (newBass >= 0)
        {
            bass.noteOn (newBass, (float) velocity / 127.0f);
            sendMidi (juce::MidiMessage::noteOn (chBass, newBass, (juce::uint8) velocity), currentTime);
        }
        soundingBass = newBass;
    }

    chordNotes = notes;
    chordRoot = root;
    std::memcpy (chordLabel, label, sizeof (label));
}

//==============================================================================
void ChordEngine::process (juce::AudioBuffer<float>& audio, juce::MidiBuffer& midi,
                           const EngineSettings& s, const TransportInfo& t)
{
    const int n = audio.getNumSamples();
    blockStart = clock;
    blockSize = n;
    currentTime = clock;
    transport = t;
    if (transport.bpm < 20.0 || transport.bpm > 400.0) transport.bpm = 110.0;
    sixteenth = sr * 60.0 / transport.bpm / 4.0;
    if (transport.playing && transport.hasPpq)
        gridOrigin = (double) clock - transport.ppq * 4.0 * sixteenth;

    // Incoming MIDI is consumed; the buffer is refilled with our output.
    midiInput.clear();
    midiInput.addEvents (midi, 0, n, 0);
    midi.clear();
    midiOut = &midi;

    applySettings (s);

    {
        const auto scope = uiFifo.read (uiFifo.getNumReady());
        for (int i = 0; i < scope.blockSize1; ++i) handleUiEvent (uiEvents[(size_t) (scope.startIndex1 + i)]);
        for (int i = 0; i < scope.blockSize2; ++i) handleUiEvent (uiEvents[(size_t) (scope.startIndex2 + i)]);
    }

    auto* mono = monoBuffer.getWritePointer (0);
    auto* bassOut = bassBuffer.getWritePointer (0);
    juce::FloatVectorOperations::clear (mono, n);
    juce::FloatVectorOperations::clear (bassOut, n);

    auto it = midiInput.begin();
    for (int start = 0; start < n; start += chunkSize)
    {
        const int len = std::min (chunkSize, n - start);
        currentTime = clock + start;
        for (; it != midiInput.end() && (*it).samplePosition < start + len; ++it)
        {
            currentTime = clock + std::max (start, (*it).samplePosition);
            handleMidi ((*it).getMessage());
        }
        currentTime = clock + start;
        performer.process (clock + start, len, sixteenth, gridOrigin);
        voices.render (mono + start, len);
        bass.render (bassOut + start, len);
    }

    // FX: drive -> chorus -> ping-pong delay -> reverb, then the dry bass.
    if (settings.drive > 0.01f)
    {
        const float d = 1.0f + 8.0f * settings.drive, norm = 1.0f / std::tanh (d);
        for (int i = 0; i < n; ++i) mono[i] = std::tanh (mono[i] * d) * norm;
    }

    const int numCh = audio.getNumChannels();
    audio.clear();
    auto* left = audio.getWritePointer (0);
    auto* right = numCh > 1 ? audio.getWritePointer (1) : left;
    chorus.process (mono, left, right, n, settings.chorus);
    if (settings.delay > 0.001f)
        delay.process (left, right, n, (float) (0.75 * 60.0 / transport.bpm * sr), 0.38f, settings.delay * 0.7f);

    juce::Reverb::Parameters rp;
    rp.roomSize = 0.82f;
    rp.damping = 0.35f;
    rp.wetLevel = settings.space * 0.55f;
    rp.dryLevel = 1.0f - settings.space * 0.3f;
    rp.width = 1.0f;
    reverb.setParameters (rp);
    if (numCh > 1) reverb.processStereo (left, right, n);
    else           reverb.processMono (left, n);

    float blockPeak = 0.0f;
    for (int i = 0; i < n; ++i)
    {
        const float b = bassOut[i] * settings.bassLevel;
        left[i] = std::tanh ((left[i] + b) * settings.level);
        if (numCh > 1) right[i] = std::tanh ((right[i] + b) * settings.level);
        blockPeak = std::max (blockPeak, std::abs (left[i]));
    }
    peak = std::max (peak * 0.9f, blockPeak);

    clock += n;
    midiOut = nullptr;
    writeSnapshot();
}
}
