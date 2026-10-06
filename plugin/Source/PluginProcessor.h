#pragma once

#include "ChordEngine.h"

#include <juce_audio_processors/juce_audio_processors.h>

#define LIRIO_PARAMS(X)     X (sound) X (perform) X (arpRate) X (pattern) X (key) X (keyMode) X (style) X (voicing)     X (voicingMode) X (bassVoicing) X (bassOn) X (bassSound) X (bassLevel) X (latch) X (tone)     X (chorus) X (delay) X (space) X (drive) X (level) X (octave) X (chordInput) X (midiOut) X (knobMap)

class LirioProcessor : public juce::AudioProcessor,
                       private juce::Timer
{
public:
    LirioProcessor();

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override                          { return true; }

    const juce::String getName() const override              { return JucePlugin_Name; }
    bool acceptsMidi() const override                        { return true; }
    bool producesMidi() const override                       { return true; }
    bool isMidiEffect() const override                       { return false; }
    double getTailLengthSeconds() const override             { return 3.0; }

    int getNumPrograms() override                            { return 1; }
    int getCurrentProgram() override                         { return 0; }
    void setCurrentProgram (int) override                    {}
    const juce::String getProgramName (int) override         { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    static juce::StringArray choicesFor (const juce::String& paramId);

    juce::AudioProcessorValueTreeState state;
    sl::ChordEngine engine;

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout createLayout();
    sl::EngineSettings readSettings() const;
    void timerCallback() override;

    // Hardware knobs (CC 70-77, the Akai MPK layout). The audio thread stores the latest
    // value per knob; the message thread turns it into a parameter change.
    static constexpr int firstKnobCC = 70, numKnobs = 8;
    std::array<std::atomic<int>, numKnobs> pendingKnobs;

    // Raw parameter values, cached once so the audio thread never looks them up by name.
    struct RawParams
    {
       #define LIRIO_DECLARE(name) std::atomic<float>* name = nullptr;
        LIRIO_PARAMS (LIRIO_DECLARE)
       #undef LIRIO_DECLARE
    } raw;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (LirioProcessor)
};
