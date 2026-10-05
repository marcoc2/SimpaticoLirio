"""Pygame front panel. Everything is playable from the computer keyboard and mouse too."""

from __future__ import annotations

import math

import pygame

from . import theory
from .drums import Looper
from .engine import Engine

W, H = 1100, 640

BG = (28, 26, 25)
PANEL = (44, 41, 38)
SCREEN = (14, 22, 19)
LCD = (120, 230, 190)
LCD_DIM = (55, 110, 92)
CREAM = (232, 222, 204)
CREAM_DARK = (180, 170, 152)
ACCENT = (255, 122, 61)
ACCENT_SOFT = (255, 170, 120)
BASS_COLOR = (110, 170, 255)
TEXT = (230, 225, 215)
TEXT_DIM = (140, 134, 125)
RED = (235, 70, 70)

PIANO_KEYS = [pygame.K_z, pygame.K_s, pygame.K_x, pygame.K_d, pygame.K_c, pygame.K_v,
              pygame.K_g, pygame.K_b, pygame.K_h, pygame.K_n, pygame.K_j, pygame.K_m,
              pygame.K_COMMA]
PIANO_LABELS = ["Z", "S", "X", "D", "C", "V", "G", "B", "H", "N", "J", "M", ","]
BUTTON_KEYS = {pygame.K_1: "dim", pygame.K_2: "min", pygame.K_3: "maj", pygame.K_4: "sus",
               pygame.K_q: "6", pygame.K_w: "m7", pygame.K_e: "M7", pygame.K_r: "9"}
BUTTON_HINTS = {"dim": "1", "min": "2", "maj": "3", "sus": "4",
                "6": "Q", "m7": "W", "M7": "E", "9": "R"}
BLACK_PCS = {1, 3, 6, 8, 10}

HELP = [
    "Z S X D C V G B H N J M ,   play the 12 keys (root note)",
    "1 2 3 4  DIM MIN MAJ SUS      Q W E R  6 m7 M7 9   (hold)",
    "Left/Right  voicing dial      Up/Down  bass voicing dial     PgUp/PgDn  octave",
    "T perform mode (Shift = back)   Y sound   U key mode   I key root   O major/minor",
    "P playstyle   5 bass on/off   6 voicing OCTAVE/SPLIT   7 latch   8 beat on/off",
    "9 / 0 beat pattern   - / = BPM   Space loop rec/play/dub   L loop stop",
    "Backspace loop undo   Delete loop clear   Esc panic (all notes off)",
    "[ / ] select knob   ; / ' turn knob   mouse wheel over any knob or dial",
    "F1 toggle this help",
]


