"""
main.py — Gamebook Studio.

Three views:
    * MainMenuView   — library browser, continue, settings
    * PlayerView     — full player with skill checks, item-use, save slots
    * StudioView     — node-graph editor with per-scene inspector and validator

Run:
    python3 main.py [--verbose] [--book NAME] [--no-textures]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import arcade
from arcade import XYWH
from arcade.camera import Camera2D

from data_model import (
    GameBook, Scene, Choice, Item, PlayerState,
    save_game, load_game, list_saves, delete_save, roll_check,
)
from ui_widgets import (
    Button, IconButton, ToggleButton, Slider, TextInput,
    TypewriterTextArea, StatBar, InventorySlot, MessageLog, NodeWidget,
    Tooltip, DiceRoller, Panel, TabBar,
)

# ─── verbose flag (parsed in main()) ────────────────────────────
VERBOSE = False
def vlog(*a, **kw):
    if VERBOSE:
        print(*a, **kw)

# ─── Config ─────────────────────────────────────────────────────
def load_config():
    for name in ("config.json", "config.sys"):
        if os.path.exists(name):
            try:
                with open(name, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}

CONFIG = load_config()

def cfg(section, key, default):
    return CONFIG.get(section, {}).get(key, default)

# Mutable runtime settings (persisted back to config.json by Settings panel)
SETTINGS = {
    "text_speed": cfg("display", "text_speed", 90),
    "font_size":  cfg("display", "font_size", 15),
    "master_volume": cfg("audio", "master_volume", 0.8),
    "sfx_volume":    cfg("audio", "sfx_volume", 0.7),
    "music_volume":  cfg("audio", "music_volume", 0.5),
    "show_dice":     True,
    "auto_save":     True,
}

def save_settings_to_disk():
    """Persist SETTINGS into config.json without clobbering other keys."""
    try:
        path = "config.json" if os.path.exists("config.json") else "config.sys"
        cfg_data = CONFIG
        cfg_data.setdefault("display", {})
        cfg_data["display"]["text_speed"] = int(SETTINGS["text_speed"])
        cfg_data["display"]["font_size"]  = int(SETTINGS["font_size"])
        cfg_data.setdefault("audio", {})
        cfg_data["audio"]["master_volume"] = float(SETTINGS["master_volume"])
        cfg_data["audio"]["sfx_volume"]    = float(SETTINGS["sfx_volume"])
        cfg_data["audio"]["music_volume"]  = float(SETTINGS["music_volume"])
        cfg_data.setdefault("gameplay", {})
        cfg_data["gameplay"]["show_dice"]  = bool(SETTINGS["show_dice"])
        cfg_data["gameplay"]["auto_save"]  = bool(SETTINGS["auto_save"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f, indent=2)
    except Exception as e:
        vlog(f"Could not save settings: {e}")

# ─── Key mapping ────────────────────────────────────────────────
KEY_MAP: dict[str, int] = {}
def _build_keys():
    tbl = {"f": arcade.key.F, "escape": arcade.key.ESCAPE, "h": arcade.key.H,
           "s": arcade.key.S, "l": arcade.key.L, "n": arcade.key.N,
           "e": arcade.key.E, "q": arcade.key.Q, "space": arcade.key.SPACE,
           "i": arcade.key.I, "c": arcade.key.C, "b": arcade.key.B,
           "tab": arcade.key.TAB, "r": arcade.key.R}
    for i in range(1, 10):
        tbl[str(i)] = arcade.key.KEY_1 + (i - 1)
    for action, kname in CONFIG.get("keys", {}).items():
        k = tbl.get(str(kname).lower())
        if k:
            KEY_MAP[action] = k
    defaults = {
        "fullscreen": arcade.key.F, "exit": arcade.key.ESCAPE,
        "help": arcade.key.H, "save": arcade.key.S, "load": arcade.key.L,
        "notebook": arcade.key.N, "editor_toggle": arcade.key.E,
        "inventory": arcade.key.I, "character": arcade.key.C,
        "back": arcade.key.B, "settings": arcade.key.TAB,
        "quicksave": arcade.key.R,
    }
    for i in range(1, 10):
        defaults[f"choice_{i}"] = arcade.key.KEY_1 + (i - 1)
    for a, k in defaults.items():
        KEY_MAP.setdefault(a, k)
_build_keys()

def km(key, action):
    return key == KEY_MAP.get(action)

# ─── Texture cache ──────────────────────────────────────────────
_TEXTURE_CACHE: dict[str, object | None] = {}
def load_tex(path):
    if path in _TEXTURE_CACHE:
        return _TEXTURE_CACHE[path]
    if os.path.exists(path):
        try:
            t = arcade.load_texture(path)
            _TEXTURE_CACHE[path] = t
            return t
        except Exception:
            pass
    _TEXTURE_CACHE[path] = None
    return None

# Layout constants
SIDEBAR_W = cfg("display", "sidebar_width", 220)


# ═══════════════════════════════════════════════════════════════
# MAIN MENU
# ═══════════════════════════════════════════════════════════════
class MainMenuView(arcade.View):
    """Library browser with cover panel, Continue, and book stats."""

    def __init__(self):
        super().__init__()
        self.background_color = (16, 16, 22)
        self.buttons: list[Button] = []
        self.gamebooks: list[GameBook] = []
        self.book_buttons: list[Button] = []
        self.selected_book = 0
        self.show_help = False
        self.show_settings = False
        self.show_achievements = False
        self.settings_widgets: list = []
        self._latest_save: dict | None = None      # (book_index, save_meta)
        self._scroll = 0       # offset into book list
        self._cover_tex = None
        self._title_pulse = 0.0

    # ── lifecycle ───────────────────────────────────────────────
    def on_show_view(self):
        self._load_library()
        self._find_latest_save()
        self._rebuild()
        if self.gamebooks:
            self._load_cover()

    def on_resize(self, w, h):
        self._rebuild()

    def on_update(self, dt):
        self._title_pulse = (self._title_pulse + dt) % 6.28

    # ── library / metadata ──────────────────────────────────────
    def _load_library(self):
        self.gamebooks = []
        lib = cfg("paths", "library", "./library")
        if not os.path.exists(lib):
            os.makedirs(lib, exist_ok=True)
        for entry in sorted(os.listdir(lib)):
            path = os.path.join(lib, entry)
            if (os.path.isdir(path)
                    and os.path.exists(os.path.join(path, "project.json"))):
                try:
                    self.gamebooks.append(GameBook.load(path))
                    vlog(f"  Loaded book: {entry}")
                except Exception as e:
                    vlog(f"  Skipped {entry}: {e}")

    def _find_latest_save(self):
        latest_t = 0.0
        self._latest_save = None
        for i, gb in enumerate(self.gamebooks):
            saves = list_saves(gb.folder_path)
            if saves and saves[0]["timestamp"] > latest_t:
                latest_t = saves[0]["timestamp"]
                self._latest_save = {"book_index": i, "save": saves[0]}

    def _load_cover(self):
        gb = self.gamebooks[self.selected_book]
        cover_path = os.path.join(gb.folder_path, "assets", "textures", "cover.png")
        # Fall back to start-scene illustration as cover.
        if not os.path.exists(cover_path):
            cover_path = os.path.join(gb.folder_path, "assets", "textures",
                                      f"{gb.start_scene}.png")
        self._cover_tex = load_tex(cover_path)

    # ── layout ──────────────────────────────────────────────────
    def _rebuild(self):
        w, h = self.window.width, self.window.height
        self.buttons = []
        self.book_buttons = []

        # LEFT panel: book list
        left_panel_w = max(280, int(w * 0.30))
        list_top = h - 130
        list_h = h - 240
        bw = left_panel_w - 40
        max_books = max(1, list_h // 56)
        start = max(0, min(self._scroll, max(0, len(self.gamebooks) - max_books)))
        self._scroll = start
        for vi, idx in enumerate(range(start, min(len(self.gamebooks), start + max_books))):
            gb = self.gamebooks[idx]
            sel = (idx == self.selected_book)
            btn = Button(20 + bw / 2, list_top - vi * 56,
                         bw, 48,
                         f"  {gb.title}",
                         color=(60, 80, 120) if sel else (38, 42, 56),
                         hover_color=(80, 105, 150),
                         text_color=(235, 230, 220),
                         font_size=13, align="left",
                         callback=lambda i=idx: self._select(i))
            btn.subtitle = f"  {len(gb.scenes)} scenes · by {gb.author[:20]}"
            self.book_buttons.append(btn)

        # Bottom action bar
        by = 60
        bw_btn = 140
        gap = 14
        actions: list[tuple[str, callable, tuple[int, int, int], bool]] = []
        if self._latest_save:
            actions.append(("CONTINUE", self._continue, (50, 130, 70), True))
        actions += [
            ("PLAY", self._play, (40, 100, 55), bool(self.gamebooks)),
            ("LOAD", self._load, (50, 80, 120), bool(self.gamebooks)),
            ("STUDIO", self._studio, (110, 75, 40), bool(self.gamebooks)),
            ("SETTINGS", self._open_settings, (70, 60, 90), True),
            ("QUIT", self._quit, (110, 45, 45), True),
        ]
        total_w = bw_btn * len(actions) + gap * (len(actions) - 1)
        x = (w - total_w) / 2 + bw_btn / 2
        for label, cb, col, en in actions:
            b = Button(x, by, bw_btn, 38, label, color=col,
                       hover_color=tuple(min(255, c + 30) for c in col),
                       font_size=13, callback=cb, enabled=en)
            self.buttons.append(b)
            x += bw_btn + gap

        # Right column tools
        self.buttons.append(Button(w - 110, h - 28, 90, 28, "Help",
                                   color=(50, 50, 65),
                                   hover_color=(70, 70, 90),
                                   font_size=10, callback=self._toggle_help))
        self.buttons.append(Button(w - 210, h - 28, 90, 28, "★ Awards",
                                   color=(80, 65, 35),
                                   hover_color=(110, 92, 50),
                                   font_size=10, callback=self._toggle_achievements))

        # Scroll arrows for book list
        if len(self.gamebooks) > max_books:
            self.buttons.append(IconButton(left_panel_w - 12, list_top + 32, 22,
                                           "▲", color=(50, 55, 70),
                                           hover_color=(70, 80, 105),
                                           callback=lambda: self._scroll_books(-1)))
            self.buttons.append(IconButton(left_panel_w - 12,
                                           list_top - max_books * 56 - 4, 22,
                                           "▼", color=(50, 55, 70),
                                           hover_color=(70, 80, 105),
                                           callback=lambda: self._scroll_books(1)))

    def _scroll_books(self, delta):
        self._scroll = max(0, self._scroll + delta)
        self._rebuild()

    def _select(self, i):
        self.selected_book = i
        self._load_cover()
        self._rebuild()

    # ── actions ─────────────────────────────────────────────────
    def _play(self):
        if self.gamebooks:
            self.window.show_view(PlayerView(self.gamebooks[self.selected_book]))

    def _continue(self):
        if not self._latest_save:
            return self._play()
        bi = self._latest_save["book_index"]
        slot = self._latest_save["save"]["slot"]
        gb = self.gamebooks[bi]
        ps = load_game(gb.folder_path, slot)
        if ps:
            pv = PlayerView(gb, start_scene=ps.current_scene)
            pv._loaded_state = ps
            self.window.show_view(pv)

    def _load(self):
        if not self.gamebooks:
            return
        gb = self.gamebooks[self.selected_book]
        saves = list_saves(gb.folder_path)
        if saves:
            ps = load_game(gb.folder_path, saves[0]["slot"])
            if ps:
                pv = PlayerView(gb, start_scene=ps.current_scene)
                pv._loaded_state = ps
                self.window.show_view(pv)
                return
        self._play()

    def _studio(self):
        if self.gamebooks:
            self.window.show_view(StudioView(self.gamebooks[self.selected_book]))

    def _quit(self):
        self.window.close()

    def _toggle_help(self):
        self.show_help = not self.show_help
        self.show_settings = False
        self.show_achievements = False

    def _toggle_achievements(self):
        self.show_achievements = not self.show_achievements
        self.show_help = False
        self.show_settings = False

    def _open_settings(self):
        self.show_settings = not self.show_settings
        self.show_help = False
        self.show_achievements = False
        if self.show_settings:
            self._build_settings()

    def _build_settings(self):
        w, h = self.window.width, self.window.height
        self.settings_widgets = []
        cx, cy = w // 2, h // 2
        x0 = cx - 180; y = cy + 80
        # text speed
        self.settings_widgets.append(Slider(
            x0, y, 360, 8, "Text speed (chars/sec)",
            SETTINGS["text_speed"], 10, 300, 5,
            on_change=lambda v: SETTINGS.__setitem__("text_speed", int(v))))
        y -= 36
        self.settings_widgets.append(Slider(
            x0, y, 360, 8, "Font size",
            SETTINGS["font_size"], 11, 22, 1,
            on_change=lambda v: SETTINGS.__setitem__("font_size", int(v))))
        y -= 36
        self.settings_widgets.append(Slider(
            x0, y, 360, 8, "Master volume",
            SETTINGS["master_volume"], 0.0, 1.0, 0.05,
            on_change=lambda v: SETTINGS.__setitem__("master_volume", float(v))))
        y -= 36
        # toggles
        tb1 = ToggleButton(cx - 110, y - 14, 200, 28,
                           "Animated dice rolls",
                           color=(40, 40, 55), hover_color=(55, 55, 75),
                           font_size=11, value=SETTINGS["show_dice"],
                           callback=lambda v: SETTINGS.__setitem__("show_dice", v))
        tb2 = ToggleButton(cx + 110, y - 14, 200, 28,
                           "Auto-save on scene",
                           color=(40, 40, 55), hover_color=(55, 55, 75),
                           font_size=11, value=SETTINGS["auto_save"],
                           callback=lambda v: SETTINGS.__setitem__("auto_save", v))
        self.settings_widgets += [tb1, tb2]
        # save / close
        self.settings_widgets.append(Button(
            cx - 90, cy - 100, 150, 32, "Save & Close",
            color=(50, 110, 60), hover_color=(70, 140, 80),
            font_size=12, callback=self._save_settings))
        self.settings_widgets.append(Button(
            cx + 90, cy - 100, 150, 32, "Cancel",
            color=(95, 50, 50), hover_color=(125, 70, 70),
            font_size=12, callback=lambda: setattr(self, "show_settings", False)))

    def _save_settings(self):
        save_settings_to_disk()
        self.show_settings = False

    # ── drawing ─────────────────────────────────────────────────
    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        left_panel_w = max(280, int(w * 0.30))

        # Subtle vignette / texture
        arcade.draw_rect_filled(XYWH(left_panel_w / 2, h / 2, left_panel_w, h),
                                color=(22, 22, 30))
        arcade.draw_line(left_panel_w, 0, left_panel_w, h, (60, 60, 75), 1)

        # Title
        import math
        glow = 200 + int(20 * math.sin(self._title_pulse))
        arcade.draw_text("GAMEBOOK STUDIO", w // 2, h - 50,
                         (glow, 188, 130), font_size=30,
                         anchor_x="center", anchor_y="center", bold=True)
        arcade.draw_text("Interactive Fiction Editor & Player",
                         w // 2, h - 80, (135, 135, 145),
                         font_size=11, anchor_x="center", anchor_y="center")

        # Library label
        arcade.draw_text(f"LIBRARY · {len(self.gamebooks)} BOOKS",
                         20, h - 110, (150, 150, 160), font_size=11,
                         anchor_x="left", anchor_y="center", bold=True)

        # Book list buttons
        for b in self.book_buttons:
            b.draw()

        # Right pane: cover + metadata
        if self.gamebooks:
            gb = self.gamebooks[self.selected_book]
            right_x = left_panel_w + 30
            right_w = w - left_panel_w - 60
            # Cover area
            cover_top = h - 130
            cover_h = min(int(right_w * 9 / 16), int((h - 280) * 0.55))
            cover_y = cover_top - cover_h / 2
            arcade.draw_rect_filled(XYWH(right_x + right_w / 2, cover_y,
                                         right_w, cover_h),
                                    color=(8, 8, 14))
            if self._cover_tex:
                arcade.draw_texture_rect(self._cover_tex,
                                         XYWH(right_x + right_w / 2, cover_y,
                                              right_w, cover_h))
            arcade.draw_rect_outline(XYWH(right_x + right_w / 2, cover_y,
                                          right_w, cover_h),
                                     color=(80, 70, 50), border_width=1)

            # Title + author
            ty = cover_y - cover_h / 2 - 20
            arcade.draw_text(gb.title, right_x, ty, (240, 220, 170),
                             font_size=22, anchor_x="left", anchor_y="center",
                             bold=True)
            ty -= 30
            arcade.draw_text(f"by {gb.author}  ·  v{gb.version}",
                             right_x, ty, (155, 150, 160), font_size=11,
                             anchor_x="left", anchor_y="center")
            ty -= 22
            # Stats line
            saves = list_saves(gb.folder_path)
            save_str = f"{len(saves)} saves" if saves else "no saves yet"
            stats_str = (f"{len(gb.scenes)} scenes · {len(gb.items)} items · "
                         f"{len(gb.stat_names)} stats · {save_str}")
            arcade.draw_text(stats_str, right_x, ty, (130, 150, 175),
                             font_size=10, anchor_x="left", anchor_y="center")
            ty -= 26
            # Description
            desc = gb.description
            arcade.draw_text(desc, right_x, ty, (180, 175, 180),
                             font_size=11, anchor_x="left", anchor_y="top",
                             width=right_w, multiline=True)

            # Continue card
            if self._latest_save and self._latest_save["book_index"] == self.selected_book:
                save = self._latest_save["save"]
                cw_box, ch_box = right_w, 44
                cy_box = 110
                arcade.draw_rect_filled(
                    XYWH(right_x + cw_box / 2, cy_box, cw_box, ch_box),
                    color=(34, 50, 38, 230))
                arcade.draw_rect_outline(
                    XYWH(right_x + cw_box / 2, cy_box, cw_box, ch_box),
                    color=(70, 130, 80), border_width=1)
                arcade.draw_text("▶ Continue", right_x + 12, cy_box + 8,
                                 (180, 230, 190), font_size=11,
                                 anchor_x="left", anchor_y="center", bold=True)
                meta = (f"{save.get('scene_title', save['scene'])} · "
                        f"{_fmt_time(save.get('play_seconds', 0))}")
                arcade.draw_text(meta, right_x + 12, cy_box - 8,
                                 (160, 170, 165), font_size=9,
                                 anchor_x="left", anchor_y="center")

        # Bottom action bar
        for b in self.buttons:
            b.draw()
        arcade.draw_text("F=fullscreen  H=help  ESC=quit  ↑/↓=select",
                         w // 2, 20, (90, 90, 100), font_size=9,
                         anchor_x="center", anchor_y="center")

        if self.show_help:
            self._draw_help(w, h)
        if self.show_settings:
            self._draw_settings(w, h)
        if self.show_achievements:
            self._draw_achievements(w, h)

    def _draw_help(self, w, h):
        Panel(w // 2, h // 2, 540, 410, "GAMEBOOK STUDIO — HELP").draw()
        lines = [
            ("Library", True),
            ("  ↑ / ↓        Select gamebook", False),
            ("  Enter        Play", False),
            ("  TAB          Settings", False),
            ("", False),
            ("Player", True),
            ("  1 – 9        Choose option", False),
            ("  Space/Click  Skip text reveal · roll dice · advance", False),
            ("  S / L        Save / Load   ·   R   Quicksave", False),
            ("  I            Inventory tab    ·   N   Notebook tab", False),
            ("  C            Character sheet ·   B   Back one scene", False),
            ("  E / ESC      Editor / Menu", False),
            ("", False),
            ("Studio", True),
            ("  Click / Drag  Select / move node  ·  Middle-drag  Pan", False),
            ("  Scroll        Zoom  ·  + / -   Add / delete scene", False),
            ("  V             Validate project   ·  Ctrl+S  Save", False),
        ]
        cx, cy = w // 2, h // 2 + 175
        for ln, hd in lines:
            color = (230, 200, 130) if hd else (200, 200, 210)
            size = 13 if hd else 11
            arcade.draw_text(ln, cx - 230, cy, color, font_size=size,
                             anchor_x="left", anchor_y="center", bold=hd)
            cy -= 19

    def _draw_settings(self, w, h):
        Panel(w // 2, h // 2, 460, 320, "SETTINGS").draw()
        for sw in self.settings_widgets:
            sw.draw()

    def _draw_achievements(self, w, h):
        Panel(w // 2, h // 2, 540, 380,
              "ACHIEVEMENTS").draw()
        # Aggregate achievements across all books' newest save
        cx = w // 2; cy = h // 2 + 130
        any_unlocked = False
        for gb in self.gamebooks:
            saves = list_saves(gb.folder_path)
            if not saves:
                continue
            ps = load_game(gb.folder_path, saves[0]["slot"])
            if not ps or not ps.achievements:
                continue
            any_unlocked = True
            arcade.draw_text(gb.title, cx - 240, cy, (220, 195, 130),
                             font_size=12, anchor_x="left", anchor_y="center",
                             bold=True)
            cy -= 18
            for ach in ps.achievements:
                meta = gb.achievements.get(ach, {}) if isinstance(gb.achievements, dict) else {}
                name = meta.get("name", ach) if isinstance(meta, dict) else ach
                arcade.draw_text(f"  ★ {name}", cx - 230, cy,
                                 (180, 220, 180), font_size=10,
                                 anchor_x="left", anchor_y="center")
                cy -= 16
            cy -= 6
        if not any_unlocked:
            arcade.draw_text("No achievements yet — start playing!",
                             cx, cy - 20, (150, 150, 160), font_size=12,
                             anchor_x="center", anchor_y="center")

    # ── input ───────────────────────────────────────────────────
    def on_key_press(self, key, mods):
        if self.show_help or self.show_settings or self.show_achievements:
            if km(key, "exit"):
                self.show_help = self.show_settings = self.show_achievements = False
            return
        if km(key, "fullscreen"):
            self.window.set_fullscreen(not self.window.fullscreen)
        elif km(key, "exit"):
            self.window.close()
        elif km(key, "help"):
            self._toggle_help()
        elif km(key, "settings"):
            self._open_settings()
        elif key == arcade.key.UP:
            self.selected_book = max(0, self.selected_book - 1)
            if self.selected_book < self._scroll:
                self._scroll = self.selected_book
            self._load_cover()
            self._rebuild()
        elif key == arcade.key.DOWN:
            self.selected_book = min(len(self.gamebooks) - 1, self.selected_book + 1)
            self._rebuild()
            self._load_cover()
        elif key == arcade.key.ENTER:
            self._play()

    def on_mouse_motion(self, x, y, dx, dy):
        for b in self.buttons:
            b.on_mouse_motion(x, y)
        for b in self.book_buttons:
            b.on_mouse_motion(x, y)
        if self.show_settings:
            for sw in self.settings_widgets:
                if hasattr(sw, "on_mouse_motion"):
                    sw.on_mouse_motion(x, y)

    def on_mouse_press(self, x, y, btn, mods):
        if self.show_settings:
            for sw in self.settings_widgets:
                if sw.on_mouse_press(x, y, btn):
                    return
            return
        if self.show_help or self.show_achievements:
            return
        for b in self.book_buttons:
            if b.on_mouse_press(x, y, btn):
                return
        for b in self.buttons:
            if b.on_mouse_press(x, y, btn):
                return

    def on_mouse_release(self, x, y, btn, mods):
        if self.show_settings:
            for sw in self.settings_widgets:
                if hasattr(sw, "on_mouse_release"):
                    sw.on_mouse_release(x, y, btn)

    def on_mouse_drag(self, x, y, dx, dy, buttons, mods):
        if self.show_settings:
            for sw in self.settings_widgets:
                if hasattr(sw, "on_mouse_drag"):
                    sw.on_mouse_drag(x, y, dx, dy, buttons, mods)

    def on_mouse_scroll(self, x, y, sx, sy):
        # scroll the book list
        if x < max(280, int(self.window.width * 0.30)):
            self._scroll_books(-int(sy))


def _fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m:02d}:{s:02d}"


# ═══════════════════════════════════════════════════════════════
# PLAYER VIEW
# ═══════════════════════════════════════════════════════════════
class PlayerView(arcade.View):
    """Player with sidebar tabs (stats / inventory / notebook), dice rolls,
    save slot previews, scene history, and ending screen."""

    SIDEBAR = 240            # right sidebar (tabs)
    TOOLBAR_H = 44

    def __init__(self, gamebook: GameBook, start_scene: str = ""):
        super().__init__()
        self.background_color = (16, 16, 22)
        self.gamebook = gamebook
        self.player = gamebook.create_player()
        self.current_scene: Scene | None = None
        self._pending_scene = start_scene or gamebook.start_scene
        self._loaded_state: PlayerState | None = None

        self.text_area = TypewriterTextArea(
            0, 0, 100, 100,
            font_size=SETTINGS["font_size"],
            chars_per_second=SETTINGS["text_speed"])
        self.choice_buttons: list[Button] = []
        self.hud_buttons: list[Button] = []
        self.stat_bars: list[StatBar] = []
        self.inventory_slots: list[InventorySlot] = []
        self.message_log = MessageLog()
        self.tooltip = Tooltip()
        self.dice = DiceRoller()
        self.tabbar: TabBar | None = None

        # UI state flags
        self.show_help = False
        self.show_save_menu = False
        self.show_load_menu = False
        self.show_character = False
        self.show_settings = False
        self.show_ending = False
        self.show_confirm_quit = False
        self.active_tab = 0   # 0=Stats, 1=Notebook, 2=History
        self.save_buttons: list[Button] = []
        self.ending_buttons: list[Button] = []
        self.confirm_buttons: list[Button] = []
        self.character_buttons: list[Button] = []
        self.settings_widgets: list = []

        self._scene_tex = None
        self._bg_tex = None
        self._icon_textures: dict[str, object] = {}
        self._illust_rect = (0, 0, 100, 100)
        self._fade_alpha = 0       # scene-transition fade
        self._fade_dir = 0         # +1 fade-out, -1 fade-in
        self._next_scene_id = ""
        self._pending_choice: tuple[Choice, int] | None = None
        self._scene_start_time = 0.0
        self._selected_inv = -1     # selected inventory slot index

    # ── lifecycle ───────────────────────────────────────────────
    def on_show_view(self):
        self._load_textures()
        if self._loaded_state:
            self.player = self._loaded_state
            self._loaded_state = None
        # rebuild UI before goto so layout exists
        self._goto_scene(self._pending_scene, fade=False)

    def on_resize(self, w, h):
        if self.current_scene:
            self._rebuild_ui()

    def on_update(self, dt):
        self.message_log.update(dt)
        self.text_area.update(dt)
        self.tooltip.update(dt)
        self.dice.update(dt)
        for sb in self.stat_bars:
            sb.update(dt)
        if not self.show_ending:
            self.player.play_seconds += dt
        # Handle dice resolution
        if self.dice.finished and self._pending_choice:
            # waiting for click/space
            pass
        # Fade animation
        if self._fade_dir > 0:
            self._fade_alpha = min(255, self._fade_alpha + int(dt * 800))
            if self._fade_alpha >= 230:
                self._fade_dir = -1
                self._do_goto(self._next_scene_id)
        elif self._fade_dir < 0:
            self._fade_alpha = max(0, self._fade_alpha - int(dt * 600))
            if self._fade_alpha == 0:
                self._fade_dir = 0

    # ── textures ────────────────────────────────────────────────
    def _load_textures(self):
        base = self.gamebook.folder_path
        td = os.path.join(base, "assets", "textures")
        self._bg_tex = load_tex(os.path.join(td, "background.png"))
        self._icon_textures = {}
        idir = os.path.join(td, "icons")
        for iid in self.gamebook.items:
            t = load_tex(os.path.join(idir, f"{iid}.png"))
            if t:
                self._icon_textures[iid] = t

    def _load_scene_tex(self, sid):
        td = os.path.join(self.gamebook.folder_path, "assets", "textures")
        self._scene_tex = load_tex(os.path.join(td, f"{sid}.png"))

    # ── navigation ──────────────────────────────────────────────
    def _goto_scene(self, sid: str, fade: bool = True) -> None:
        if fade and self.current_scene:
            self._next_scene_id = sid
            self._fade_dir = 1
            return
        self._do_goto(sid)

    def _do_goto(self, sid: str) -> None:
        scene = self.gamebook.get_scene(sid)
        if not scene:
            self.message_log.add(f"Scene not found: {sid}", color=(255, 80, 80))
            return
        # Push history (not on revisit)
        if self.current_scene and self.current_scene.id != sid:
            self.player.history.append(self.current_scene.id)
            self.player.history = self.player.history[-16:]
        self.current_scene = scene
        self.player.current_scene = sid
        is_new = sid not in self.player.visited_scenes
        if is_new:
            self.player.visited_scenes.append(sid)
        # On-enter effects (with messages)
        for action_dict in scene.on_enter:
            msgs = self.player.apply_effects(action_dict)
            for m in msgs:
                self.message_log.add(m, color=(180, 220, 255))
        self._load_scene_tex(sid)
        self.text_area.set_speed(SETTINGS["text_speed"])
        self.text_area.font_size = SETTINGS["font_size"]
        self.text_area.set_text(scene.body, animate=True)
        self._scene_start_time = time.time()
        self._rebuild_ui()
        # Auto-save
        if SETTINGS.get("auto_save") and is_new:
            try:
                save_game(self.player, self.gamebook.folder_path,
                          slot_name="autosave",
                          scene_title=scene.title)
            except Exception:
                pass
        # Ending check
        if scene.is_ending() and not scene.choices:
            # Award some auto-achievements
            self._award_endgame_achievements(scene)
            self.show_ending = True
            self._build_ending_buttons()

    def _award_endgame_achievements(self, scene: Scene) -> None:
        ach = self.player.achievements
        if scene.is_ending() and "first_ending" not in ach:
            ach.append("first_ending")
        if any(t in scene.tags for t in ("victory",)) and "victor" not in ach:
            ach.append("victor")
        if any(t in scene.tags for t in ("defeat", "death")) and "fallen" not in ach:
            ach.append("fallen")
        # Visited every scene
        if (len(self.player.visited_scenes) == len(self.gamebook.scenes)
                and "completionist" not in ach):
            ach.append("completionist")
        # Collected every item the book ever offers
        if (len(set(self.player.inventory)) >= len(self.gamebook.items)
                and "collector" not in ach
                and len(self.gamebook.items) >= 5):
            ach.append("collector")
        # No-failure run
        if (self.player.rolls_failed == 0 and self.player.rolls_succeeded > 0
                and "lucky" not in ach):
            ach.append("lucky")

    # ── choosing ────────────────────────────────────────────────
    def _choose(self, idx: int) -> None:
        if not self.current_scene or idx >= len(self.current_scene.choices):
            return
        if self.text_area.is_animating:
            self.text_area.skip_animation()
            return
        if self.dice.active:
            return  # ignore choices while rolling
        ch = self.current_scene.choices[idx]
        if isinstance(ch, dict):
            ch = Choice.from_dict(ch)
        if not self.player.check_condition(ch.conditions):
            self.message_log.add("Conditions not met!", color=(255, 80, 80))
            return

        # Skill-check?
        if ch.roll:
            result = roll_check(ch.roll, self.player)
            self._pending_choice = (ch, idx)
            if SETTINGS.get("show_dice", True):
                self.dice.start(result)
            else:
                self._resolve_choice_with_roll(ch, result)
            return
        self._resolve_choice(ch)

    def _resolve_choice(self, ch: Choice) -> None:
        self.player.choices_made += 1
        msgs = self.player.apply_effects(ch.effects)
        for m in msgs:
            self.message_log.add(m)
        # Flash any stat bars affected
        self._flash_stat_changes(ch.effects)
        self._goto_scene(ch.target, fade=True)

    def _resolve_choice_with_roll(self, ch: Choice, result: dict) -> None:
        self.player.choices_made += 1
        if result["success"]:
            self.player.rolls_succeeded += 1
            msgs = self.player.apply_effects(ch.effects)
            for m in msgs:
                self.message_log.add(m, color=(180, 220, 180))
            self.message_log.add(
                f"✓ {result['stat'].upper()} {result['total']} vs {result['dc']}",
                color=(180, 220, 180))
            self._flash_stat_changes(ch.effects)
            self._goto_scene(ch.target, fade=True)
        else:
            self.player.rolls_failed += 1
            target = ch.fail_target or ch.target
            effects = ch.fail_effects or {}
            msgs = self.player.apply_effects(effects)
            for m in msgs:
                self.message_log.add(m, color=(220, 160, 160))
            self.message_log.add(
                f"✗ {result['stat'].upper()} {result['total']} vs {result['dc']}",
                color=(220, 160, 160))
            self._flash_stat_changes(effects)
            self._goto_scene(target, fade=True)
        self._pending_choice = None
        self.dice.reset()

    def _flash_stat_changes(self, effects: dict) -> None:
        if not isinstance(effects, dict):
            return
        names = {sb.label.lower(): sb for sb in self.stat_bars}
        for k, v in effects.items():
            if not str(k).startswith("stat"):
                continue
            sn = None
            # colon form: value like "valor:-2"  → stat name is before ':'
            if isinstance(v, str) and ":" in v:
                sn = v.split(":", 1)[0].strip()
            # direct form: key like "stat_valor" (value is the delta)
            elif "_" in str(k):
                sn = str(k).split("_", 1)[1].strip()
            if sn and sn.lower() in names:
                names[sn.lower()].flash = 1.0

    # ── item-use ────────────────────────────────────────────────
    def _use_item(self, slot_idx: int) -> None:
        if slot_idx < 0 or slot_idx >= len(self.player.inventory):
            return
        iid = self.player.inventory[slot_idx]
        item = self.gamebook.items.get(iid)
        if not item:
            return
        if not item.consumable and not item.use_effects:
            self.message_log.add(f"Can't use {item.name}",
                                 color=(200, 180, 100))
            return
        msgs = self.player.apply_effects(item.use_effects)
        for m in msgs:
            self.message_log.add(m, color=(180, 220, 180))
        if item.consumable:
            self.player.remove_item(iid)
            self.message_log.add(f"Used: {item.name}", color=(180, 220, 180))
        self._flash_stat_changes(item.use_effects)
        self._rebuild_ui()

    # ── back / undo ─────────────────────────────────────────────
    def _go_back(self) -> None:
        if not self.player.history:
            self.message_log.add("Nothing to go back to.",
                                 color=(200, 180, 100))
            return
        prev = self.player.history.pop()
        # Switch without pushing history again
        sc = self.gamebook.get_scene(prev)
        if not sc:
            return
        self.current_scene = sc
        self.player.current_scene = prev
        self._load_scene_tex(prev)
        self.text_area.set_text(sc.body, animate=False)
        self._rebuild_ui()
        self.message_log.add(f"Returned to: {sc.title}",
                             color=(160, 200, 220))

    # ── layout ──────────────────────────────────────────────────
    def _rebuild_ui(self) -> None:
        w, h = self.window.width, self.window.height
        sw = self.SIDEBAR
        toolbar_h = self.TOOLBAR_H
        # Main area (everything left of right sidebar)
        main_left, main_w = 0, w - sw

        # ── Choice band (bottom-anchored, grows upward) ──────────────
        n_choices = len(self.current_scene.choices) if self.current_scene else 0
        bottom_pad = 30          # clearance under the lowest choice (msg log ~18)
        gap = 8
        btn_h = 32
        if n_choices == 0:
            choice_h = 45
            stride = btn_h + gap
        else:
            stride = btn_h + gap
            cap = int(h * 0.55)
            needed = bottom_pad + btn_h + (n_choices - 1) * stride + 8
            if needed > cap:
                # shrink stride + button height so everything fits on screen
                stride = max(22, (cap - bottom_pad - 8) // n_choices)
                btn_h = max(18, stride - 6)
                needed = bottom_pad + btn_h + (n_choices - 1) * stride + 8
            choice_h = max(45, min(cap, needed))

        # Illustration: fills main width, capped 16:9 then capped by available
        if self._scene_tex:
            available_h = h - toolbar_h - choice_h - 14
            ideal_h = int(main_w * 9 / 16)
            illust_h = min(ideal_h, int(available_h * 0.42))
            illust_h = max(120, illust_h)
        else:
            illust_h = 0
        text_h = h - toolbar_h - illust_h - choice_h - 14

        illust_bottom = h - toolbar_h - illust_h
        self._illust_rect = (main_left, illust_bottom, main_w, illust_h)

        # Text area below illustration
        text_left = main_left + 24
        text_w = main_w - 48
        text_bottom = choice_h + 8
        self.text_area.update_position(text_left, text_bottom, text_w, max(60, text_h - 6))

        # Choice buttons — lowest choice at bottom_pad, stacking upward
        self.choice_buttons = []
        if self.current_scene and n_choices:
            btn_w = min(main_w - 60, 820)
            btn_cx = main_left + main_w // 2
            cy0 = bottom_pad + btn_h / 2          # centre of the bottom-most choice
            for i, ch in enumerate(self.current_scene.choices):
                if isinstance(ch, dict):
                    ch = Choice.from_dict(ch)
                en = self.player.check_condition(ch.conditions)
                label = f"  {i+1}. {ch.text}"
                if ch.roll:
                    label += f"   [{ch.roll}]"
                col = (50, 65, 88) if en else (32, 32, 38)
                hcol = (70, 92, 125) if en else (32, 32, 38)
                tc = (220, 220, 225) if en else (95, 95, 100)
                if ch.roll and en:
                    col = (60, 55, 92)
                    hcol = (90, 78, 130)
                cy = cy0 + (n_choices - 1 - i) * stride
                fs = 12 if btn_h >= 28 else 11
                btn = Button(btn_cx, cy, btn_w, btn_h, label,
                             color=col, hover_color=hcol,
                             text_color=tc, align="left",
                             font_size=fs, callback=lambda idx=i: self._choose(idx),
                             enabled=en)
                if not en:
                    item_lookup = {iid: it.name for iid, it in self.gamebook.items.items()}
                    reason = self.player.condition_failure_reason(ch.conditions, item_lookup)
                    btn.subtitle = "      " + reason if reason else ""
                self.choice_buttons.append(btn)

        # Toolbar HUD buttons (right-anchored row of icons)
        right_x = main_w
        hud_specs = [
            ("≡", (48, 48, 60), (70, 70, 90), 18, self._toggle_help),
            ("⚙", (52, 52, 70), (74, 74, 100), 15, self._toggle_settings),
            ("S", (45, 65, 90), (60, 85, 115), 12, self._open_save),
            ("L", (45, 65, 90), (60, 85, 115), 12, self._open_load),
            ("C", (60, 50, 80), (80, 70, 105), 12, self._toggle_character),
            ("↶", (60, 60, 70), (85, 85, 95), 14, self._go_back),
            ("⌂", (74, 54, 54), (104, 74, 74), 14, self._confirm_exit),
        ]
        self.hud_buttons = []
        for k, spec in enumerate(hud_specs):
            glyph, c, hc, fs, cb = spec
            enabled = True
            if glyph == "↶":
                enabled = bool(self.player.history)
            self.hud_buttons.append(
                IconButton(right_x - 28 - k * 32, h - toolbar_h // 2, 28, glyph,
                           color=c, hover_color=hc, font_size=fs,
                           callback=cb, enabled=enabled))
        # left edge of the HUD row → progress text anchors to its left
        self._hud_left_x = right_x - 28 - (len(hud_specs) - 1) * 32 - 22

        # ── Right sidebar : single top-down y cursor ─────────────────
        sx = w - sw + 8
        stat_w = sw - 16
        tab_y = h - toolbar_h - 16            # tab bar centre
        self.tabbar = TabBar(w - sw + 6, tab_y, sw - 12, 26,
                             ["Stats", "Notes", "Visited"],
                             active=self.active_tab,
                             on_change=self._set_tab)

        pal = [(60, 150, 80), (180, 80, 60), (70, 110, 180),
               (180, 145, 50), (140, 105, 170), (100, 165, 145),
               (160, 95, 120), (90, 165, 165)]
        self.stat_bars = []
        bar_h = 16
        step = 22
        first_bar_cy = (tab_y - 13) - 10 - bar_h / 2   # below tab bar bottom + gap
        for i, sn in enumerate(self.gamebook.stat_names):
            v = self.player.stats.get(sn, 0)
            mx = self.player.max_stats.get(sn, v)
            self.stat_bars.append(StatBar(sx, first_bar_cy - i * step,
                                          stat_w, bar_h, sn.upper(), v, mx,
                                          bar_color=pal[i % len(pal)]))

        n_stats = len(self.gamebook.stat_names)
        last_bar_bottom = (first_bar_cy - (n_stats - 1) * step) - bar_h / 2 \
            if n_stats else (tab_y - 13)
        # gold line + inventory header positions (consumed by _draw_sidebar)
        self._gold_y = last_bar_bottom - 16
        self._panel_header_y = self._gold_y - 22

        # Inventory slots — under header, only on the Stats tab
        self.inventory_slots = []
        if self.active_tab == 0:
            slot_sz = 46
            inv_top = self._panel_header_y - 12 - slot_sz / 2
            cols = max(1, (sw - 16) // (slot_sz + 4))
            # clamp rows so the lowest slot stays above the Use button (~70)
            max_rows = max(1, int((inv_top + slot_sz / 2 - 72) // (slot_sz + 4)) + 1)
            for i, iid in enumerate(self.player.inventory):
                row = i // cols
                if row >= max_rows:
                    break
                item = self.gamebook.items.get(iid)
                name = item.name if item else iid
                desc = item.description if item else ""
                col = i % cols
                scx = sx + col * (slot_sz + 4) + slot_sz // 2
                scy = inv_top - row * (slot_sz + 4)
                slot = InventorySlot(scx, scy, slot_sz,
                                     item_id=iid, item_name=name,
                                     item_desc=desc,
                                     icon_texture=self._icon_textures.get(iid),
                                     item_type=item.item_type if item else "misc",
                                     usable=bool(item and (item.consumable
                                                           or item.use_effects)))
                slot.selected = (i == self._selected_inv)
                self.inventory_slots.append(slot)

    def _set_tab(self, idx: int) -> None:
        self.active_tab = idx
        self._rebuild_ui()

    # ── overlays ────────────────────────────────────────────────
    def _toggle_help(self):
        self.show_help = not self.show_help

    def _toggle_character(self):
        self.show_character = not self.show_character
        if self.show_character:
            self._build_character_buttons()

    def _build_character_buttons(self):
        w, h = self.window.width, self.window.height
        self.character_buttons = [
            Button(w // 2, h // 2 - 170, 120, 34, "Close",
                   color=(80, 60, 60), hover_color=(110, 80, 80),
                   font_size=12,
                   callback=lambda: setattr(self, "show_character", False))
        ]

    # ── in-game settings overlay ────────────────────────────────
    def _toggle_settings(self):
        self.show_settings = not self.show_settings
        if self.show_settings:
            self._build_settings()
        else:
            save_settings_to_disk()

    def _confirm_exit(self):
        self.show_confirm_quit = True
        self._build_confirm_quit()

    def _build_settings(self):
        w, h = self.window.width, self.window.height
        cx, cy = w / 2, h / 2
        lx = cx - 210
        sw_ = 420
        self.settings_widgets = []

        def mk_speed(v):
            SETTINGS["text_speed"] = int(v)
            self.text_area._chars_per_second = int(v)

        def mk_font(v):
            SETTINGS["font_size"] = int(v)
            self.text_area.font_size = int(v)

        def mk_vol(v):
            SETTINGS["master_volume"] = round(float(v), 2)

        self.settings_widgets.append(
            Slider(lx, cy + 92, sw_, 8, "Text speed (chars/sec)",
                   int(SETTINGS["text_speed"]), vmin=10, vmax=200, step=5,
                   on_change=mk_speed))
        self.settings_widgets.append(
            Slider(lx, cy + 44, sw_, 8, "Font size",
                   int(SETTINGS["font_size"]), vmin=10, vmax=24, step=1,
                   on_change=mk_font))
        self.settings_widgets.append(
            Slider(lx, cy - 4, sw_, 8, "Master volume",
                   float(SETTINGS["master_volume"]), vmin=0.0, vmax=1.0,
                   step=0.05, on_change=mk_vol))
        # toggles
        self.settings_widgets.append(
            ToggleButton(cx - 108, cy - 60, 200, 30, "Dice animation",
                         color=(48, 56, 74), hover_color=(64, 74, 96),
                         font_size=11,
                         value=bool(SETTINGS["show_dice"]),
                         callback=lambda v: SETTINGS.__setitem__("show_dice", bool(v))))
        self.settings_widgets.append(
            ToggleButton(cx + 108, cy - 60, 200, 30, "Autosave",
                         color=(48, 56, 74), hover_color=(64, 74, 96),
                         font_size=11,
                         value=bool(SETTINGS["auto_save"]),
                         callback=lambda v: SETTINGS.__setitem__("auto_save", bool(v))))
        # action buttons
        self.settings_widgets.append(
            Button(cx, cy - 118, 160, 34, "Close & Save",
                   color=(50, 100, 66), hover_color=(66, 130, 86),
                   font_size=12, callback=self._toggle_settings))

    def _draw_settings(self, w, h):
        Panel(w / 2, h / 2, 520, 360, "SETTINGS").draw()
        for wd in self.settings_widgets:
            wd.draw()
        arcade.draw_text(
            "Changes apply instantly · saved to config.json on close",
            w / 2, h / 2 - 150, (140, 140, 152), font_size=9,
            anchor_x="center", anchor_y="center")


    def _open_save(self):
        self.show_save_menu = True
        self.show_load_menu = False
        self._build_sl("save")

    def _open_load(self):
        self.show_load_menu = True
        self.show_save_menu = False
        self._build_sl("load")

    def _build_sl(self, mode: str) -> None:
        w, h = self.window.width, self.window.height
        self.save_buttons = []
        slots = ["slot_1", "slot_2", "slot_3", "quicksave", "autosave"]
        labels = ["Slot 1", "Slot 2", "Slot 3", "Quicksave", "Autosave"]
        existing = {s["slot"]: s for s in list_saves(self.gamebook.folder_path)}
        cy = h // 2 + 110
        for slot, label in zip(slots, labels):
            meta = existing.get(slot)
            cb = (lambda n=slot: self._do_save(n)) if mode == "save" \
                else (lambda n=slot: self._do_load(n))
            btn = Button(w // 2, cy, 480, 44,
                         f"  {label}",
                         color=(50, 60, 84) if meta else (38, 42, 56),
                         hover_color=(72, 88, 120),
                         font_size=12, align="left",
                         callback=cb,
                         enabled=(mode == "save" or meta is not None))
            if meta:
                t = time.strftime("%Y-%m-%d %H:%M",
                                  time.localtime(meta["timestamp"]))
                btn.subtitle = (f"      {meta.get('scene_title') or meta['scene']}"
                                f"  ·  {t}  ·  {_fmt_time(meta.get('play_seconds', 0))}")
            else:
                btn.subtitle = "      [empty]"
            self.save_buttons.append(btn)
            cy -= 50
        self.save_buttons.append(Button(w // 2, h // 2 - 200, 140, 32,
                                        "Cancel",
                                        color=(95, 50, 50),
                                        hover_color=(125, 70, 70),
                                        font_size=12, callback=self._close_sl))

    def _do_save(self, slot: str) -> None:
        title = self.current_scene.title if self.current_scene else ""
        save_game(self.player, self.gamebook.folder_path,
                  slot_name=slot, scene_title=title)
        self.message_log.add(f"Saved to {slot}", color=(120, 220, 130))
        self._close_sl()

    def _do_load(self, slot: str) -> None:
        ps = load_game(self.gamebook.folder_path, slot)
        if ps:
            self.player = ps
            self._goto_scene(self.player.current_scene, fade=False)
            self.message_log.add(f"Loaded {slot}", color=(120, 200, 230))
        else:
            self.message_log.add(f"No save in {slot}", color=(220, 100, 100))
        self._close_sl()

    def _close_sl(self):
        self.show_save_menu = False
        self.show_load_menu = False
        self.save_buttons = []

    def _quicksave(self):
        self._do_save("quicksave")

    def _build_ending_buttons(self):
        w, h = self.window.width, self.window.height
        self.ending_buttons = [
            Button(w // 2 - 100, 120, 180, 38, "Restart Adventure",
                   color=(50, 110, 70), hover_color=(70, 140, 90),
                   font_size=13, callback=self._restart),
            Button(w // 2 + 100, 120, 180, 38, "Return to Library",
                   color=(80, 70, 110), hover_color=(105, 95, 145),
                   font_size=13,
                   callback=lambda: self.window.show_view(MainMenuView())),
        ]

    def _restart(self):
        self.player = self.gamebook.create_player()
        self.show_ending = False
        self._goto_scene(self.gamebook.start_scene, fade=False)

    def _build_confirm_quit(self):
        w, h = self.window.width, self.window.height
        self.confirm_buttons = [
            Button(w // 2 - 90, h // 2 - 30, 150, 36, "Save & Quit",
                   color=(50, 110, 70), hover_color=(70, 140, 90),
                   font_size=12,
                   callback=lambda: (self._do_save("quicksave"),
                                     self.window.show_view(MainMenuView()))),
            Button(w // 2 + 90, h // 2 - 30, 150, 36, "Quit Without Saving",
                   color=(95, 50, 50), hover_color=(125, 70, 70),
                   font_size=12,
                   callback=lambda: self.window.show_view(MainMenuView())),
            Button(w // 2, h // 2 - 80, 110, 30, "Cancel",
                   color=(60, 60, 70), hover_color=(85, 85, 95),
                   font_size=11,
                   callback=lambda: setattr(self, "show_confirm_quit", False)),
        ]

    # ── drawing ─────────────────────────────────────────────────
    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        sw = self.SIDEBAR
        main_w = w - sw
        toolbar_h = self.TOOLBAR_H

        # Background image (main area)
        if self._bg_tex:
            arcade.draw_texture_rect(
                self._bg_tex,
                XYWH(main_w / 2, h / 2, main_w, h))

        # Right sidebar background
        arcade.draw_rect_filled(XYWH(w - sw / 2, h / 2, sw, h),
                                color=(20, 20, 28))
        arcade.draw_line(w - sw, 0, w - sw, h, (50, 50, 62), 1)

        # Toolbar
        arcade.draw_rect_filled(XYWH(w / 2, h - toolbar_h / 2, w, toolbar_h),
                                color=(26, 26, 36))
        arcade.draw_line(0, h - toolbar_h, w, h - toolbar_h, (50, 50, 62), 1)
        if self.current_scene:
            arcade.draw_text(self.current_scene.title,
                             14, h - toolbar_h / 2,
                             (228, 208, 158), font_size=15,
                             anchor_x="left", anchor_y="center", bold=True)
            # Visited progress — anchored left of the HUD icon row
            prog = (f"{len(self.player.visited_scenes)}/{len(self.gamebook.scenes)}  "
                    f"·  {_fmt_time(self.player.play_seconds)}")
            prog_x = getattr(self, "_hud_left_x", main_w - 200)
            arcade.draw_text(prog, prog_x, h - toolbar_h / 2,
                             (130, 140, 155), font_size=10,
                             anchor_x="right", anchor_y="center")

        # Illustration zone
        il, ib, iw, ih = self._illust_rect
        if self._scene_tex and ih > 0:
            arcade.draw_rect_filled(XYWH(il + iw / 2, ib + ih / 2, iw, ih),
                                    color=(8, 8, 14))
            arcade.draw_texture_rect(
                self._scene_tex,
                XYWH(il + iw / 2, ib + ih / 2, iw, ih))
            # subtle bottom-fade for legibility above text
            for i in range(8):
                a = 22 - i * 2
                arcade.draw_rect_filled(
                    XYWH(il + iw / 2, ib + 4 + i * 2, iw, 2),
                    color=(8, 8, 14, max(0, a)))

        # Text area
        self.text_area.draw()

        # Skip hint while animating
        if self.text_area.is_animating:
            arcade.draw_text(
                "▷  SPACE / CLICK to skip",
                main_w / 2,
                self.text_area.bottom + self.text_area.height + 4,
                (180, 170, 110, 200), font_size=10,
                anchor_x="center", anchor_y="bottom")

        # Choices
        for b in self.choice_buttons:
            b.draw()

        # End-of-branch hint
        if (self.current_scene and not self.current_scene.choices
                and not self.show_ending):
            cx = main_w // 2
            arcade.draw_rect_filled(XYWH(cx, 50, 280, 32),
                                    color=(40, 40, 52, 220))
            arcade.draw_text("Press ESC to return to library",
                             cx, 50, (180, 180, 190),
                             font_size=11, anchor_x="center", anchor_y="center")

        # ── Sidebar contents ────────────────────────────────────
        self._draw_sidebar(w, h, sw)

        # HUD buttons (toolbar)
        for b in self.hud_buttons:
            b.draw()

        # Message log near bottom-center of main area
        ly = 86 if (self.current_scene
                    and not self.current_scene.choices) else 18
        self.message_log.draw(main_w / 2, ly)

        # Tooltip
        self.tooltip.draw(w, h)

        # Dice
        if self.dice.active:
            self.dice.draw(main_w / 2, h / 2)

        # Fade overlay
        if self._fade_alpha > 0:
            arcade.draw_rect_filled(XYWH(w / 2, h / 2, w, h),
                                    color=(0, 0, 0, self._fade_alpha))

        # Modal overlays
        if self.show_help:
            self._draw_help(w, h)
        if self.show_save_menu or self.show_load_menu:
            self._draw_sl(w, h)
        if self.show_character:
            self._draw_character(w, h)
        if self.show_settings:
            self._draw_settings(w, h)
        if self.show_confirm_quit:
            self._draw_confirm_quit(w, h)
        if self.show_ending:
            self._draw_ending(w, h)

    def _draw_sidebar(self, w, h, sw):
        toolbar_h = self.TOOLBAR_H
        # Title
        arcade.draw_text(self.gamebook.title[:26], w - sw / 2,
                         h - toolbar_h / 2, (140, 140, 150),
                         font_size=10, anchor_x="center", anchor_y="center")
        if self.tabbar:
            self.tabbar.draw()
        # Stats area always shown
        for sb in self.stat_bars:
            sb.draw()
        # Gold line
        # Gold line (position computed in _rebuild_ui via running y-cursor)
        gold_y = getattr(self, "_gold_y",
                         h - toolbar_h - 56 - len(self.gamebook.stat_names) * 22 - 14)
        header_y = getattr(self, "_panel_header_y", gold_y - 22)
        arcade.draw_text(f"Gold: {self.player.gold}",
                         w - sw + 10, gold_y,
                         (220, 195, 90), font_size=11,
                         anchor_x="left", anchor_y="center")

        if self.active_tab == 0:
            arcade.draw_text(
                f"INVENTORY  {len(self.player.inventory)}/{self.player.max_inventory}",
                w - sw + 10, header_y, (135, 135, 145),
                font_size=9, anchor_x="left", anchor_y="center", bold=True)
            for s in self.inventory_slots:
                s.draw()
            # Use button for selected slot
            if 0 <= self._selected_inv < len(self.player.inventory):
                iid = self.player.inventory[self._selected_inv]
                item = self.gamebook.items.get(iid)
                if item and (item.consumable or item.use_effects):
                    use_btn = Button(w - sw / 2, 36, sw - 28, 28,
                                     f"Use {item.name[:18]}",
                                     color=(50, 110, 65),
                                     hover_color=(70, 140, 85),
                                     font_size=10,
                                     callback=lambda: self._use_item(self._selected_inv))
                    # Cache for hit-test
                    self._use_button = use_btn
                    use_btn.draw()
                else:
                    self._use_button = None
            else:
                self._use_button = None

        elif self.active_tab == 1:
            # Notebook + codewords
            arcade.draw_text("NOTEBOOK", w - sw + 10, header_y,
                             (135, 135, 145), font_size=9,
                             anchor_x="left", anchor_y="center", bold=True)
            ny = header_y - 18
            for note in self.player.notebook[-12:]:
                arcade.draw_text(f"· {note}", w - sw + 14, ny,
                                 (190, 185, 170), font_size=9,
                                 anchor_x="left", anchor_y="top",
                                 width=sw - 24, multiline=True)
                ny -= 28
            # codewords
            ny = max(ny, 80)
            arcade.draw_text("CODEWORDS", w - sw + 10, 70,
                             (135, 135, 145), font_size=9,
                             anchor_x="left", anchor_y="center", bold=True)
            cwy = 50
            for cw_word in self.player.codewords:
                arcade.draw_text(f"  ◊ {cw_word}", w - sw + 14, cwy,
                                 (170, 200, 230), font_size=9,
                                 anchor_x="left", anchor_y="center")
                cwy -= 14

        elif self.active_tab == 2:
            arcade.draw_text(
                f"VISITED  ({len(self.player.visited_scenes)}/{len(self.gamebook.scenes)})",
                w - sw + 10, header_y, (135, 135, 145),
                font_size=9, anchor_x="left", anchor_y="center", bold=True)
            ny = header_y - 18
            for sid in reversed(self.player.visited_scenes[-18:]):
                sc = self.gamebook.scenes.get(sid)
                if not sc:
                    continue
                color = (220, 200, 130) if sid == self.player.current_scene \
                    else (180, 180, 190)
                arcade.draw_text(sc.title[:24], w - sw + 14, ny,
                                 color, font_size=9,
                                 anchor_x="left", anchor_y="center")
                ny -= 14
                if ny < 30:
                    break

    def _draw_help(self, w, h):
        Panel(w / 2, h / 2, 460, 380, "PLAYER CONTROLS").draw()
        lines = [
            "1 – 9        Make choice / advance",
            "Space/Click  Skip text · roll dice · advance",
            "S / L        Save / Load slot menu",
            "R            Quicksave",
            "I            Inventory tab",
            "C            Character sheet",
            "O / ⚙        Settings (text speed, font, volume…)",
            "B            Back one scene (history)",
            "TAB          Cycle sidebar tabs",
            "H            This help    ·    ⌂  Quit to library",
            "F            Toggle fullscreen",
            "E            Switch to Studio editor",
            "ESC          Return to library",
        ]
        cy = h / 2 + 130
        for ln in lines:
            arcade.draw_text(ln, w / 2 - 200, cy, (200, 200, 210),
                             font_size=12, anchor_x="left", anchor_y="center")
            cy -= 22

    def _draw_sl(self, w, h):
        label = "SAVE GAME" if self.show_save_menu else "LOAD GAME"
        Panel(w / 2, h / 2, 540, 440, label).draw()
        for b in self.save_buttons:
            b.draw()

    def _draw_character(self, w, h):
        Panel(w / 2, h / 2, 520, 460, "CHARACTER SHEET").draw()
        x0 = w / 2 - 230
        y = h / 2 + 175
        arcade.draw_text(self.player.name, x0, y, (235, 215, 150),
                         font_size=16, anchor_x="left", anchor_y="center", bold=True)
        y -= 30
        arcade.draw_text(f"Adventure: {self.gamebook.title}", x0, y,
                         (180, 180, 190), font_size=11,
                         anchor_x="left", anchor_y="center")
        y -= 24
        # Stats
        for sn in self.gamebook.stat_names:
            v = self.player.stats.get(sn, 0)
            mx = self.player.max_stats.get(sn, v)
            arcade.draw_text(f"{sn.upper():<12}", x0, y,
                             (190, 180, 130), font_size=12,
                             anchor_x="left", anchor_y="center", bold=True)
            arcade.draw_text(f"{v} / {mx}", x0 + 130, y,
                             (220, 220, 225), font_size=12,
                             anchor_x="left", anchor_y="center")
            y -= 20
        y -= 8
        # Run statistics
        arcade.draw_text("ADVENTURE LOG", x0, y, (190, 180, 130),
                         font_size=11, anchor_x="left", anchor_y="center", bold=True)
        y -= 18
        rows = [
            ("Time played", _fmt_time(self.player.play_seconds)),
            ("Choices made", str(self.player.choices_made)),
            ("Skill checks won", str(self.player.rolls_succeeded)),
            ("Skill checks failed", str(self.player.rolls_failed)),
            ("Scenes visited", f"{len(self.player.visited_scenes)} / {len(self.gamebook.scenes)}"),
            ("Gold", str(self.player.gold)),
        ]
        for label, value in rows:
            arcade.draw_text(label, x0, y, (170, 170, 180),
                             font_size=10, anchor_x="left", anchor_y="center")
            arcade.draw_text(value, x0 + 200, y, (220, 220, 230),
                             font_size=10, anchor_x="left", anchor_y="center")
            y -= 16
        # Achievements
        y -= 8
        arcade.draw_text("ACHIEVEMENTS", x0, y, (190, 180, 130),
                         font_size=11, anchor_x="left", anchor_y="center", bold=True)
        y -= 18
        if not self.player.achievements:
            arcade.draw_text("(none yet)", x0, y, (140, 140, 150),
                             font_size=10, anchor_x="left", anchor_y="center")
        else:
            for ach in self.player.achievements:
                meta = self.gamebook.achievements.get(ach, {}) \
                    if isinstance(self.gamebook.achievements, dict) else {}
                name = meta.get("name", ach) if isinstance(meta, dict) else ach
                arcade.draw_text(f"★ {name}", x0, y,
                                 (180, 220, 180), font_size=10,
                                 anchor_x="left", anchor_y="center")
                y -= 14
        for b in self.character_buttons:
            b.draw()

    def _draw_confirm_quit(self, w, h):
        Panel(w / 2, h / 2, 460, 220, "QUIT TO LIBRARY?").draw()
        arcade.draw_text("Save your progress before leaving?",
                         w / 2, h / 2 + 30, (200, 200, 210),
                         font_size=13, anchor_x="center", anchor_y="center")
        for b in self.confirm_buttons:
            b.draw()

    def _draw_ending(self, w, h):
        Panel(w / 2, h / 2, 620, 460,
              "✦  ADVENTURE'S END  ✦").draw()
        cy = h / 2 + 160
        title = (self.current_scene.title if self.current_scene
                 else "End")
        arcade.draw_text(title, w / 2, cy, (235, 215, 150),
                         font_size=20, anchor_x="center", anchor_y="center", bold=True)
        cy -= 36
        # Tag-derived flavour
        tags = self.current_scene.tags if self.current_scene else []
        if "victory" in tags:
            flavour = "Triumph! Your name will be sung in the halls."
            colour = (160, 220, 170)
        elif "defeat" in tags or "death" in tags:
            flavour = "Your tale ends in shadow."
            colour = (220, 160, 160)
        else:
            flavour = "And so concludes your journey."
            colour = (200, 200, 215)
        arcade.draw_text(flavour, w / 2, cy, colour,
                         font_size=12, anchor_x="center", anchor_y="center")
        cy -= 38
        rows = [
            ("Time played",          _fmt_time(self.player.play_seconds)),
            ("Choices made",         str(self.player.choices_made)),
            ("Skill checks won",     str(self.player.rolls_succeeded)),
            ("Skill checks failed",  str(self.player.rolls_failed)),
            ("Scenes discovered",
             f"{len(self.player.visited_scenes)} / {len(self.gamebook.scenes)}"),
            ("Gold remaining",       str(self.player.gold)),
            ("Items in inventory",   str(len(self.player.inventory))),
        ]
        x0 = w / 2 - 180
        for label, value in rows:
            arcade.draw_text(label, x0, cy, (170, 170, 185),
                             font_size=11, anchor_x="left", anchor_y="center")
            arcade.draw_text(value, x0 + 240, cy, (225, 215, 175),
                             font_size=11, anchor_x="left", anchor_y="center", bold=True)
            cy -= 18
        cy -= 6
        # Achievements
        if self.player.achievements:
            arcade.draw_text("ACHIEVEMENTS UNLOCKED", w / 2, cy,
                             (200, 180, 130), font_size=11,
                             anchor_x="center", anchor_y="center", bold=True)
            cy -= 18
            for ach in self.player.achievements:
                meta = self.gamebook.achievements.get(ach, {}) \
                    if isinstance(self.gamebook.achievements, dict) else {}
                name = meta.get("name", ach) if isinstance(meta, dict) else ach
                arcade.draw_text(f"★ {name}", w / 2, cy,
                                 (180, 220, 180), font_size=10,
                                 anchor_x="center", anchor_y="center")
                cy -= 14
        for b in self.ending_buttons:
            b.draw()

    # ── input ───────────────────────────────────────────────────
    def on_key_press(self, key, mods):
        # Modal-first
        if self.show_ending:
            if km(key, "exit"):
                self.window.show_view(MainMenuView())
            return
        if self.show_help:
            if km(key, "exit") or km(key, "help"):
                self.show_help = False
            return
        if self.show_character:
            if km(key, "exit") or km(key, "character"):
                self.show_character = False
            return
        if self.show_settings:
            if km(key, "exit") or key == arcade.key.O:
                self._toggle_settings()
            return
        if self.show_save_menu or self.show_load_menu:
            if km(key, "exit"):
                self._close_sl()
            return
        if self.show_confirm_quit:
            if km(key, "exit"):
                self.show_confirm_quit = False
            return
        if self.dice.active:
            if self.dice.finished and (km(key, "exit") or
                                       key == arcade.key.SPACE
                                       or km(key, "exit")):
                if self._pending_choice:
                    ch, _idx = self._pending_choice
                    self._resolve_choice_with_roll(ch, self.dice.result)
            return

        if km(key, "exit"):
            self.show_confirm_quit = True
            self._build_confirm_quit()
        elif km(key, "fullscreen"):
            self.window.set_fullscreen(not self.window.fullscreen)
            self._rebuild_ui()
        elif km(key, "help"):
            self.show_help = True
        elif km(key, "character"):
            self._toggle_character()
        elif key == arcade.key.O:
            self._toggle_settings()
        elif km(key, "save"):
            self._open_save()
        elif km(key, "load"):
            self._open_load()
        elif km(key, "quicksave"):
            self._quicksave()
        elif km(key, "back"):
            self._go_back()
        elif km(key, "editor_toggle"):
            self.window.show_view(StudioView(self.gamebook))
        elif km(key, "settings") or key == arcade.key.TAB:
            self._set_tab((self.active_tab + 1) % 3)
        elif km(key, "inventory"):
            self._set_tab(0)
        elif km(key, "notebook"):
            self._set_tab(1)
        elif key == arcade.key.SPACE:
            if self.text_area.is_animating:
                self.text_area.skip_animation()
        else:
            for i in range(1, 10):
                if km(key, f"choice_{i}"):
                    self._choose(i - 1)
                    return

    def on_mouse_motion(self, x, y, dx, dy):
        for b in self.choice_buttons:
            b.on_mouse_motion(x, y)
        for b in self.hud_buttons:
            b.on_mouse_motion(x, y)
        for b in self.save_buttons:
            b.on_mouse_motion(x, y)
        for b in self.character_buttons:
            b.on_mouse_motion(x, y)
        for b in self.ending_buttons:
            b.on_mouse_motion(x, y)
        for b in self.confirm_buttons:
            b.on_mouse_motion(x, y)
        for wd in self.settings_widgets:
            if hasattr(wd, "on_mouse_motion"):
                wd.on_mouse_motion(x, y)
        if self.tabbar:
            self.tabbar.on_mouse_motion(x, y)
        # Inventory hover -> tooltip + selected
        found = False
        for slot in self.inventory_slots:
            slot.hovered = slot.contains(x, y)
            if slot.hovered and slot.item_desc:
                hint = slot.item_desc
                if slot.usable:
                    hint += "\n(Click to select, then Use)"
                self.tooltip.show(x, y, slot.item_name, hint)
                found = True
        if not found:
            self.tooltip.hide()
        # Use button hover
        if getattr(self, "_use_button", None):
            self._use_button.on_mouse_motion(x, y)

    def on_mouse_press(self, x, y, btn, mods):
        # Modals first
        if self.show_ending:
            for b in self.ending_buttons:
                if b.on_mouse_press(x, y, btn):
                    return
            return
        if self.show_save_menu or self.show_load_menu:
            for b in self.save_buttons:
                if b.on_mouse_press(x, y, btn):
                    return
            return
        if self.show_character:
            for b in self.character_buttons:
                if b.on_mouse_press(x, y, btn):
                    return
            return
        if self.show_settings:
            for wd in self.settings_widgets:
                if wd.on_mouse_press(x, y, btn):
                    return
            return
        if self.show_confirm_quit:
            for b in self.confirm_buttons:
                if b.on_mouse_press(x, y, btn):
                    return
            return
        # Dice click-through
        if self.dice.active:
            if self.dice.finished and self._pending_choice:
                ch, _idx = self._pending_choice
                self._resolve_choice_with_roll(ch, self.dice.result)
            return
        # Skip text on any click in main area
        if self.text_area.is_animating:
            self.text_area.skip_animation()
            return
        # HUD then choice buttons
        for b in self.hud_buttons:
            if b.on_mouse_press(x, y, btn):
                return
        for b in self.choice_buttons:
            if b.on_mouse_press(x, y, btn):
                return
        if self.tabbar and self.tabbar.on_mouse_press(x, y, btn):
            return
        # Inventory click → select then second-click → use
        for i, slot in enumerate(self.inventory_slots):
            if slot.contains(x, y):
                if self._selected_inv == i and slot.usable:
                    self._use_item(i)
                    self._selected_inv = -1
                else:
                    self._selected_inv = i
                self._rebuild_ui()
                return
        # Use button
        if getattr(self, "_use_button", None):
            if self._use_button.on_mouse_press(x, y, btn):
                return
        self._selected_inv = -1
        self._rebuild_ui()

    def on_mouse_drag(self, x, y, dx, dy, buttons, mods):
        if self.show_settings:
            for wd in self.settings_widgets:
                if hasattr(wd, "on_mouse_drag"):
                    wd.on_mouse_drag(x, y, dx, dy, buttons, mods)

    def on_mouse_release(self, x, y, btn, mods):
        if self.show_settings:
            for wd in self.settings_widgets:
                if hasattr(wd, "on_mouse_release"):
                    wd.on_mouse_release(x, y, btn)

    def on_mouse_scroll(self, x, y, sx, sy):
        if self.show_settings:
            return
        self.text_area.on_mouse_scroll(x, y, sx, sy)


# ═══════════════════════════════════════════════════════════════
# STUDIO  (node-graph editor with inspector, choice editor, validation)
# ═══════════════════════════════════════════════════════════════
class StudioView(arcade.View):
    """Visual editor for a gamebook.

    Features
    --------
    * Pan (middle-drag) and zoom (scroll) on the node graph.
    * Click a node to select; drag with left button to reposition.
    * Inspector panel (right side) edits title, body, tags, choices.
    * Add / duplicate / delete scene buttons.
    * Validate report identifies broken targets, dead ends, orphans.
    * Save persists positions and edits back to project.json.
    """

    def __init__(self, gamebook: GameBook):
        super().__init__()
        self.background_color = (22, 22, 28)
        self.gamebook = gamebook
        self.camera = Camera2D()
        self.ui_camera = Camera2D()
        self._cam_pos = (0.0, 0.0)
        self.zoom = 1.0
        self.nodes: dict[str, NodeWidget] = {}
        self.selected_node: str | None = None
        self.panning = False
        self.show_help = False
        self.show_validation = False
        self.validation_report: dict | None = None

        # editable text inputs (built lazily per selection)
        self.title_input: TextInput | None = None
        self.body_input: TextInput | None = None
        self.tags_input: TextInput | None = None
        # choice editor
        self.editing_choice: int = -1
        self.choice_text_input: TextInput | None = None
        self.choice_target_input: TextInput | None = None
        self.choice_inputs: list = []          # full rich-editor field list
        self._choice_overflow: int = 0
        self._choices_header_y: float = 0.0

        self.toolbar_buttons: list[Button] = []
        self.inspector_buttons: list[Button] = []
        self.choice_buttons: list[Button] = []
        self.notice: str = ""
        self.notice_timer: float = 0.0

        # confirmation dialog
        self.confirm_text: str = ""
        self.confirm_action = None

        self._build_nodes()

    # ── nodes ────────────────────────────────────────────────────
    def _build_nodes(self) -> None:
        self.nodes = {}
        for sid, sc in self.gamebook.scenes.items():
            tags = sc.tags or []
            if sid == self.gamebook.start_scene or "start" in tags:
                c = (40, 100, 60)
            elif "ending" in tags or "victory" in tags:
                c = (100, 80, 40)
            elif "combat" in tags:
                c = (120, 50, 50)
            elif "boss" in tags or "climax" in tags:
                c = (130, 40, 80)
            elif "encounter" in tags:
                c = (50, 80, 110)
            elif "revelation" in tags or "lore" in tags:
                c = (90, 60, 110)
            else:
                c = (50, 60, 80)
            n = NodeWidget(sid, sc.title, sc.position[0], sc.position[1], color=c)
            n.choice_count = len(sc.choices)
            self.nodes[sid] = n

    def _refresh_node_visuals(self) -> None:
        for sid, n in self.nodes.items():
            sc = self.gamebook.scenes.get(sid)
            if sc:
                n.title = sc.title
                n.choice_count = len(sc.choices)
                n.has_error = False
        if self.validation_report:
            for sid, _, _ in self.validation_report.get("broken_targets", []):
                if sid in self.nodes:
                    self.nodes[sid].has_error = True
            for sid in self.validation_report.get("dead_ends", []):
                if sid in self.nodes:
                    self.nodes[sid].has_error = True

    # ── toolbar / inspector ──────────────────────────────────────
    def _rebuild_toolbar(self) -> None:
        h = self.window.height
        self.toolbar_buttons = [
            Button(60, h - 20, 100, 30, "← Menu", color=(72, 52, 42),
                   hover_color=(100, 72, 52), font_size=10,
                   callback=lambda: self.window.show_view(MainMenuView())),
            Button(170, h - 20, 100, 30, "▶ Play Test",
                   color=(36, 82, 46), hover_color=(52, 112, 62),
                   font_size=10, callback=self._play_test),
            Button(280, h - 20, 100, 30, "💾 Save",
                   color=(46, 62, 92), hover_color=(62, 86, 126),
                   font_size=10, callback=self._save),
            Button(390, h - 20, 100, 30, "✓ Validate",
                   color=(64, 72, 56), hover_color=(86, 96, 70),
                   font_size=10, callback=self._validate),
            Button(500, h - 20, 100, 30, "⊞ Fit View",
                   color=(52, 52, 72), hover_color=(72, 72, 102),
                   font_size=10, callback=self._fit),
            Button(610, h - 20, 100, 30, "+ Scene",
                   color=(48, 80, 56), hover_color=(64, 110, 76),
                   font_size=10, callback=self._add_scene),
        ]

    def _rebuild_inspector(self) -> None:
        """Rebuild text inputs and per-choice buttons for the selected scene."""
        self.inspector_buttons = []
        self.choice_buttons = []
        self.title_input = None
        self.body_input = None
        self.tags_input = None
        self.choice_text_input = None
        self.choice_target_input = None
        self.choice_inputs = []
        self._choice_overflow = 0
        if not self.selected_node or self.selected_node not in self.gamebook.scenes:
            return

        sc = self.gamebook.scenes[self.selected_node]
        w, h = self.window.width, self.window.height
        sw = max(280, int(w * 0.30))
        x0 = w - sw + 12
        iw = sw - 24

        # ── top-down cursor (each field reserves 14px for its caption) ──
        cursor = h - 74
        # title
        title_h = 26
        ty = cursor - 13 - title_h
        self.title_input = TextInput(x0, ty, iw, title_h, sc.title,
                                     placeholder="Scene title", font_size=11)
        cursor = ty - 10
        # body
        by_h = min(150, max(90, int(h * 0.22)))
        by = cursor - 13 - by_h
        self.body_input = TextInput(x0, by, iw, by_h, sc.body,
                                    multiline=True, placeholder="Scene body",
                                    font_size=10)
        cursor = by - 10
        # tags
        tags_h = 24
        tgy = cursor - 13 - tags_h
        self.tags_input = TextInput(x0, tgy, iw, tags_h,
                                    ", ".join(sc.tags or []),
                                    placeholder="tags, comma-separated",
                                    font_size=9)
        cursor = tgy - 8

        # ── pinned action bar (above the status bar at y=14/h=28) ──────
        ay = 56
        is_start = (sc.id == self.gamebook.start_scene)
        bw = (iw - 3 * 7) / 4
        def bx(k):
            return x0 + bw / 2 + k * (bw + 7)
        self.inspector_buttons = [
            Button(bx(0), ay, bw, 28, "Apply", color=(46, 86, 56),
                   hover_color=(62, 116, 76), font_size=9,
                   callback=self._apply_props),
            Button(bx(1), ay, bw, 28, "Dup", color=(58, 72, 96),
                   hover_color=(78, 96, 128), font_size=9,
                   callback=self._duplicate_scene),
            Button(bx(2), ay, bw, 28, "Delete", color=(112, 52, 52),
                   hover_color=(146, 70, 70), font_size=9,
                   callback=lambda: self._confirm(
                       f"Delete scene '{sc.id}'?", self._delete_scene)),
            Button(bx(3), ay, bw, 28,
                   "★ Start" if is_start else "Set Start",
                   color=(86, 74, 42) if is_start else (54, 60, 76),
                   hover_color=(112, 96, 56) if is_start else (74, 82, 104),
                   font_size=9, enabled=not is_start,
                   callback=self._set_start),
        ]

        # ── choice rows (clamped so they never collide with action bar) ─
        self._choices_header_y = cursor - 4
        row_h = 26
        row_gap = 7
        row_top = self._choices_header_y - 20          # first row centre band
        action_top = ay + 14 + 10                       # action-bar top + margin
        usable = row_top - action_top
        # one slot reserved for the "+ Choice" button
        max_slots = max(1, int(usable // (row_h + row_gap)))
        n = len(sc.choices)
        shown = min(n, max(0, max_slots - 1))
        self._choice_overflow = n - shown

        cy = row_top
        for i in range(shown):
            ch = sc.choices[i]
            d = ch.to_dict() if isinstance(ch, Choice) else dict(ch)
            text_preview = (d.get("text", "") or "")[:32]
            target = d.get("target", "") or "—"
            badge = ""
            if d.get("roll"):
                badge = "  ⚄"
            self.choice_buttons.append(Button(
                x0, cy, iw - 96, row_h,
                f"{i + 1}. {text_preview}{badge}",
                subtitle=f"   → {target}",
                color=(46, 52, 70), hover_color=(64, 72, 96),
                font_size=9, align="left",
                callback=lambda i=i: self._edit_choice(i)))
            self.choice_buttons.append(Button(
                x0 + iw - 92, cy, 28, row_h, "↑",
                color=(58, 58, 78), hover_color=(78, 78, 102),
                font_size=10, callback=lambda i=i: self._move_choice(i, -1)))
            self.choice_buttons.append(Button(
                x0 + iw - 60, cy, 28, row_h, "↓",
                color=(58, 58, 78), hover_color=(78, 78, 102),
                font_size=10, callback=lambda i=i: self._move_choice(i, 1)))
            self.choice_buttons.append(Button(
                x0 + iw - 28, cy, 26, row_h, "✕",
                color=(96, 50, 50), hover_color=(126, 70, 70),
                font_size=10, callback=lambda i=i: self._delete_choice(i)))
            cy -= (row_h + row_gap)

        # add-choice button on the final slot
        self.choice_buttons.append(Button(
            x0 + iw // 2 - 60, cy, 120, row_h, "+ Choice",
            color=(48, 72, 60), hover_color=(64, 100, 82),
            font_size=10, callback=self._add_choice))

    def _set_start(self) -> None:
        if self.selected_node and self.selected_node in self.gamebook.scenes:
            self.gamebook.start_scene = self.selected_node
            # keep the "start" tag aligned with the actual start scene
            for sid, s in self.gamebook.scenes.items():
                if "start" in (s.tags or []) and sid != self.selected_node:
                    s.tags = [t for t in s.tags if t != "start"]
            tgt = self.gamebook.scenes[self.selected_node]
            if "start" not in (tgt.tags or []):
                tgt.tags = list(tgt.tags or []) + ["start"]
            self._build_nodes()        # recolour the start node
            self._rebuild_inspector()
            self._toast(f"Start scene → {self.selected_node}")


    # ── toolbar callbacks ────────────────────────────────────────
    def _play_test(self) -> None:
        s = self.selected_node or self.gamebook.start_scene
        self.window.show_view(PlayerView(self.gamebook, start_scene=s))

    def _save(self) -> None:
        self._apply_props(silent=True)
        for sid, n in self.nodes.items():
            sc = self.gamebook.scenes.get(sid)
            if sc:
                sc.position = (n.x, n.y)
        try:
            self.gamebook.save()
            self._toast("Project saved.")
        except Exception as e:
            self._toast(f"Save error: {e}")

    def _validate(self) -> None:
        self.validation_report = self.gamebook.validate()
        self.show_validation = True
        self._refresh_node_visuals()

    def _fit(self) -> None:
        if not self.nodes:
            return
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        self._cam_pos = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        span = max(max(xs) - min(xs), max(ys) - min(ys), 100)
        self.zoom = min(2.0, max(0.3, self.window.width / (span + 400)))

    # ── scene operations ─────────────────────────────────────────
    def _add_scene(self) -> None:
        sid = self.gamebook.new_scene_id()
        # place near the centre of the camera, offset to avoid overlap
        cx, cy = self._cam_pos
        sc = Scene(id=sid, title="New scene",
                   body="Write the scene description here.",
                   choices=[], tags=[], position=(cx, cy))
        self.gamebook.scenes[sid] = sc
        c = (50, 60, 80)
        n = NodeWidget(sid, sc.title, cx, cy, color=c)
        n.choice_count = 0
        self.nodes[sid] = n
        self.selected_node = sid
        self._rebuild_inspector()
        self._toast(f"Added {sid}")

    def _duplicate_scene(self) -> None:
        if not self.selected_node:
            return
        src = self.gamebook.scenes.get(self.selected_node)
        if not src:
            return
        sid = self.gamebook.new_scene_id(prefix=src.id.split("_")[0] or "scene")
        new_sc = Scene(
            id=sid, title=f"{src.title} (copy)", body=src.body,
            choices=[Choice(**c.to_dict()) for c in src.choices],
            tags=list(src.tags), illustration=src.illustration,
            sound=src.sound, ambient=src.ambient,
            on_enter=list(src.on_enter) if src.on_enter else [],
            position=(src.position[0] + 200, src.position[1] - 60),
        )
        self.gamebook.scenes[sid] = new_sc
        n = NodeWidget(sid, new_sc.title, *new_sc.position, color=(50, 60, 80))
        n.choice_count = len(new_sc.choices)
        self.nodes[sid] = n
        self.selected_node = sid
        self._rebuild_inspector()
        self._toast(f"Duplicated → {sid}")

    def _delete_scene(self) -> None:
        sid = self.selected_node
        if not sid or sid not in self.gamebook.scenes:
            return
        if sid == self.gamebook.start_scene:
            self._toast("Cannot delete the start scene.")
            return
        del self.gamebook.scenes[sid]
        self.nodes.pop(sid, None)
        # purge dangling targets that point at it
        for sc in self.gamebook.scenes.values():
            for ch in sc.choices:
                d = ch if isinstance(ch, dict) else None
                if isinstance(ch, Choice):
                    if ch.target == sid:
                        ch.target = ""
                    if ch.fail_target == sid:
                        ch.fail_target = ""
        self.selected_node = None
        self._rebuild_inspector()
        self._toast(f"Deleted {sid}")

    def _apply_props(self, silent: bool = False) -> None:
        if not self.selected_node:
            return
        sc = self.gamebook.scenes.get(self.selected_node)
        if not sc:
            return
        if self.title_input:
            sc.title = self.title_input.text.strip() or sc.title
        if self.body_input:
            sc.body = self.body_input.text
        if self.tags_input:
            raw = self.tags_input.text.strip()
            sc.tags = [t.strip() for t in raw.split(",") if t.strip()] if raw else []
        n = self.nodes.get(self.selected_node)
        if n:
            n.title = sc.title
        if not silent:
            self._toast("Properties applied.")

    # ── choice operations ────────────────────────────────────────
    def _add_choice(self) -> None:
        if not self.selected_node:
            return
        sc = self.gamebook.scenes[self.selected_node]
        sc.choices.append(Choice(text="New choice", target=""))
        n = self.nodes.get(self.selected_node)
        if n:
            n.choice_count = len(sc.choices)
        self.editing_choice = len(sc.choices) - 1
        self._open_choice_editor()

    def _delete_choice(self, idx: int) -> None:
        if not self.selected_node:
            return
        sc = self.gamebook.scenes[self.selected_node]
        if 0 <= idx < len(sc.choices):
            del sc.choices[idx]
            n = self.nodes.get(self.selected_node)
            if n:
                n.choice_count = len(sc.choices)
            self.editing_choice = -1
            self._rebuild_inspector()
            self._toast(f"Deleted choice {idx + 1}")

    def _move_choice(self, idx: int, delta: int) -> None:
        if not self.selected_node:
            return
        sc = self.gamebook.scenes[self.selected_node]
        j = idx + delta
        if 0 <= idx < len(sc.choices) and 0 <= j < len(sc.choices):
            sc.choices[idx], sc.choices[j] = sc.choices[j], sc.choices[idx]
            self._rebuild_inspector()

    def _edit_choice(self, idx: int) -> None:
        self.editing_choice = idx
        self._open_choice_editor()

    # ── choice editor (rich) ─────────────────────────────────────
    @staticmethod
    def _dict_to_lines(d: dict) -> str:
        if not isinstance(d, dict) or not d:
            return ""
        return "\n".join(f"{k}: {v}" for k, v in d.items())

    @staticmethod
    def _lines_to_dict(s: str) -> dict:
        out: dict = {}
        for raw in (s or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            sep = ":" if ":" in line else ("=" if "=" in line else None)
            if sep is None:
                out[line] = True
                continue
            k, _, v = line.partition(sep)
            k, v = k.strip(), v.strip()
            if not k:
                continue
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
        return out

    def _open_choice_editor(self) -> None:
        if not self.selected_node or self.editing_choice < 0:
            return
        sc = self.gamebook.scenes[self.selected_node]
        if self.editing_choice >= len(sc.choices):
            return
        ch = sc.choices[self.editing_choice]
        d = ch.to_dict() if isinstance(ch, Choice) else dict(ch)
        w, h = self.window.width, self.window.height
        self.PW_CHOICE, self.PH_CHOICE = 560, 470
        pw, ph = self.PW_CHOICE, self.PH_CHOICE
        cx, cy = w // 2, h // 2
        left = cx - pw // 2 + 18
        fullw = pw - 36
        halfw = (fullw - 12) / 2

        cur = cy + ph // 2 - 36
        # text (multiline)
        t_h = 50
        ty = cur - 13 - t_h
        text_in = TextInput(left, ty, fullw, t_h, d.get("text", ""),
                            multiline=True, placeholder="Choice text", font_size=10)
        cur = ty - 8
        # target / fail target
        r_h = 24
        ry = cur - 13 - r_h
        target_in = TextInput(left, ry, halfw, r_h, d.get("target", ""),
                              placeholder="target scene id", font_size=10)
        fail_in = TextInput(left + halfw + 12, ry, halfw, r_h,
                            d.get("fail_target", ""),
                            placeholder="fail target (optional)", font_size=10)
        cur = ry - 8
        # roll / tags
        r2y = cur - 13 - r_h
        roll_in = TextInput(left, r2y, halfw, r_h, d.get("roll", ""),
                            placeholder="roll e.g. valor:14", font_size=10)
        tags_in = TextInput(left + halfw + 12, r2y, halfw, r_h,
                            ", ".join(d.get("tags", []) or []),
                            placeholder="tags, comma", font_size=10)
        cur = r2y - 8
        # conditions (multiline)
        c_h = 46
        cyy = cur - 13 - c_h
        cond_in = TextInput(left, cyy, fullw, c_h,
                            self._dict_to_lines(d.get("conditions", {})),
                            multiline=True,
                            placeholder="conditions — one 'key: value' per line",
                            font_size=9)
        cur = cyy - 8
        # effects (multiline)
        e_h = 46
        eyy = cur - 13 - e_h
        eff_in = TextInput(left, eyy, fullw, e_h,
                           self._dict_to_lines(d.get("effects", {})),
                           multiline=True,
                           placeholder="effects — one 'key: value' per line",
                           font_size=9)

        self._choice_field_map = {
            "text": text_in, "target": target_in, "fail_target": fail_in,
            "roll": roll_in, "tags": tags_in, "conditions": cond_in,
            "effects": eff_in,
        }
        self._choice_captions = {
            id(text_in): "Choice text", id(target_in): "Target scene id",
            id(fail_in): "Fail target (roll fail)", id(roll_in): "Roll (stat:DC)",
            id(tags_in): "Tags", id(cond_in): "Conditions",
            id(eff_in): "Effects",
        }
        self.choice_inputs = [text_in, target_in, fail_in, roll_in,
                              tags_in, cond_in, eff_in]
        # legacy aliases (kept for any external reference)
        self.choice_text_input = text_in
        self.choice_target_input = target_in

    def _close_choice_editor(self, save: bool) -> None:
        if save and self.selected_node and self.editing_choice >= 0:
            sc = self.gamebook.scenes[self.selected_node]
            if self.editing_choice < len(sc.choices):
                ch = sc.choices[self.editing_choice]
                if isinstance(ch, Choice):
                    m = getattr(self, "_choice_field_map", {})
                    if "text" in m:
                        ch.text = m["text"].text.strip()
                        ch.target = m["target"].text.strip()
                        ch.fail_target = m["fail_target"].text.strip()
                        ch.roll = m["roll"].text.strip()
                        ch.tags = [t.strip() for t in m["tags"].text.split(",")
                                   if t.strip()]
                        ch.conditions = self._lines_to_dict(m["conditions"].text)
                        ch.effects = self._lines_to_dict(m["effects"].text)
                n = self.nodes.get(self.selected_node)
                if n:
                    n.choice_count = len(sc.choices)
        self.editing_choice = -1
        self.choice_inputs = []
        self.choice_text_input = None
        self.choice_target_input = None
        self._choice_field_map = {}
        self._rebuild_inspector()

    # ── confirmation dialog ──────────────────────────────────────
    def _confirm(self, text: str, action) -> None:
        self.confirm_text = text
        self.confirm_action = action

    def _confirm_yes(self) -> None:
        action = self.confirm_action
        self.confirm_text = ""
        self.confirm_action = None
        if action:
            action()

    def _confirm_no(self) -> None:
        self.confirm_text = ""
        self.confirm_action = None

    # ── notice / toast ───────────────────────────────────────────
    def _toast(self, msg: str) -> None:
        self.notice = msg
        self.notice_timer = 2.5

    # ── arcade lifecycle ─────────────────────────────────────────
    def on_show_view(self) -> None:
        self._rebuild_toolbar()
        self._fit()
        self._rebuild_inspector()

    def on_resize(self, w, h):
        self.camera.match_window()
        self.ui_camera.match_window()
        self._rebuild_toolbar()
        self._rebuild_inspector()

    def on_update(self, dt: float) -> None:
        if self.notice_timer > 0:
            self.notice_timer -= dt
            if self.notice_timer <= 0:
                self.notice = ""
        for ti in (self.title_input, self.body_input, self.tags_input):
            if ti:
                ti.update(dt)
        for ti in self.choice_inputs:
            ti.update(dt)

    def _s2w(self, sx, sy):
        w, h = self.window.width, self.window.height
        return ((sx - w / 2) / self.zoom + self._cam_pos[0],
                (sy - h / 2) / self.zoom + self._cam_pos[1])

    # ── draw ─────────────────────────────────────────────────────
    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        sw = max(280, int(w * 0.30))

        # graph (world camera)
        self.camera.position = self._cam_pos
        self.camera.use()
        # connection edges
        for sid, sc in self.gamebook.scenes.items():
            if sid not in self.nodes:
                continue
            src = self.nodes[sid]
            for ch in sc.choices:
                d = ch.to_dict() if isinstance(ch, Choice) else dict(ch)
                for tgt_key, edge_color in (
                        ("target", (110, 130, 90, 200)),
                        ("fail_target", (140, 80, 70, 180)),
                ):
                    tid = d.get(tgt_key, "")
                    if not tid or tid not in self.nodes:
                        continue
                    dst = self.nodes[tid]
                    s2, s3 = src.get_output_port()
                    ex, ey = dst.get_input_port()
                    mx = (s2 + ex) / 2
                    lc = (200, 190, 110, 230) if self.selected_node == sid else edge_color
                    arcade.draw_line(s2, s3, mx, s3, lc, 1.4)
                    arcade.draw_line(mx, s3, mx, ey, lc, 1.4)
                    arcade.draw_line(mx, ey, ex, ey, lc, 1.4)
                    arcade.draw_triangle_filled(ex, ey, ex - 8, ey + 5,
                                                ex - 8, ey - 5, lc[:3])
        for n in self.nodes.values():
            n.selected = (n.scene_id == self.selected_node)
            n.draw()

        # UI overlay
        self.ui_camera.use()
        # top toolbar bar
        arcade.draw_rect_filled(XYWH(w // 2, h - 20, w, 40), color=(26, 26, 34))
        arcade.draw_line(0, h - 40, w, h - 40, (52, 52, 64), 1)
        for b in self.toolbar_buttons:
            b.draw()
        arcade.draw_text(
            f"STUDIO ▸ {self.gamebook.title}",
            (w - sw) // 2, h - 20, (160, 160, 175),
            font_size=11, anchor_x="center", anchor_y="center", bold=True)

        # right inspector panel
        arcade.draw_rect_filled(XYWH(w - sw // 2, h // 2, sw, h),
                                color=(22, 22, 30))
        arcade.draw_line(w - sw, 0, w - sw, h, (44, 44, 56), 1)
        arcade.draw_text("INSPECTOR", w - sw // 2, h - 56,
                         (180, 165, 120), font_size=11,
                         anchor_x="center", anchor_y="center", bold=True)

        if self.selected_node and self.selected_node in self.gamebook.scenes:
            self._draw_inspector(w, h, sw)
        else:
            arcade.draw_text("Click a node to edit",
                             w - sw // 2, h // 2,
                             (95, 95, 110), font_size=10,
                             anchor_x="center", anchor_y="center")

        # status bar
        arcade.draw_rect_filled(XYWH(w // 2, 14, w, 28), color=(20, 20, 28))
        arcade.draw_text(
            f"{len(self.gamebook.scenes)} scenes  •  "
            f"{len(self.gamebook.items)} items  •  "
            f"{len(self.gamebook.stat_names)} stats  •  "
            f"zoom {self.zoom:.2f}×",
            (w - sw) // 2, 14, (110, 110, 122), font_size=9,
            anchor_x="center", anchor_y="center")

        # toast
        if self.notice and self.notice_timer > 0:
            alpha = min(255, int(self.notice_timer * 220))
            arcade.draw_rect_filled(XYWH((w - sw) // 2, 50, 320, 30),
                                    color=(28, 36, 46, alpha))
            arcade.draw_text(self.notice, (w - sw) // 2, 50,
                             (220, 220, 200, alpha), font_size=10,
                             anchor_x="center", anchor_y="center")

        # validation report overlay
        if self.show_validation and self.validation_report:
            self._draw_validation(w, h)

        # choice editor overlay
        if self.editing_choice >= 0 and self.choice_text_input:
            self._draw_choice_editor(w, h)

        # confirm dialog
        if self.confirm_text:
            self._draw_confirm(w, h)

        # help
        if self.show_help:
            self._draw_help(w, h)

    def _draw_inspector(self, w: int, h: int, sw: int) -> None:
        sc = self.gamebook.scenes[self.selected_node]
        x0 = w - sw + 12

        # ID + start marker
        is_start = (sc.id == self.gamebook.start_scene)
        id_label = f"ID: {sc.id}"
        if is_start:
            id_label += "   ★ START"
        arcade.draw_text(id_label, x0, h - 70, (135, 135, 145),
                         font_size=8, anchor_y="center")

        def caption(ti, label):
            if ti:
                arcade.draw_text(label, x0, ti.top + 3, (130, 130, 145),
                                 font_size=8, anchor_x="left", anchor_y="bottom")
                ti.draw()

        caption(self.title_input, "Title")
        caption(self.body_input, "Body")
        caption(self.tags_input, "Tags")

        # choices header (position set by _rebuild_inspector)
        ch_y = getattr(self, "_choices_header_y", h - 280)
        arcade.draw_text(f"Choices ({len(sc.choices)})",
                         x0, ch_y, (170, 160, 120), font_size=10,
                         anchor_y="center", bold=True)

        for b in self.choice_buttons:
            b.draw()
        for b in self.inspector_buttons:
            b.draw()

        if getattr(self, "_choice_overflow", 0) > 0:
            arcade.draw_text(
                f"+{self._choice_overflow} more — enlarge window to edit",
                x0, 90, (150, 140, 120), font_size=8,
                anchor_x="left", anchor_y="center")

    def _draw_validation(self, w: int, h: int) -> None:
        rep = self.validation_report or {}
        pw, ph = 540, 380
        cx, cy = w // 2, h // 2
        arcade.draw_rect_filled(XYWH(cx, cy, pw, ph), color=(20, 20, 28, 245))
        arcade.draw_rect_outline(XYWH(cx, cy, pw, ph),
                                 color=(110, 110, 130), border_width=2)
        arcade.draw_text("VALIDATION REPORT",
                         cx, cy + ph // 2 - 22, (220, 200, 140),
                         font_size=14, anchor_x="center", anchor_y="center",
                         bold=True)
        ok = (not rep.get("broken_targets") and not rep.get("dead_ends")
              and not rep.get("orphans") and not rep.get("missing_items"))
        summary = (f"{rep.get('reached',0)}/{rep.get('total',0)} scenes "
                   f"reachable from start")
        arcade.draw_text(summary, cx, cy + ph // 2 - 44,
                         (180, 200, 180) if ok else (210, 180, 140),
                         font_size=10, anchor_x="center", anchor_y="center")
        y = cy + ph // 2 - 76
        lx = cx - pw // 2 + 22

        def line(label: str, items: list, color=(220, 130, 130)) -> int:
            nonlocal y
            arcade.draw_text(f"{label} ({len(items)})", lx, y,
                             color if items else (110, 140, 110),
                             font_size=10, bold=True)
            y -= 14
            for it in items[:5]:
                arcade.draw_text(f"   • {it}", lx, y,
                                 (180, 180, 190), font_size=8)
                y -= 11
            if len(items) > 5:
                arcade.draw_text(f"   …and {len(items) - 5} more",
                                 lx, y, (130, 130, 145), font_size=8)
                y -= 11
            y -= 6
            return y

        line("Broken targets",
             [f"{sid} #{i+1} → {t}"
              for sid, i, t in rep.get("broken_targets", [])])
        line("Dead ends", rep.get("dead_ends", []))
        line("Orphans (unreachable)", rep.get("orphans", []))
        line("Missing items",
             [f"{sid} {k}={v}" for sid, k, v in rep.get("missing_items", [])])

        if ok:
            arcade.draw_text("All checks passed. ✓",
                             cx, cy - ph // 2 + 50, (140, 200, 140),
                             font_size=12, anchor_x="center", anchor_y="center",
                             bold=True)
        arcade.draw_text("Click anywhere to close",
                         cx, cy - ph // 2 + 22, (130, 130, 145),
                         font_size=9, anchor_x="center", anchor_y="center")

    def _draw_choice_editor(self, w: int, h: int) -> None:
        pw = getattr(self, "PW_CHOICE", 560)
        ph = getattr(self, "PH_CHOICE", 470)
        cx, cy = w // 2, h // 2
        arcade.draw_rect_filled(XYWH(cx, cy, pw, ph), color=(24, 24, 32, 248))
        arcade.draw_rect_outline(XYWH(cx, cy, pw, ph),
                                 color=(110, 110, 130), border_width=2)
        arcade.draw_text(f"EDIT CHOICE #{self.editing_choice + 1}",
                         cx, cy + ph // 2 - 18, (220, 200, 140),
                         font_size=12, anchor_x="center", anchor_y="center",
                         bold=True)
        caps = getattr(self, "_choice_captions", {})
        for ti in self.choice_inputs:
            label = caps.get(id(ti), "")
            if label:
                arcade.draw_text(label, ti.left, ti.top + 3,
                                 (135, 135, 148), font_size=8,
                                 anchor_x="left", anchor_y="bottom")
            ti.draw()
        # OK / Cancel
        by = cy - ph // 2 + 26
        arcade.draw_rect_filled(XYWH(cx + 90, by, 90, 28), color=(46, 86, 56))
        arcade.draw_text("Save", cx + 90, by, (224, 234, 224),
                         font_size=11, anchor_x="center", anchor_y="center",
                         bold=True)
        arcade.draw_rect_filled(XYWH(cx - 10, by, 90, 28), color=(86, 56, 56))
        arcade.draw_text("Cancel", cx - 10, by, (224, 224, 224),
                         font_size=11, anchor_x="center", anchor_y="center",
                         bold=True)

    def _choice_editor_button_at(self, x: int, y: int) -> str | None:
        w, h = self.window.width, self.window.height
        cx, cy = w // 2, h // 2
        ph = getattr(self, "PH_CHOICE", 470)
        by = cy - ph // 2 + 26
        if abs(y - by) > 14:
            return None
        if abs(x - (cx + 90)) <= 45:
            return "ok"
        if abs(x - (cx - 10)) <= 45:
            return "cancel"
        return None

    def _draw_confirm(self, w: int, h: int) -> None:
        pw, ph = 380, 150
        cx, cy = w // 2, h // 2
        arcade.draw_rect_filled(XYWH(cx, cy, pw, ph), color=(24, 24, 32, 248))
        arcade.draw_rect_outline(XYWH(cx, cy, pw, ph),
                                 color=(180, 110, 110), border_width=2)
        arcade.draw_text("CONFIRM", cx, cy + 50, (220, 180, 160),
                         font_size=12, anchor_x="center", anchor_y="center",
                         bold=True)
        arcade.draw_text(self.confirm_text, cx, cy + 16,
                         (210, 210, 220), font_size=10,
                         anchor_x="center", anchor_y="center",
                         width=pw - 30, multiline=True)
        arcade.draw_rect_filled(XYWH(cx - 70, cy - 36, 100, 30),
                                color=(112, 52, 52))
        arcade.draw_text("Yes", cx - 70, cy - 36, (240, 230, 230),
                         font_size=11, anchor_x="center",
                         anchor_y="center", bold=True)
        arcade.draw_rect_filled(XYWH(cx + 70, cy - 36, 100, 30),
                                color=(54, 70, 92))
        arcade.draw_text("Cancel", cx + 70, cy - 36, (230, 230, 240),
                         font_size=11, anchor_x="center",
                         anchor_y="center", bold=True)

    def _confirm_button_at(self, x: int, y: int) -> str | None:
        w, h = self.window.width, self.window.height
        cx, cy = w // 2, h // 2
        if abs(y - (cy - 36)) > 15:
            return None
        if abs(x - (cx - 70)) <= 50:
            return "yes"
        if abs(x - (cx + 70)) <= 50:
            return "no"
        return None

    def _draw_help(self, w: int, h: int) -> None:
        pw, ph = 470, 360
        cx, cy = w // 2, h // 2
        arcade.draw_rect_filled(XYWH(cx, cy, pw, ph), color=(18, 18, 28, 245))
        arcade.draw_rect_outline(XYWH(cx, cy, pw, ph),
                                 color=(85, 85, 105), border_width=2)
        lines = [
            ("STUDIO HELP", True),
            ("", False),
            ("Left-click node      Select / drag", False),
            ("Middle-drag          Pan camera", False),
            ("Scroll wheel         Zoom", False),
            ("+ / =                New scene at cursor", False),
            ("Ctrl+D               Duplicate selected scene", False),
            ("- / Delete           Delete selected scene", False),
            ("V                    Validate (broken links)", False),
            ("Apply                Save inspector edits", False),
            ("Set Start            Make scene the start", False),
            ("Click a choice       Edit text/target/roll/cond/fx", False),
            ("S                    Save to project.json", False),
            ("H                    Toggle this panel", False),
            ("F                    Fullscreen   ·   E / ESC  Menu", False),
        ]
        for i, (ln, hdr) in enumerate(lines):
            color = (220, 200, 140) if hdr else (180, 180, 190)
            size = 13 if hdr else 10
            arcade.draw_text(ln, cx - pw // 2 + 24, cy + ph // 2 - 24 - i * 18,
                             color, font_size=size,
                             anchor_x="left", anchor_y="center", bold=hdr)

    # ── input ────────────────────────────────────────────────────
    def on_key_press(self, key, mods):
        # focused text input gets all printable input
        focused = self._focused_input()
        if focused is not None:
            focused.on_key_press(key, mods)
            return
        if self.editing_choice >= 0:
            if key == arcade.key.ESCAPE:
                self._close_choice_editor(save=False)
            elif key == arcade.key.ENTER and not (mods & arcade.key.MOD_SHIFT):
                self._close_choice_editor(save=True)
            return
        if self.show_validation:
            if key == arcade.key.ESCAPE:
                self.show_validation = False
            return
        if self.confirm_text:
            if key == arcade.key.ESCAPE:
                self._confirm_no()
            elif key == arcade.key.ENTER:
                self._confirm_yes()
            return
        if km(key, "exit") or km(key, "editor_toggle"):
            self.window.show_view(MainMenuView())
        elif km(key, "fullscreen"):
            self.window.set_fullscreen(not self.window.fullscreen)
            self.camera.match_window()
            self.ui_camera.match_window()
            self._rebuild_toolbar()
            self._rebuild_inspector()
        elif km(key, "help"):
            self.show_help = not self.show_help
        elif km(key, "save"):
            self._save()
            return
        # ── editor shortcuts (no input focused, no overlay) ──────────
        K = arcade.key
        ctrl = bool(mods & K.MOD_CTRL)
        add_keys = {getattr(K, n, -999) for n in ("PLUS", "EQUAL", "NUM_ADD")}
        del_keys = {getattr(K, n, -999) for n in
                    ("MINUS", "NUM_SUBTRACT", "DELETE")}
        if key == K.V:
            self._validate()
        elif ctrl and key == K.D:
            self._duplicate_scene()
        elif ctrl and key == K.N:
            self._add_scene()
        elif key in add_keys:
            self._add_scene()
        elif key in del_keys:
            if self.selected_node and self.selected_node in self.gamebook.scenes:
                sc = self.gamebook.scenes[self.selected_node]
                self._confirm(f"Delete scene '{sc.id}'?", self._delete_scene)

    def on_text(self, text: str) -> None:
        focused = self._focused_input()
        if focused is not None:
            focused.on_text(text)

    def _focused_input(self) -> TextInput | None:
        for ti in self._all_inputs():
            if ti is not None and ti.focused:
                return ti
        return None

    def _all_inputs(self) -> list:
        base = [self.title_input, self.body_input, self.tags_input]
        return [ti for ti in base if ti is not None] + list(self.choice_inputs)

    def on_mouse_press(self, x, y, btn, mods):
        # confirm dialog absorbs all clicks first
        if self.confirm_text:
            r = self._confirm_button_at(x, y)
            if r == "yes":
                self._confirm_yes()
            elif r == "no":
                self._confirm_no()
            return
        # validation overlay absorbs all clicks
        if self.show_validation:
            self.show_validation = False
            return
        # choice editor
        if self.editing_choice >= 0:
            r = self._choice_editor_button_at(x, y)
            if r == "ok":
                self._close_choice_editor(save=True)
                return
            if r == "cancel":
                self._close_choice_editor(save=False)
                return
            for ti in self.choice_inputs:
                ti.on_mouse_press(x, y, btn)
            return

        w = self.window.width
        sw = max(280, int(w * 0.30))

        # toolbar
        for b in self.toolbar_buttons:
            if b.on_mouse_press(x, y, btn):
                return

        # inspector area: text inputs + buttons
        if x > w - sw:
            for ti in self._all_inputs():
                ti.on_mouse_press(x, y, btn)
            for b in self.choice_buttons:
                if b.on_mouse_press(x, y, btn):
                    return
            for b in self.inspector_buttons:
                if b.on_mouse_press(x, y, btn):
                    return
            return

        # graph area: lose focus on any text input
        for ti in self._all_inputs():
            ti.focused = False

        if btn == arcade.MOUSE_BUTTON_MIDDLE:
            self.panning = True
            return
        if btn == arcade.MOUSE_BUTTON_LEFT:
            wx, wy = self._s2w(x, y)
            clicked = None
            # iterate top-down (last drawn = topmost)
            for n in reversed(list(self.nodes.values())):
                if n.contains(wx, wy):
                    clicked = n.scene_id
                    n.dragging = True
                    break
            if clicked != self.selected_node:
                # persist any pending edits before switching away
                if self.selected_node:
                    self._apply_props(silent=True)
                self.selected_node = clicked
                self._rebuild_inspector()

    def on_mouse_release(self, x, y, btn, mods):
        if btn == arcade.MOUSE_BUTTON_MIDDLE:
            self.panning = False
        if btn == arcade.MOUSE_BUTTON_LEFT:
            for n in self.nodes.values():
                if n.dragging:
                    n.dragging = False
                    sc = self.gamebook.scenes.get(n.scene_id)
                    if sc:
                        sc.position = (n.x, n.y)
            for ti in self._all_inputs():
                ti.on_mouse_release(x, y, btn)

    def on_mouse_drag(self, x, y, dx, dy, buttons, mods):
        if self.panning:
            cx, cy = self._cam_pos
            self._cam_pos = (cx - dx / self.zoom, cy - dy / self.zoom)
            return
        if buttons & arcade.MOUSE_BUTTON_LEFT:
            for n in self.nodes.values():
                if n.dragging:
                    n.x += dx / self.zoom
                    n.y += dy / self.zoom
                    return

    def on_mouse_motion(self, x, y, dx, dy):
        for b in self.toolbar_buttons:
            b.on_mouse_motion(x, y)
        for b in self.choice_buttons:
            b.on_mouse_motion(x, y)
        for b in self.inspector_buttons:
            b.on_mouse_motion(x, y)

    def on_mouse_scroll(self, x, y, sx, sy):
        # Scroll within an inspector text input scrolls that input instead of zooming.
        w = self.window.width
        sw = max(280, int(w * 0.30))
        if x > w - sw:
            for ti in self._all_inputs():
                if hasattr(ti, "on_mouse_scroll"):
                    ti.on_mouse_scroll(x, y, sx, sy)
            return
        self.zoom *= (1.1 if sy > 0 else 0.9)
        self.zoom = max(0.2, min(3.0, self.zoom))


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════
def get_screen_size():
    """Return primary monitor size (best effort)."""
    try:
        import pyglet
        d = pyglet.display.get_display()
        s = d.get_screens()
        if s:
            return s[0].width, s[0].height
    except Exception:
        pass
    try:
        return arcade.get_display_size()
    except Exception:
        pass
    return 1920, 1080


def main():
    global VERBOSE
    p = argparse.ArgumentParser(description="Gamebook Studio")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Print extra diagnostic output.")
    p.add_argument("--book", help="Open a book directly (folder name in library/).")
    p.add_argument("--no-textures", action="store_true",
                   help="Skip placeholder texture generation at startup.")
    args = p.parse_args()
    VERBOSE = args.verbose

    # Generate placeholder textures unless suppressed.
    if not args.no_textures:
        try:
            from texture_gen import generate_all_placeholders
            lib = cfg("paths", "library", "./library")
            if os.path.exists(lib):
                for entry in sorted(os.listdir(lib)):
                    bp = os.path.join(lib, entry)
                    if os.path.isdir(bp) and os.path.exists(
                            os.path.join(bp, "project.json")):
                        try:
                            gb = GameBook.load(bp)
                            vlog(f"Textures: {entry}")
                            generate_all_placeholders(gb, bp, CONFIG)
                        except Exception as ex:
                            vlog(f"  texture-gen skipped for {entry}: {ex}")
        except Exception as e:
            vlog(f"Texture generation skipped: {e}")

    cw = CONFIG.get("window", {})
    sw, sh = get_screen_size()
    vlog(f"Screen: {sw}×{sh}")
    if cw.get("autodetect_size", True):
        w = max(1024, min(int(sw * 0.82), sw - 40))
        h = max(600, min(int(sh * 0.82), sh - 80))
    else:
        w, h = cw.get("width", 1280), cw.get("height", 800)
    vlog(f"Window: {w}×{h}")

    window = arcade.Window(
        w, h, cw.get("title", "Gamebook Studio"),
        resizable=True, vsync=cw.get("vsync", True))
    try:
        window.set_minimum_size(cw.get("min_width", 1024),
                                cw.get("min_height", 600))
    except AttributeError:
        pass

    # Direct-open?
    start_view = MainMenuView()
    if args.book:
        bp = os.path.join(cfg("paths", "library", "./library"), args.book)
        if os.path.isdir(bp):
            try:
                gb = GameBook.load(bp)
                start_view = PlayerView(gb)
            except Exception as e:
                print(f"Failed to load --book {args.book}: {e}")
    window.show_view(start_view)
    arcade.run()


if __name__ == "__main__":
    main()
