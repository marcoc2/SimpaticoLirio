#pragma once

#include "PluginProcessor.h"

#include <juce_gui_extra/juce_gui_extra.h>

/** The front panel is the web page in ui/index.html, embedded as binary data and shown
    in a WebView2 browser. Events flow both ways through window.__JUCE__.backend. */
class LirioEditor : public juce::AudioProcessorEditor,
                    private juce::Timer
{
public:
    explicit LirioEditor (LirioProcessor&);
    ~LirioEditor() override;

    void resized() override;
    void paint (juce::Graphics&) override;

private:
    void timerCallback() override;
    void handleUiMessage (const juce::var& message);
    void sendMeta();
    juce::var buildState() const;
    std::optional<juce::WebBrowserComponent::Resource> getResource (const juce::String& url) const;

    LirioProcessor& processor;
    juce::WebBrowserComponent browser;
    bool pageReady = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (LirioEditor)
};
