#include "PluginEditor.h"

#include <BinaryData.h>

namespace
{
constexpr int baseWidth = 1100, baseHeight = 660;

const char* mimeFor (const juce::String& file)
{
    if (file.endsWithIgnoreCase (".html")) return "text/html";
    if (file.endsWithIgnoreCase (".css"))  return "text/css";
    if (file.endsWithIgnoreCase (".js"))   return "text/javascript";
    if (file.endsWithIgnoreCase (".ttf"))  return "font/ttf";
    if (file.endsWithIgnoreCase (".svg"))  return "image/svg+xml";
    if (file.endsWithIgnoreCase (".png"))  return "image/png";
    return "application/octet-stream";
}

juce::WebBrowserComponent::Options makeOptions (HandfulEditor& editor,
                                                std::function<void (const juce::var&)> onMessage,
                                                juce::WebBrowserComponent::ResourceProvider provider)
{
    using Options = juce::WebBrowserComponent::Options;
    const auto dataFolder = juce::File::getSpecialLocation (juce::File::userApplicationDataDirectory)
                                .getChildFile ("Handful").getChildFile ("WebView2");
    juce::ignoreUnused (editor);
    return Options {}
        .withBackend (Options::Backend::webview2)
        .withWinWebView2Options (Options::WinWebView2 {}
                                     .withUserDataFolder (dataFolder)
                                     .withStatusBarDisabled()
                                     .withBuiltInErrorPageDisabled()
                                     .withBackgroundColour (juce::Colour (0xff161814)))
        .withNativeIntegrationEnabled()
        .withKeepPageLoadedWhenBrowserIsHidden()
        .withEventListener ("ui", std::move (onMessage))
        .withResourceProvider (std::move (provider));
}
}

//==============================================================================
HandfulEditor::HandfulEditor (HandfulProcessor& p)
    : AudioProcessorEditor (&p),
      processor (p),
      browser (makeOptions (*this,
                            [this] (const juce::var& m) { handleUiMessage (m); },
                            [this] (const juce::String& url) { return getResource (url); }))
{
    addAndMakeVisible (browser);
    browser.goToURL (juce::WebBrowserComponent::getResourceProviderRoot());

    setResizable (true, true);
    setResizeLimits (760, 456, 1900, 1140);
    if (auto* c = getConstrainer())
        c->setFixedAspectRatio ((double) baseWidth / baseHeight);
    setSize (baseWidth, baseHeight);

    startTimerHz (30);
}

HandfulEditor::~HandfulEditor()
{
    stopTimer();
}

void HandfulEditor::resized()
{
    browser.setBounds (getLocalBounds());
}

void HandfulEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colour (0xff161814));
}

//==============================================================================
std::optional<juce::WebBrowserComponent::Resource> HandfulEditor::getResource (const juce::String& url) const
{
    auto path = url.upToFirstOccurrenceOf ("?", false, false).trimCharactersAtStart ("/");
    if (path.isEmpty())
        path = "index.html";
    const auto fileName = path.fromLastOccurrenceOf ("/", false, false);

    for (int i = 0; i < HandfulUI::namedResourceListSize; ++i)
    {
        if (fileName == HandfulUI::originalFilenames[i])
        {
            int size = 0;
            if (const auto* data = HandfulUI::getNamedResource (HandfulUI::namedResourceList[i], size))
            {
                std::vector<std::byte> bytes ((size_t) size);
                std::memcpy (bytes.data(), data, (size_t) size);
                return juce::WebBrowserComponent::Resource { std::move (bytes), mimeFor (fileName) };
            }
        }
    }
    return std::nullopt;
}

//==============================================================================
void HandfulEditor::handleUiMessage (const juce::var& m)
{
    const auto type = m["type"].toString();

    if (type == "ready")
    {
        pageReady = true;
        sendMeta();
        return;
    }
    if (type == "key")
    {
        const int velocity = (bool) m["down"] ? juce::jlimit (1, 127, (int) m["velocity"]) : 0;
        processor.engine.postUiEvent ({ hf::UiEvent::Key, (int) m["note"], velocity });
        return;
    }
    if (type == "button")
    {
        processor.engine.postUiEvent ({ hf::UiEvent::ButtonToggle, (int) m["index"], (bool) m["on"] ? 1 : 0 });
        return;
    }
    if (type == "panic")
    {
        processor.engine.postUiEvent ({ hf::UiEvent::Panic, 0, 0 });
        return;
    }
    if (type == "gesture" || type == "param")
    {
        auto* param = processor.state.getParameter (m["id"].toString());
        if (param == nullptr)
            return;
        if (type == "gesture")
        {
            if ((bool) m["begin"]) param->beginChangeGesture();
            else                   param->endChangeGesture();
            return;
        }
        param->setValueNotifyingHost (param->convertTo0to1 ((float) (double) m["value"]));
    }
}

void HandfulEditor::sendMeta()
{
    auto* meta = new juce::DynamicObject();
    for (const auto* id : { "sound", "bassSound", "perform", "arpRate", "pattern", "key", "style", "chordInput" })
    {
        juce::Array<juce::var> list;
        for (const auto& s : HandfulProcessor::choicesFor (id)) list.add (s);
        meta->setProperty (id, list);
    }
    browser.emitEventIfBrowserIsVisible ("meta", juce::var (meta));
}

juce::var HandfulEditor::buildState() const
{
    const auto snap = processor.engine.getSnapshot();
    auto* obj = new juce::DynamicObject();
    obj->setProperty ("label", juce::String::fromUTF8 (snap.label));
    juce::Array<juce::var> notes;
    for (int i = 0; i < snap.numNotes; ++i) notes.add (snap.notes[(size_t) i]);
    obj->setProperty ("notes", notes);
    obj->setProperty ("root", snap.root);
    obj->setProperty ("bass", snap.bass);
    obj->setProperty ("buttons", (int) snap.buttons);
    obj->setProperty ("keyNote", snap.keyNote);
    obj->setProperty ("bpm", snap.bpm);
    obj->setProperty ("playing", snap.hostPlaying);
    obj->setProperty ("peak", snap.peak);

    auto* params = new juce::DynamicObject();
    for (auto* p : processor.getParameters())
        if (auto* ranged = dynamic_cast<juce::RangedAudioParameter*> (p))
            params->setProperty (ranged->getParameterID(), ranged->convertFrom0to1 (ranged->getValue()));
    obj->setProperty ("params", juce::var (params));
    return juce::var (obj);
}

void HandfulEditor::timerCallback()
{
    if (pageReady)
        browser.emitEventIfBrowserIsVisible ("state", buildState());
}
