"""Entry point: python -m lirio_proto [--learn] [--list] [--no-gui] [--no-audio]"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import mido
import sounddevice as sd

from .config import load_config
from .engine import Engine

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "lirio_config.json"


def list_devices():
    print("MIDI inputs: ", mido.get_input_names())
    print("MIDI outputs:", mido.get_output_names())
    print("\nAudio outputs:")
    hostapis = sd.query_hostapis()
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0:
            print(f"  [{i}] {dev['name']}  ({hostapis[dev['hostapi']]['name']}, "
                  f"{dev['default_samplerate']:.0f} Hz)")


def pick_audio_device(audio_cfg: dict) -> tuple[int | None, int]:
    """Return (device index, sample rate) honouring hostapi/device substrings."""
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    host_name = (audio_cfg.get("hostapi") or "").lower()
    dev_name = (audio_cfg.get("device") or "").lower()

    host_index = None
    for i, h in enumerate(hostapis):
        if host_name and host_name in h["name"].lower():
            host_index = i
    candidates = []
    for i, dev in enumerate(devices):
        if dev["max_output_channels"] < 2:
            continue
        if host_index is not None and dev["hostapi"] != host_index:
            continue
        if dev_name and dev_name not in dev["name"].lower():
            continue
        candidates.append(i)

    index = None
    if candidates:
        index = candidates[0]
        if not dev_name and host_index is not None:
            default = hostapis[host_index]["default_output_device"]
            if default in candidates:
                index = default
    if index is None:
        default_out = sd.default.device[1]
        index = default_out if default_out is not None and default_out >= 0 else None
    sr = int(sd.query_devices(index if index is not None else None, "output")["default_samplerate"])
    return index, sr


def warm_up(sr: int, config: dict):
    """Compile the numba kernels before the audio stream starts."""
    warm = Engine(sr, config)
    warm.fx.delay_mix = 0.2
    warm.fx.reverb_mix = 0.2
    warm.synth.note_on(60, 1.0)
    warm.bass_synth.note_on(36, 1.0)
    for _ in range(3):
        warm.process(256)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lirio_proto", description="Chord synth driven by MIDI (Simpático Lírio prototype)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--learn", action="store_true", help="map your MIDI controller interactively")
    parser.add_argument("--list", action="store_true", help="list MIDI and audio devices")
    parser.add_argument("--no-gui", action="store_true", help="run headless (MIDI control only)")
    parser.add_argument("--no-audio", action="store_true",
                        help="do not open an audio device (MIDI out only, e.g. to a DAW)")
    parser.add_argument("--midi-out", help="MIDI output port substring (overrides config)")
    args = parser.parse_args(argv)

    if args.list:
        list_devices()
        return
    if args.learn:
        from .learn import run_learn
        run_learn(args.config)
        return

    config = load_config(args.config)
    if args.midi_out:
        config["midi_output"] = args.midi_out
    audio_cfg = config["audio"]
    blocksize = int(audio_cfg.get("blocksize", 256))

    device, sr = (None, 48000) if args.no_audio else pick_audio_device(audio_cfg)
    print(f"Compiling DSP (first run takes a little longer) at {sr} Hz ...")
    warm_up(sr, config)
    engine = Engine(sr, config)

    from .midi_io import MidiController, MidiOutput
    midi_out = None
    if config.get("midi_output"):
        try:
            midi_out = MidiOutput(config["midi_output"])
            engine.midi_out_queue = midi_out.queue
            print(f"MIDI out: {midi_out.name}")
        except OSError as exc:
            print(exc)
    controller = MidiController(engine, config)
    opened = controller.open()
    status = "MIDI in: " + (", ".join(opened) if opened else "none")
    if midi_out:
        status += f"   |   MIDI out: {midi_out.name}"
    print(status)

    stream = None
    stop = threading.Event()
    if args.no_audio:
        def tick():
            period = blocksize / sr
            next_t = time.perf_counter()
            while not stop.is_set():
                engine.process(blocksize, render=False)
                next_t += period
                delay = next_t - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
        threading.Thread(target=tick, daemon=True).start()
    else:
        def callback(outdata, frames, time_info, status_flags):
            try:
                outdata[:] = engine.process(frames)
            except Exception as exc:  # never let the audio thread die silently
                outdata.fill(0)
                print(f"audio error: {exc!r}", file=sys.stderr)

        try:
            stream = sd.OutputStream(samplerate=sr, channels=2, dtype="float32", device=device,
                                     blocksize=blocksize, latency=audio_cfg.get("latency", "low"),
                                     callback=callback)
            stream.start()
        except sd.PortAudioError as exc:
            print(f"Could not open {device}: {exc}. Falling back to the default device.")
            sr_default = int(sd.query_devices(None, "output")["default_samplerate"])
            if sr_default != sr:
                sr = sr_default
                engine = Engine(sr, config)
                controller.engine = engine
                if midi_out:
                    engine.midi_out_queue = midi_out.queue
            stream = sd.OutputStream(samplerate=sr, channels=2, dtype="float32",
                                     blocksize=blocksize, callback=callback)
            stream.start()
        dev_name = sd.query_devices(stream.device)["name"]
        print(f"Audio: {dev_name} @ {sr} Hz, block {blocksize}, latency {stream.latency * 1000:.0f} ms")

    try:
        if args.no_gui:
            print("Running headless. Ctrl+C to quit.")
            while True:
                time.sleep(0.5)
        else:
            from .gui import FrontPanel
            FrontPanel(engine, status).run()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        controller.close()
        if stream is not None:
            stream.stop()
            stream.close()
        if midi_out:
            midi_out.close()


if __name__ == "__main__":
    main()
