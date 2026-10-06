"""Interactive MIDI learn: press/turn your controls and the mapping is written to the config."""

from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path

import mido

from .config import load_config, save_config
from .theory import ALL_BUTTONS, BUTTON_LABELS

OPTIONAL_ACTIONS = ["loop", "loop_undo", "beat", "key_mode", "bass", "latch",
                    "voicing_mode", "next_sound", "next_perform", "panic"]
OPTIONAL_PARAMS = ["cutoff", "resonance", "reverb", "delay", "chorus", "drive",
                   "sound", "perform", "bpm", "bass vol", "master"]


def _stdin_reader(lines: queue.SimpleQueue):
    for line in sys.stdin:
        lines.put(line.strip())


def _drain(q: queue.SimpleQueue):
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def _wait(msgs, lines, accept) -> mido.Message | None | str:
    """Wait for a MIDI message accepted by `accept`, or Enter (skip) / 'q' (finish)."""
    _drain(msgs)
    while True:
        try:
            line = lines.get_nowait()
            return "quit" if line.lower() == "q" else None
        except queue.Empty:
            pass
        try:
            msg = msgs.get(timeout=0.05)
        except queue.Empty:
            continue
        if accept(msg):
            return msg


def _is_press(msg) -> bool:
    return (msg.type == "note_on" and msg.velocity > 0) or \
        (msg.type == "control_change" and msg.value > 0 and msg.control != 64)


def _detect_dial_mode(msgs, first: mido.Message) -> str:
    values = [first.value]
    deadline = time.time() + 1.0
    while time.time() < deadline:
        try:
            msg = msgs.get(timeout=0.05)
        except queue.Empty:
            continue
        if msg.type == "control_change" and msg.control == first.control:
            values.append(msg.value)
    if all(v in (1, 2, 3, 4, 125, 126, 127, 124) for v in values) and len(set(values)) <= 4:
        return "relative_twos"
    if all(57 <= v <= 71 for v in values) and len(values) > 3:
        return "relative_offset"
    if all(v in (1, 2, 3, 65, 66, 67) for v in values) and len(values) > 3:
        return "relative_signed"
    return "absolute"


def _spec(msg) -> dict:
    if msg.type == "note_on":
        return {"note": msg.note, "channel": msg.channel + 1}
    return {"cc": msg.control, "channel": msg.channel + 1}


def run_learn(config_path: Path):
    config = load_config(config_path)
    msgs: queue.SimpleQueue = queue.SimpleQueue()
    names = mido.get_input_names()
    wanted = config.get("midi_inputs") or []
    ports = []
    for name in names:
        if wanted and not any(w.lower() in name.lower() for w in wanted):
            continue
        try:
            ports.append(mido.open_input(name, callback=msgs.put))
            print(f"listening: {name}")
        except (OSError, IOError) as exc:
            print(f"could not open {name}: {exc}")
    if not ports:
        print("No MIDI inputs available.")
        return

    lines: queue.SimpleQueue = queue.SimpleQueue()
    threading.Thread(target=_stdin_reader, args=(lines,), daemon=True).start()
    print("\nPress Enter to skip an item, type q + Enter to finish and save.\n")

    try:
        print("== Chord buttons (top row DIM MIN MAJ SUS, bottom row 6 m7 M7 9) ==")
        buttons = dict(config.get("buttons", {}))
        for name in ALL_BUTTONS:
            print(f"  press the control for [{BUTTON_LABELS[name]}] ... ", end="", flush=True)
            got = _wait(msgs, lines, _is_press)
            if got == "quit":
                raise KeyboardInterrupt
            if got is None:
                print("skipped")
                continue
            buttons[name] = _spec(got)
            print(buttons[name])
        config["buttons"] = buttons

        print("\n== Dials (turn the knob a few clicks) ==")
        for name in ("voicing", "bass_voicing"):
            print(f"  turn the knob for [{name}] ... ", end="", flush=True)
            got = _wait(msgs, lines, lambda m: m.type == "control_change" and m.control != 64)
            if got == "quit":
                raise KeyboardInterrupt
            if got is None:
                print("skipped")
                continue
            mode = _detect_dial_mode(msgs, got)
            dial = dict(config["dials"].get(name, {}))
            dial.update({"cc": got.control, "channel": got.channel + 1, "mode": mode})
            config["dials"][name] = dial
            print(f"CC {got.control} ({mode})")

        print("\n== Optional buttons ==")
        actions = dict(config.get("actions", {}))
        for name in OPTIONAL_ACTIONS:
            print(f"  press the control for [{name}] (Enter = skip) ... ", end="", flush=True)
            got = _wait(msgs, lines, _is_press)
            if got == "quit":
                raise KeyboardInterrupt
            if got is None:
                print("skipped")
                continue
            actions[name] = _spec(got)
            print(actions[name])
        config["actions"] = actions

        print("\n== Optional knobs (absolute CC) ==")
        ccs = dict(config.get("cc", {}))
        for name in OPTIONAL_PARAMS:
            print(f"  turn the knob for [{name}] (Enter = skip) ... ", end="", flush=True)
            got = _wait(msgs, lines, lambda m: m.type == "control_change" and m.control != 64)
            if got == "quit":
                raise KeyboardInterrupt
            if got is None:
                print("skipped")
                continue
            for other, cc in list(ccs.items()):
                if cc == got.control and other != name:
                    del ccs[other]
            ccs[name] = got.control
            print(f"CC {got.control}")
            time.sleep(0.6)
        config["cc"] = ccs
    except KeyboardInterrupt:
        print("\nfinishing.")
    finally:
        for port in ports:
            port.close()

    save_config(config_path, config)
    print(f"\nSaved {config_path}")
