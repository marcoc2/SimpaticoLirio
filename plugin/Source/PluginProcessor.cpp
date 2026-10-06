#include "PluginProcessor.h"
#include "PluginEditor.h"

namespace
{
const juce::StringArray noteNames { "C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B" };

juce::StringArray presetNames (const std::vector<sl::Preset>& presets)
{
    juce::StringArray names;
    for (const auto& p : presets) names.add (p.name);
    return names;
}
}

juce::StringArray LirioProcessor::choicesFor (const juce::String& id)
{
    if (id == "sound")       return presetNames (sl::getPresets());
    if (id == "bassSound")   return presetNames (sl::getBassPresets());
    if (id == "perform")     return { "Block", "Strum", "Strum 2 Oct", "Slop", "Arp", "Arp 2 Oct", "Pattern", "Harp" };
    if (id == "style")       return { "Simple", "Advanced", "Free" };
    if (id == "voicingMode") return { "Octave", "Split" };
    if (id == "chordInput")  return { "Pads ch.10 (36-43)", "Lowest keys (24-31)" };
    if (id == "knobMap")     return { "Akai MPK (CC 70-77)", "Off" };
    if (id == "arpRate")
    {
        juce::StringArray s;
        for (int i = 0; i < sl::Performer::numArpRates; ++i) s.add (sl::Performer::arpRateName (i));
        return s;
    }
    if (id == "pattern")
    {
        juce::StringArray s;
        for (int i = 0; i < sl::Performer::numPatterns; ++i) s.add (sl::Performer::patternName (i));
        return s;
    }
    if (id == "key")
    {
        juce::StringArray s;
        for (const auto& scale : { "major", "minor" })
            for (const auto& n : noteNames) s.add (n + " " + scale);
        return s;
    }
    return {};
}

juce::AudioProcessorValueTreeState::ParameterLayout LirioProcessor::createLayout()
{
    using namespace juce;
    AudioProcessorValueTreeState::ParameterLayout layout;

    auto choice = [&] (const char* id, const char* name, int defaultIndex)
    {
        layout.add (std::make_unique<AudioParameterChoice> (ParameterID { id, 1 }, name, choicesFor (id), defaultIndex));
    };
    auto integer = [&] (const char* id, const char* name, int lo, int hi, int def)
    {
        layout.add (std::make_unique<AudioParameterInt> (ParameterID { id, 1 }, name, lo, hi, def));
    };
    auto toggle = [&] (const char* id, const char* name, bool def)
    {
        layout.add (std::make_unique<AudioParameterBool> (ParameterID { id, 1 }, name, def));
    };
    auto amount = [&] (const char* id, const char* name, float hi, float def)
    {
        layout.add (std::make_unique<AudioParameterFloat> (ParameterID { id, 1 }, name, NormalisableRange<float> { 0.0f, hi }, def));
    };

    choice ("sound", "Sound", 2);
    choice ("perform", "Perform", 0);
    choice ("arpRate", "Rate", 3);
    choice ("pattern", "Pattern", 0);
    choice ("key", "Key", 0);
    toggle ("keyMode", "Key Mode", false);
    choice ("style", "Playstyle", 1);
    integer ("voicing", "Voicing", -12, 12, 0);
    choice ("voicingMode", "Voicing Mode", 0);
    integer ("bassVoicing", "Bass Voicing", -4, 4, 0);
    toggle ("bassOn", "Bass", true);
    choice ("bassSound", "Bass Sound", 0);
    amount ("bassLevel", "Bass Level", 1.5f, 0.8f);
    toggle ("latch", "Latch", false);
    amount ("tone", "Tone", 1.0f, 0.5f);
    amount ("chorus", "Chorus", 1.0f, 0.5f);
    amount ("delay", "Delay", 1.0f, 0.2f);
    amount ("space", "Space", 1.0f, 0.4f);
    amount ("drive", "Drive", 1.0f, 0.0f);
    amount ("level", "Level", 1.5f, 0.8f);
    integer ("octave", "Keys Octave", 1, 7, 4);
    choice ("chordInput", "Chord Buttons Input", 0);
    toggle ("midiOut", "MIDI Out", true);
    choice ("knobMap", "Hardware Knobs", 0);
    return layout;
}

