"""MIDI input mapping (controller -> Handful controls) and the MIDI output thread."""

from __future__ import annotations

import queue
import threading

import mido

from .engine import Engine


def _matches(spec: dict, msg: mido.Message) -> bool:
    channel = spec.get("channel")
    return channel is None or msg.channel == int(channel) - 1


def relative_delta(value: int, mode: str) -> int:
    if mode == "relative_offset":
        return value - 64
    if mode == "relative_twos":
        return value if value < 64 else value - 128
    if mode == "relative_signed":
        return value if value < 64 else -(value - 64)
    return 0


class MidiController:
    """Translates incoming messages into engine calls according to the config."""

    def __init__(self, engine: Engine, config: dict):
        self.engine = engine
        self.config = config
        self.ports: list = []
        self.last_message = ""
        kb = config.get("keyboard", {})
        self.kb_channel = kb.get("channel")
        self.transpose = int(kb.get("transpose", 0))

        self.note_buttons: dict[tuple[int, int | None], str] = {}
        self.cc_buttons: dict[tuple[int, int | None], str] = {}
        for name, spec in config.get("buttons", {}).items():
            if "note" in spec:
                self.note_buttons[(int(spec["note"]), spec.get("channel"))] = name
            elif "cc" in spec:
                self.cc_buttons[(int(spec["cc"]), spec.get("channel"))] = name
        self.actions = config.get("actions", {})
        self.dials = config.get("dials", {})
        self.cc_params = {int(cc): name for name, cc in config.get("cc", {}).items()}

    # --- ports ---------------------------------------------------------------------------
    def open(self) -> list[str]:
        wanted = self.config.get("midi_inputs") or []
        out_name = self.config.get("midi_output")
        opened = []
        for name in mido.get_input_names():
            if wanted and not any(w.lower() in name.lower() for w in wanted):
                continue
            if out_name and out_name.lower() in name.lower():
                continue  # never listen to our own output loop
            try:
                self.ports.append(mido.open_input(name, callback=self.handle))
                opened.append(name)
            except (OSError, IOError) as exc:
                print(f"Could not open MIDI input {name!r}: {exc}")
        return opened

    def close(self):
        for port in self.ports:
            port.close()
        self.ports.clear()

    # --- mapping -------------------------------------------------------------------------
    def _button_for(self, msg) -> str | None:
        for (note, channel), name in self.note_buttons.items():
            if note == msg.note and (channel is None or msg.channel == int(channel) - 1):
                return name
        return None

    def _action_for(self, msg) -> str | None:
        for name, spec in self.actions.items():
            if not _matches(spec, msg):
                continue
            if msg.type in ("note_on", "note_off") and spec.get("note") == msg.note:
                return name
            if msg.type == "control_change" and spec.get("cc") == msg.control:
                return name
        return None

    def handle(self, msg: mido.Message):
        if msg.type in ("clock", "active_sensing"):
            return
        self.last_message = str(msg)
        e = self.engine
        if msg.type in ("note_on", "note_off"):
            down = msg.type == "note_on" and msg.velocity > 0
            button = self._button_for(msg)
            if button:
                e.post(e.button_down if down else e.button_up, button)
                return
            action = self._action_for(msg)
            if action:
                if down:
                    self.run_action(action)
                return
            if self.kb_channel is not None and msg.channel != int(self.kb_channel) - 1:
                return
            note = msg.note + self.transpose
            if down:
                e.post(e.key_down, note, msg.velocity)
            else:
                e.post(e.key_up, note)
            return

        if msg.type == "control_change":
            if msg.control == 64:
                e.post(e.set_sustain, msg.value >= 64)
                return
            for (cc, channel), button in self.cc_buttons.items():
                if cc == msg.control and (channel is None or msg.channel == int(channel) - 1):
                    e.post(e.button_down if msg.value >= 64 else e.button_up, button)
                    return
            for dial_name, spec in self.dials.items():
                if spec.get("cc") == msg.control and _matches(spec, msg):
                    self._dial(dial_name, spec, msg.value)
                    return
            action = self._action_for(msg)
            if action:
                if msg.value >= 64:
                    self.run_action(action)
                return
            name = self.cc_params.get(msg.control)
            if name:
                param = e.param(name)
                if param:
                    param.set_normalized(msg.value / 127.0)

    def _dial(self, name: str, spec: dict, value: int):
        e = self.engine
        mode = spec.get("mode", "absolute")
        current = e.voicing if name == "voicing" else e.bass_voicing
        if mode == "absolute":
            rng = int(spec.get("range", 12))
            target = round((value - 64) / 64.0 * rng)
        else:
            target = current + relative_delta(value, mode)
        setter = e.set_voicing if name == "voicing" else e.set_bass_voicing
        e.post(setter, target)

    def run_action(self, name: str):
        e = self.engine
        perform = e.param("perform")
        sound = e.param("sound")
        table = {
            "loop": lambda: e.post(e.loop_press),
            "loop_stop": lambda: e.post(e.looper.stop),
            "loop_undo": lambda: e.post(e.looper.undo),
            "loop_clear": lambda: e.post(e.looper.clear),
            "beat": lambda: e.post(e.toggle_beat),
            "key_mode": lambda: e.post(e.toggle_key_mode),
            "bass": lambda: e.post(e.toggle_bass),
            "latch": lambda: e.post(e.toggle_latch),
            "voicing_mode": lambda: e.post(e.toggle_voicing_mode),
            "next_sound": lambda: sound.nudge(1),
            "prev_sound": lambda: sound.nudge(-1),
            "next_perform": lambda: perform.nudge(1),
            "prev_perform": lambda: perform.nudge(-1),
            "panic": lambda: e.post(e.panic),
        }
        fn = table.get(name)
        if fn:
            fn()


class MidiOutput:
    """Sends the engine's outgoing messages from a dedicated thread."""

    def __init__(self, port_substring: str):
        names = [n for n in mido.get_output_names() if port_substring.lower() in n.lower()]
        if not names:
            raise OSError(f"No MIDI output matching {port_substring!r}. "
                          f"Available: {mido.get_output_names()}")
        self.name = names[0]
        self.port = mido.open_output(self.name)
        self.queue: queue.SimpleQueue = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            msg = self.queue.get()
            if msg is None:
                return
            self.port.send(msg)

    def close(self):
        self.queue.put(None)
        self._thread.join(timeout=1.0)
        for channel in range(16):
            self.port.send(mido.Message("control_change", control=123, value=0, channel=channel))
        self.port.close()