class FrontPanel:
    def __init__(self, engine: Engine, midi_status: str):
        pygame.init()
        pygame.display.set_caption("Handful prototype")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.font_big = self._font(64, bold=True)
        self.font_mid = self._font(24, bold=True)
        self.font = self._font(17)
        self.font_small = self._font(14)
        self.engine = engine
        self.midi_status = midi_status
        self.octave = 4
        self.selected = 0
        self.show_help = False
        self.held_piano: dict[int, int] = {}  # pygame key -> note
        self.mouse_note: int | None = None
        self.mouse_button: str | None = None
        self.button_rects: dict[str, pygame.Rect] = {}
        self.key_rects: list[tuple[pygame.Rect, int]] = []
        self.param_rects: list[tuple[pygame.Rect, int]] = []
        self.dial_rects: dict[str, pygame.Rect] = {}

    @staticmethod
    def _font(size, bold=False):
        for name in ("segoeui", "helveticaneue", "arial"):
            if pygame.font.match_font(name):
                return pygame.font.SysFont(name, size, bold=bold)
        return pygame.font.Font(None, size + 6)

    # --- input ---------------------------------------------------------------------------
    def _base_note(self) -> int:
        return 12 * (self.octave + 1)

    def _key_event(self, event):
        e = self.engine
        down = event.type == pygame.KEYDOWN
        shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        key = event.key

        if key in PIANO_KEYS:
            if down:
                note = self._base_note() + PIANO_KEYS.index(key)
                self.held_piano[key] = note
                e.post(e.key_down, note, 100)
            elif key in self.held_piano:
                e.post(e.key_up, self.held_piano.pop(key))
            return
        if key in BUTTON_KEYS:
            e.post(e.button_down if down else e.button_up, BUTTON_KEYS[key])
            return
        if not down:
            return

        step = -1 if shift else 1
        actions = {
            pygame.K_LEFT: lambda: e.post(e.set_voicing, e.voicing - 1),
            pygame.K_RIGHT: lambda: e.post(e.set_voicing, e.voicing + 1),
            pygame.K_UP: lambda: e.post(e.set_bass_voicing, e.bass_voicing + 1),
            pygame.K_DOWN: lambda: e.post(e.set_bass_voicing, e.bass_voicing - 1),
            pygame.K_PAGEUP: lambda: setattr(self, "octave", min(7, self.octave + 1)),
            pygame.K_PAGEDOWN: lambda: setattr(self, "octave", max(1, self.octave - 1)),
            pygame.K_t: lambda: e.param("perform").nudge(step),
            pygame.K_y: lambda: e.param("sound").nudge(step),
            pygame.K_u: lambda: e.post(e.toggle_key_mode),
            pygame.K_i: lambda: e.param("key").nudge(step),
            pygame.K_o: lambda: e.param("scale").nudge(1),
            pygame.K_p: lambda: e.param("playstyle").nudge(step),
            pygame.K_5: lambda: e.post(e.toggle_bass),
            pygame.K_6: lambda: e.post(e.toggle_voicing_mode),
            pygame.K_7: lambda: e.post(e.toggle_latch),
            pygame.K_8: lambda: e.post(e.toggle_beat),
            pygame.K_9: lambda: e.param("beat").nudge(-1),
            pygame.K_0: lambda: e.param("beat").nudge(1),
            pygame.K_MINUS: lambda: e.param("bpm").set(e.bpm - (10 if shift else 1)),
            pygame.K_EQUALS: lambda: e.param("bpm").set(e.bpm + (10 if shift else 1)),
            pygame.K_SPACE: lambda: e.post(e.loop_press),
            pygame.K_l: lambda: e.post(e.looper.stop),
            pygame.K_BACKSPACE: lambda: e.post(e.looper.undo),
            pygame.K_DELETE: lambda: e.post(e.looper.clear),
            pygame.K_ESCAPE: lambda: e.post(e.panic),
            pygame.K_LEFTBRACKET: lambda: setattr(self, "selected", (self.selected - 1) % len(e.params)),
            pygame.K_RIGHTBRACKET: lambda: setattr(self, "selected", (self.selected + 1) % len(e.params)),
            pygame.K_SEMICOLON: lambda: e.params[self.selected].nudge(-1),
            pygame.K_QUOTE: lambda: e.params[self.selected].nudge(1),
            pygame.K_F1: lambda: setattr(self, "show_help", not self.show_help),
        }
        fn = actions.get(key)
        if fn:
            fn()

    def _mouse_event(self, event):
        e = self.engine
        pos = getattr(event, "pos", pygame.mouse.get_pos())
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for name, rect in self.button_rects.items():
                if rect.collidepoint(pos):
                    self.mouse_button = name
                    e.post(e.button_down, name)
                    return
            for rect, note in self.key_rects:
                if rect.collidepoint(pos):
                    self.mouse_note = note
                    e.post(e.key_down, note, 100)
                    return
            for rect, index in self.param_rects:
                if rect.collidepoint(pos):
                    self.selected = index
                    return
            if self.dial_rects.get("voicing", pygame.Rect(0, 0, 0, 0)).collidepoint(pos):
                e.post(e.toggle_voicing_mode)
            elif self.dial_rects.get("bass", pygame.Rect(0, 0, 0, 0)).collidepoint(pos):
                e.post(e.toggle_bass)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.mouse_button:
                e.post(e.button_up, self.mouse_button)
                self.mouse_button = None
            if self.mouse_note is not None:
                e.post(e.key_up, self.mouse_note)
                self.mouse_note = None
        elif event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if self.dial_rects.get("voicing", pygame.Rect(0, 0, 0, 0)).collidepoint(pos):
                e.post(e.set_voicing, e.voicing + event.y)
                return
            if self.dial_rects.get("bass", pygame.Rect(0, 0, 0, 0)).collidepoint(pos):
                e.post(e.set_bass_voicing, e.bass_voicing + event.y)
                return
            for rect, index in self.param_rects:
                if rect.collidepoint(pos):
                    self.selected = index
                    e.params[index].nudge(event.y)
                    return

    # --- drawing -------------------------------------------------------------------------
    def _text(self, text, font, color, pos, anchor="topleft"):
        surf = font.render(text, True, color)
        rect = surf.get_rect(**{anchor: pos})
        self.screen.blit(surf, rect)
        return rect

    def _draw_display(self):
        e = self.engine
        rect = pygame.Rect(20, 20, 700, 230)
        pygame.draw.rect(self.screen, PANEL, rect.inflate(16, 16), border_radius=16)
        pygame.draw.rect(self.screen, SCREEN, rect, border_radius=10)

        label = e.chord_label or "—"
        color = RED if "WTF" in label else LCD
        self._text(label, self.font_big, color, (rect.x + 24, rect.y + 14))
        notes = " ".join(theory.note_name(n, True) for n in e.chord_notes)
        self._text(notes or "play a key", self.font, LCD_DIM, (rect.x + 26, rect.y + 96))

        info = [
            ("SOUND", e.param("sound").display()),
            ("PERFORM", e.performer.mode),
            ("KEY", f"{theory.NOTE_NAMES[e.key_root]} {e.scale}" + ("" if e.key_mode else " (off)")),
            ("STYLE", e.playstyle),
            ("VOICING", f"{e.voicing:+d} {e.voicing_mode}"),
            ("BASS", f"{e.bass_voicing:+d} " + (e.param("bass sound").display() if e.bass_on else "OFF")),
        ]
        x0, y0 = rect.x + 26, rect.y + 130
        for i, (k, v) in enumerate(info):
            x = x0 + (i % 3) * 225
            y = y0 + (i // 3) * 46
            self._text(k, self.font_small, LCD_DIM, (x, y))
            self._text(v, self.font, LCD, (x, y + 16))

        # Right column: transport
        x = rect.right - 150
        self._text(f"{e.bpm:.0f} BPM", self.font_mid, LCD, (x, rect.y + 16))
        beat = e.drums.pattern_name if e.drums.running else "beat off"
        self._text(beat, self.font, LCD if e.drums.running else LCD_DIM, (x, rect.y + 50))
        if e.drums.running:
            step = int((e.clock - e.transport_origin) / e.sixteenth) % 16
            for i in range(16):
                c = LCD if i == step else LCD_DIM
                pygame.draw.rect(self.screen, c, (x + i * 8, rect.y + 76, 6, 6))
        loop = e.looper
        loop_color = {Looper.RECORDING: RED, Looper.OVERDUB: ACCENT}.get(loop.state, LCD)
        self._text(f"LOOP {loop.state}", self.font, loop_color, (x, rect.y + 92))
        bar = pygame.Rect(x, rect.y + 116, 128, 6)
        pygame.draw.rect(self.screen, LCD_DIM, bar)
        if loop.length:
            pygame.draw.rect(self.screen, loop_color, (bar.x, bar.y, int(bar.w * loop.progress), bar.h))
        flags = []
        if e.latch:
            flags.append("LATCH")
        if e.sustain:
            flags.append("SUS")
        self._text(" ".join(flags), self.font, ACCENT, (x, rect.y + 130))
        meter = pygame.Rect(rect.right - 18, rect.y + 16, 6, rect.h - 32)
        pygame.draw.rect(self.screen, LCD_DIM, meter)
        level = min(1.0, e.peak)
        hh = int(meter.h * level)
        pygame.draw.rect(self.screen, RED if level > 0.97 else LCD,
                         (meter.x, meter.bottom - hh, meter.w, hh))

    def _draw_buttons(self):
        e = self.engine
        held = set(e.held_buttons)
        x0, y0 = 20, 280
        self._text("CHORD", self.font_small, TEXT_DIM, (x0, y0 - 20))
        self.button_rects.clear()
        for row, names in enumerate((theory.TYPE_BUTTONS, theory.EXT_BUTTONS)):
            for col, name in enumerate(names):
                r = pygame.Rect(x0 + col * 92, y0 + row * 86, 82, 74)
                self.button_rects[name] = r
                on = name in held
                pygame.draw.rect(self.screen, ACCENT if on else CREAM, r, border_radius=12)
                pygame.draw.rect(self.screen, CREAM_DARK, r, 2, border_radius=12)
                self._text(theory.BUTTON_LABELS[name], self.font_mid, BG, r.center, "center")
                self._text(BUTTON_HINTS[name], self.font_small, (90, 84, 76),
                           (r.right - 8, r.bottom - 4), "bottomright")

    def _draw_dial(self, center, radius, value, lo, hi, label, sub, key):
        rect = pygame.Rect(0, 0, radius * 2 + 20, radius * 2 + 50)
        rect.center = (center[0], center[1] + 12)
        self.dial_rects[key] = rect
        pygame.draw.circle(self.screen, PANEL, center, radius + 8)
        pygame.draw.circle(self.screen, CREAM, center, radius)
        frac = (value - lo) / (hi - lo)
        angle = math.radians(225 - 270 * frac)
        tip = (center[0] + math.cos(angle) * (radius - 10), center[1] - math.sin(angle) * (radius - 10))
        pygame.draw.line(self.screen, ACCENT, center, tip, 5)
        pygame.draw.circle(self.screen, BG, center, 6)
        self._text(label, self.font_small, TEXT_DIM, (center[0], center[1] - radius - 26), "midtop")
        self._text(f"{value:+d}  {sub}", self.font, TEXT, (center[0], center[1] + radius + 10), "midtop")

    def _draw_keyboard(self):
        e = self.engine
        x0, y0, kw, kh = 400, 470, 44, 140
        self.key_rects.clear()
        base = self._base_note()
        active_root = e.root % 12 if e.root is not None else None
        held_notes = {n for n in self.held_piano.values()}
        if self.mouse_note is not None:
            held_notes.add(self.mouse_note)
        held_notes |= {k[0] for k in e.held_keys}
        whites = [i for i in range(13) if i % 12 not in BLACK_PCS]
        blacks = [i for i in range(13) if i % 12 in BLACK_PCS]
        white_x = {}
        for idx, i in enumerate(whites):
            r = pygame.Rect(x0 + idx * kw, y0, kw - 4, kh)
            white_x[i] = r.x
            note = base + i
            on = note in held_notes
            color = ACCENT if on else (ACCENT_SOFT if active_root == note % 12 and e.chord_notes else CREAM)
            pygame.draw.rect(self.screen, color, r, border_radius=6)
            self._text(PIANO_LABELS[i], self.font_small, (90, 84, 76), (r.centerx, r.bottom - 6), "midbottom")
            self._text(theory.note_name(note), self.font_small, (120, 112, 100), (r.centerx, r.bottom - 24), "midbottom")
            self.key_rects.append((r, note))
        for i in blacks:
            r = pygame.Rect(white_x[i - 1] + kw - 17, y0, 28, int(kh * 0.6))
            note = base + i
            on = note in held_notes
            pygame.draw.rect(self.screen, ACCENT if on else (60, 56, 52), r, border_radius=5)
            self._text(PIANO_LABELS[i], self.font_small, TEXT_DIM, (r.centerx, r.bottom - 4), "midbottom")
            self.key_rects.insert(0, (r, note))  # black keys get hit-tested first
        self._text(f"OCTAVE {self.octave}  (PgUp/PgDn)", self.font_small, TEXT_DIM, (x0, y0 - 22))

    def _draw_roll(self):
        """Five-octave strip showing what is sounding."""
        e = self.engine
        x0, y0, w, h = 400, 270, 320, 160
        pygame.draw.rect(self.screen, PANEL, (x0 - 8, y0 - 8, w + 16, h + 16), border_radius=12)
        low, high = 24, 96
        kw = w / (high - low)
        chord = set(e.chord_notes)
        sounding = set(e.performer._sounding)
        for n in range(low, high):
            x = x0 + (n - low) * kw
            black = n % 12 in BLACK_PCS
            color = (70, 66, 60) if black else (95, 90, 82)
            if n in chord:
                color = ACCENT_SOFT
            if n in sounding:
                color = ACCENT
            if e.sounding_bass == n:
                color = BASS_COLOR
            hh = h * (0.6 if black else 1.0)
            pygame.draw.rect(self.screen, color, (x, y0 + h - hh, max(1, kw - 1), hh))
            if n % 12 == 0:
                self._text(f"C{n // 12 - 1}", self.font_small, TEXT_DIM, (x, y0 - 4), "bottomleft")

    def _draw_params(self):
        e = self.engine
        x0, y0 = 760, 20
        self._text("KNOBS  ([ ] select, ; ' turn, or mouse wheel)", self.font_small, TEXT_DIM, (x0, y0))
        self.param_rects.clear()
        row_h = 26
        for i, p in enumerate(e.params):
            r = pygame.Rect(x0, y0 + 22 + i * row_h, 320, row_h - 3)
            self.param_rects.append((r, i))
            sel = i == self.selected
            pygame.draw.rect(self.screen, (64, 58, 52) if sel else PANEL, r, border_radius=6)
            fill = pygame.Rect(r.x + 6, r.bottom - 3, int((r.w - 12) * min(1.0, max(0.0, p.normalized()))), 2)
            pygame.draw.rect(self.screen, ACCENT if sel else CREAM_DARK, fill)
            self._text(p.name.upper(), self.font_small, TEXT if sel else TEXT_DIM, (r.x + 8, r.centery - 1), "midleft")
            self._text(p.display(), self.font_small, TEXT, (r.right - 8, r.centery - 1), "midright")

    def _draw_footer(self):
        self._text(self.midi_status, self.font_small, TEXT_DIM, (20, H - 22))
        self._text("F1 help", self.font_small, TEXT_DIM, (W - 20, H - 22), "topright")

    def _draw_help(self):
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 215))
        self.screen.blit(overlay, (0, 0))
        for i, line in enumerate(HELP):
            self._text(line, self.font, TEXT, (60, 80 + i * 34))

    def draw(self):
        e = self.engine
        self.screen.fill(BG)
        self._draw_display()
        self._draw_buttons()
        self._draw_roll()
        self._draw_dial((110, 528), 46, e.voicing, -24, 24, "VOICING  (click: mode)", e.voicing_mode, "voicing")
        self._draw_dial((290, 528), 46, e.bass_voicing, -8, 8, "BASS  (click: on/off)",
                        "on" if e.bass_on else "off", "bass")
        self._draw_keyboard()
        self._draw_params()
        self._draw_footer()
        if self.show_help:
            self._draw_help()
        pygame.display.flip()

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type in (pygame.KEYDOWN, pygame.KEYUP):
                    self._key_event(event)
                elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL):
                    self._mouse_event(event)
            self.draw()
            self.clock.tick(30)
        pygame.quit()