//==============================================================================
LirioProcessor::LirioProcessor()
    : AudioProcessor (BusesProperties().withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      state (*this, nullptr, "SimpaticoLirioState", createLayout())
{
   #define LIRIO_INIT(name) raw.name = state.getRawParameterValue (#name); jassert (raw.name != nullptr);
    LIRIO_PARAMS (LIRIO_INIT)
   #undef LIRIO_INIT

    for (auto& k : pendingKnobs) k.store (-1);
    startTimerHz (60);
}

void LirioProcessor::timerCallback()
{
    // Knob bank A (red): voicing, bass voicing, sound, perform.
    // Knob bank B (green): tone, rate (pattern while in Pattern mode), delay, space.
    const bool patternMode = (int) raw.perform->load() == (int) sl::PerformMode::Pattern;
    const char* targets[numKnobs] = { "voicing", "bassVoicing", "sound", "perform",
                                      "tone", patternMode ? "pattern" : "arpRate", "delay", "space" };
    for (int i = 0; i < numKnobs; ++i)
    {
        const int value = pendingKnobs[(size_t) i].exchange (-1);
        if (value < 0)
            continue;
        if (auto* param = state.getParameter (targets[i]))
        {
            param->beginChangeGesture();
            param->setValueNotifyingHost ((float) value / 127.0f);
            param->endChangeGesture();
        }
    }
}

sl::EngineSettings LirioProcessor::readSettings() const
{
    sl::EngineSettings s;
    s.sound = (int) raw.sound->load();
    s.bassSound = (int) raw.bassSound->load();
    s.perform = (sl::PerformMode) (int) raw.perform->load();
    s.arpRate = (int) raw.arpRate->load();
    s.pattern = (int) raw.pattern->load();
    s.keyIndex = (int) raw.key->load();
    s.keyMode = raw.keyMode->load() > 0.5f;
    s.style = (sl::Playstyle) (int) raw.style->load();
    s.voicing = (int) raw.voicing->load();
    s.splitVoicing = (int) raw.voicingMode->load() == 1;
    s.bassVoicing = (int) raw.bassVoicing->load();
    s.bassOn = raw.bassOn->load() > 0.5f;
    s.latch = raw.latch->load() > 0.5f;
    s.tone = raw.tone->load();
    s.chorus = raw.chorus->load();
    s.delay = raw.delay->load();
    s.space = raw.space->load();
    s.drive = raw.drive->load();
    s.bassLevel = raw.bassLevel->load();
    s.level = raw.level->load();
    s.chordInput = (int) raw.chordInput->load();
    s.midiOut = raw.midiOut->load() > 0.5f;
    return s;
}

void LirioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    engine.prepare (sampleRate, samplesPerBlock);
}

bool LirioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    const auto& out = layouts.getMainOutputChannelSet();
    return out == juce::AudioChannelSet::stereo() || out == juce::AudioChannelSet::mono();
}

void LirioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi)
{
    juce::ScopedNoDenormals noDenormals;

    sl::TransportInfo transport;
    if (auto* head = getPlayHead())
    {
        if (const auto pos = head->getPosition())
        {
            if (const auto bpm = pos->getBpm()) transport.bpm = *bpm;
            transport.playing = pos->getIsPlaying();
            if (const auto ppq = pos->getPpqPosition())
            {
                transport.hasPpq = true;
                transport.ppq = *ppq;
            }
        }
    }

    if ((int) raw.knobMap->load() == 0)
    {
        for (const auto meta : midi)
        {
            const auto m = meta.getMessage();
            if (m.isController() && m.getControllerNumber() >= firstKnobCC
                && m.getControllerNumber() < firstKnobCC + numKnobs)
                pendingKnobs[(size_t) (m.getControllerNumber() - firstKnobCC)].store (m.getControllerValue());
        }
    }

    engine.process (buffer, midi, readSettings(), transport);
}

//==============================================================================
juce::AudioProcessorEditor* LirioProcessor::createEditor()
{
    return new LirioEditor (*this);
}

void LirioProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    if (auto xml = state.copyState().createXml())
        copyXmlToBinary (*xml, destData);
}

void LirioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    if (auto xml = getXmlFromBinary (data, sizeInBytes))
        if (xml->hasTagName (state.state.getType()))
            state.replaceState (juce::ValueTree::fromXml (*xml));
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new LirioProcessor();
}
