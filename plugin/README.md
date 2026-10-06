# Simpático Lírio (VST3 / Standalone)

The plugin build of the chord synth. It is a C++ port of the Python prototype
in `../lirio_proto`, with a front panel written as a web page (`ui/index.html`) and shown in a
WebView2 browser inside the plugin window.

## Build (Windows)

Requirements: Visual Studio 2022 Build Tools (C++ workload) and CMake 3.22+.
JUCE 9.0.3 is a git submodule in `external/JUCE` (clone with `--recursive`). The WebView2
SDK is downloaded from nuget.org into `external/nuget` the first time you configure.

```
cmake -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
```

Output:

- `build/SimpaticoLirio_artefacts/Release/VST3/Simpatico Lirio.vst3`
- `build/SimpaticoLirio_artefacts/Release/Standalone/Simpatico Lirio.exe`

To use the VST3 in a DAW, copy the `.vst3` folder to `C:\Program Files\Common Files\VST3`
(or any folder your DAW scans) and rescan.

## Playing it

- **Keys**: MIDI notes play the root note. In the panel, click or hold the keys, or use `Z S X D C V G B H N J M ,`.
- **Chord buttons**: drum pads on channel 10, notes 36-43 (top row 40-43 = DIM MIN MAJ SUS, bottom row 36-39 = 6 m7 M7 9). The "Chord Buttons Input" parameter can switch them to the lowest keys, notes 24-31. In the panel, a click latches a button. Keys `1 2 3 4` / `Q W E R` work while held.
- **Sustain pedal**: holds the chord.
- **Hardware knobs** (Akai MPK layout, CC 70-77, "Hardware Knobs" parameter): bank A = Voicing, Bass Voicing, Sound, Perform; bank B = Tone, Rate (Pattern while in Pattern mode), Delay, Space. Measured on an MPK mini Play mk3.
- **Joystick / wheels**: pitch bend sweeps the voicing up to ±4 steps and springs back; CC 1 (mod wheel, joystick up) opens the filter.
- **Tempo**: arps and patterns follow the host tempo and position.
- **MIDI out**: ch 1 = perform-mode notes, ch 2 = bass, ch 3 = block chords. Route it to other instruments with "MIDI Out" on.

Every control on the panel is a host parameter, so it can be automated and MIDI-learned in the DAW.

## Layout

```
Source/
  Theory.*          chord buttons, playstyles, key mode, voicing, bass (matches lirio_proto/theory.py)
  Performer.*       perform modes on the sample clock
  Synth.*           voice engines (analog / FM / EP), presets, chorus, ping-pong delay
  ChordEngine.*     chord state, MIDI in/out, mixing, UI event queue and snapshot
  PluginProcessor.* parameters, host transport, state
  PluginEditor.*    WebView2 front panel and the JS <-> C++ bridge
ui/
  index.html        front panel (talks to C++ through window.__JUCE__.backend)
  mockup.html       the approved browser mockup (plays its own WebAudio sound)
  fonts/            DotGothic16 and Barlow Semi Condensed (SIL Open Font License)
tests/
  TheoryTest.cpp    dumps every button combination to diff against the Python prototype
```

## Bridge protocol

UI to C++ (`emitEvent("ui", ...)`):
`{type:"ready"}`, `{type:"key", note, down, velocity}`, `{type:"button", index, on}`,
`{type:"param", id, value}`, `{type:"gesture", id, begin}`, `{type:"panic"}`.

C++ to UI: `meta` (choice lists, once after `ready`) and `state` at 30 Hz
(chord label, notes, root, bass, held buttons, bpm, playing, peak, all parameter values).
