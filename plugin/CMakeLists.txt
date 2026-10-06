cmake_minimum_required(VERSION 3.22)

project(SimpaticoLirio VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# WebView2 SDK (NuGet package), downloaded into external/nuget on first configure.
set(WEBVIEW2_VERSION 1.0.3485.44)
set(WEBVIEW2_DIR "${CMAKE_CURRENT_SOURCE_DIR}/external/nuget/Microsoft.Web.WebView2.${WEBVIEW2_VERSION}")
if(WIN32 AND NOT EXISTS "${WEBVIEW2_DIR}/build/native/include/WebView2.h")
    message(STATUS "Downloading WebView2 SDK ${WEBVIEW2_VERSION}")
    set(webview2_package "${CMAKE_BINARY_DIR}/webview2.nupkg")
    file(DOWNLOAD "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/${WEBVIEW2_VERSION}"
         "${webview2_package}" STATUS webview2_status TLS_VERIFY ON)
    list(GET webview2_status 0 webview2_code)
    if(NOT webview2_code EQUAL 0)
        message(FATAL_ERROR "Could not download the WebView2 SDK: ${webview2_status}")
    endif()
    file(ARCHIVE_EXTRACT INPUT "${webview2_package}" DESTINATION "${WEBVIEW2_DIR}")
endif()
set(JUCE_WEBVIEW2_PACKAGE_LOCATION "${CMAKE_CURRENT_SOURCE_DIR}/external/nuget" CACHE PATH "")

add_subdirectory(external/JUCE)

juce_add_plugin(SimpaticoLirio
    COMPANY_NAME "marcoc2"
    BUNDLE_ID "com.marcoc2.simpaticolirio"
    PLUGIN_MANUFACTURER_CODE Mrc2
    PLUGIN_CODE Slr1
    PRODUCT_NAME "Simpatico Lirio"
    FORMATS VST3 Standalone
    IS_SYNTH TRUE
    NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT TRUE
    IS_MIDI_EFFECT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS TRUE
    NEEDS_WEBVIEW2 TRUE
    VST3_CATEGORIES Instrument Synth
    COPY_PLUGIN_AFTER_BUILD FALSE)

juce_add_binary_data(LirioUI
    NAMESPACE LirioUI
    SOURCES
        ui/index.html
        ui/fonts/DotGothic16-Regular.ttf
        ui/fonts/BarlowSemiCondensed-Medium.ttf
        ui/fonts/BarlowSemiCondensed-SemiBold.ttf
        ui/fonts/BarlowSemiCondensed-Bold.ttf)

target_sources(SimpaticoLirio PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp
    Source/ChordEngine.cpp
    Source/Performer.cpp
    Source/Synth.cpp
    Source/Theory.cpp)

target_compile_definitions(SimpaticoLirio PUBLIC
    JUCE_WEB_BROWSER=1
    JUCE_USE_WIN_WEBVIEW2_WITH_STATIC_LINKING=1
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0)

target_link_libraries(SimpaticoLirio
    PRIVATE
        LirioUI
        juce::juce_audio_utils
        juce::juce_dsp
        juce::juce_gui_extra
    PUBLIC
        juce::juce_recommended_config_flags
        juce::juce_recommended_lto_flags
        juce::juce_recommended_warning_flags)

# Plain C++ check of the chord logic against the Python prototype (no JUCE needed).
add_executable(LirioTheoryTest tests/TheoryTest.cpp Source/Theory.cpp)
