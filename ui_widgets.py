"""
ui_widgets.py — Reusable UI primitives for Gamebook Studio.

Designed for Arcade 3.x. All widgets expose:
    * ``draw()``                       — pure render (call inside on_draw)
    * ``on_mouse_motion(x, y)``        — hover state
    * ``on_mouse_press(x, y, button)`` — click handling, returns True if consumed

Primitives provided:
    Button, IconButton, ToggleButton, Slider, TextInput,
    TypewriterTextArea, StatBar, InventorySlot, Tooltip,
    MessageLog, NodeWidget, DiceRoller, Panel, TabBar
"""
from __future__ import annotations

import math
import time
import textwrap

import arcade
from arcade import XYWH, LBWH


# ─── colour helpers ─────────────────────────────────────────────
def _lighten(c, k=40):
    return tuple(min(255, int(v) + k) for v in c[:3]) + (c[3:] or ())

def _darken(c, k=20):
    return tuple(max(0, int(v) - k) for v in c[:3]) + (c[3:] or ())

def _with_alpha(c, a):
    return (int(c[0]), int(c[1]), int(c[2]), int(a))


# ─── Button ─────────────────────────────────────────────────────
class Button:
    """Rectangular pushbutton.

    The button draws its own subtle border + 1-px highlight at top to suggest
    a bevel, and dims when ``enabled`` is False.
    """

    def __init__(self, cx, cy, w, h, text,
                 color=(60, 80, 120), hover_color=(80, 110, 160),
                 text_color=(230, 230, 230), font_size=14,
                 callback=None, enabled=True, align="center", icon_text="",
                 subtitle=""):
        self.cx, self.cy, self.w, self.h = cx, cy, w, h
        self.text = text
        self.color = color
        self.hover_color = hover_color
        self.text_color = text_color
        self.font_size = font_size
        self.callback = callback
        self.hovered = False
        self.enabled = enabled
        self.align = align
        self.icon_text = icon_text
        self.subtitle = subtitle

    def contains(self, x, y):
        return abs(x - self.cx) <= self.w / 2 and abs(y - self.cy) <= self.h / 2

    def draw(self):
        if not self.enabled:
            bg, tc = (52, 52, 58), (110, 110, 115)
        elif self.hovered:
            bg, tc = self.hover_color, self.text_color
        else:
            bg, tc = self.color, self.text_color
        arcade.draw_rect_filled(XYWH(self.cx, self.cy, self.w, self.h), color=bg)
        # Top highlight (1px) and bottom shade for bevel
        arcade.draw_line(self.cx - self.w / 2 + 1, self.cy + self.h / 2 - 0.5,
                         self.cx + self.w / 2 - 1, self.cy + self.h / 2 - 0.5,
                         _lighten(bg, 30), 1)
        arcade.draw_rect_outline(XYWH(self.cx, self.cy, self.w, self.h),
                                 color=_with_alpha(tc, 70), border_width=1)
        if self.align == "center":
            tx = self.cx
            anchor_x = "center"
        else:  # left
            tx = self.cx - self.w / 2 + 12
            anchor_x = "left"
        arcade.draw_text(self.text, tx, self.cy, tc, font_size=self.font_size,
                         anchor_x=anchor_x, anchor_y="center")
        if self.subtitle:
            arcade.draw_text(self.subtitle, tx, self.cy - self.font_size - 2,
                             _with_alpha(tc, 150), font_size=max(8, self.font_size - 4),
                             anchor_x=anchor_x, anchor_y="center")

    def on_mouse_motion(self, x, y):
        self.hovered = self.contains(x, y) and self.enabled

    def on_mouse_press(self, x, y, button):
        if (self.contains(x, y) and self.enabled
                and button == arcade.MOUSE_BUTTON_LEFT):
            if self.callback:
                self.callback()
            return True
        return False


# ─── IconButton (square) ────────────────────────────────────────
class IconButton(Button):
    """Compact square button with single-character glyph."""
    def __init__(self, cx, cy, size, glyph, **kw):
        super().__init__(cx, cy, size, size, glyph, **kw)
        self.font_size = kw.get("font_size", int(size * 0.55))


# ─── ToggleButton ───────────────────────────────────────────────
class ToggleButton(Button):
    """A button that flips ``self.value`` on click and shows it visually."""
    def __init__(self, *a, value=False, **kw):
        super().__init__(*a, **kw)
        self.value = value
        self._cb = self.callback
        self.callback = self._toggle

    def _toggle(self):
        self.value = not self.value
        if self._cb:
            self._cb(self.value)

    def draw(self):
        if self.value:
            self.color, _orig = (60, 110, 70), self.color
            super().draw()
            self.color = _orig
        else:
            super().draw()


# ─── Slider ─────────────────────────────────────────────────────
class Slider:
    """Horizontal slider with label, drag handle, and value readout."""

    def __init__(self, left, cy, width, height, label, value, vmin=0, vmax=100,
                 step=1, on_change=None,
                 track_color=(50, 50, 60), fill_color=(80, 130, 200),
                 handle_color=(220, 220, 230)):
        self.left, self.cy = left, cy
        self.width, self.height = width, height
        self.label = label
        self.value = value
        self.vmin, self.vmax = vmin, vmax
        self.step = step
        self.on_change = on_change
        self.track_color = track_color
        self.fill_color = fill_color
        self.handle_color = handle_color
        self.dragging = False

    def _ratio(self):
        rng = max(1e-6, self.vmax - self.vmin)
        return max(0.0, min(1.0, (self.value - self.vmin) / rng))

    def _value_from_x(self, x):
        r = max(0.0, min(1.0, (x - self.left) / max(1, self.width)))
        v = self.vmin + r * (self.vmax - self.vmin)
        if self.step:
            v = round(v / self.step) * self.step
        return max(self.vmin, min(self.vmax, v))

    def contains(self, x, y):
        return (self.left <= x <= self.left + self.width
                and abs(y - self.cy) <= self.height)

    def draw(self):
        # label
        arcade.draw_text(self.label, self.left, self.cy + self.height + 2,
                         (190, 190, 200), font_size=10,
                         anchor_x="left", anchor_y="bottom")
        # readout
        readout = f"{self.value:.2f}" if isinstance(self.value, float) else f"{self.value}"
        arcade.draw_text(readout, self.left + self.width, self.cy + self.height + 2,
                         (210, 200, 140), font_size=10,
                         anchor_x="right", anchor_y="bottom")
        # track
        cx = self.left + self.width / 2
        arcade.draw_rect_filled(XYWH(cx, self.cy, self.width, 4),
                                color=self.track_color)
        # fill
        fw = self._ratio() * self.width
        if fw > 0:
            arcade.draw_rect_filled(XYWH(self.left + fw / 2, self.cy, fw, 4),
                                    color=self.fill_color)
        # handle
        hx = self.left + fw
        arcade.draw_circle_filled(hx, self.cy, 7, self.handle_color)
        arcade.draw_circle_outline(hx, self.cy, 7, (40, 40, 50), 1)

    def on_mouse_press(self, x, y, button):
        if self.contains(x, y) and button == arcade.MOUSE_BUTTON_LEFT:
            self.dragging = True
            new = self._value_from_x(x)
            if new != self.value:
                self.value = new
                if self.on_change:
                    self.on_change(self.value)
            return True
        return False

    def on_mouse_release(self, x, y, button):
        if self.dragging and button == arcade.MOUSE_BUTTON_LEFT:
            self.dragging = False

    def on_mouse_drag(self, x, y, dx, dy, buttons, mods):
        if self.dragging:
            new = self._value_from_x(x)
            if new != self.value:
                self.value = new
                if self.on_change:
                    self.on_change(self.value)

    def on_mouse_motion(self, x, y):
        pass


# ─── TextInput (single- or multi-line) ──────────────────────────
class TextInput:
    """Editable text field used by the Studio inspector and choice editor.

    Geometry is **bottom-anchored**: ``(left, y)`` is the bottom-left corner,
    so ``ti.top`` ( == ``y + height`` ) is a convenient anchor for a caption
    drawn just above the box.

    Editing supports an insertion cursor (LEFT/RIGHT/HOME/END), BACKSPACE,
    DELETE, and — for multiline fields — ENTER to insert a newline.
    """

    def __init__(self, left, y, width, height, value="", on_change=None,
                 font_size=12, multiline=False, placeholder=""):
        self.left = left
        self.y = y                       # bottom edge
        self.width, self.height = width, height
        self.value = value or ""
        self.on_change = on_change
        self.font_size = font_size
        self.multiline = multiline
        self.placeholder = placeholder
        self.focused = False
        self.cursor = len(self.value)    # insertion index
        self._blink = 0.0

    # backward-compatible centre accessor
    @property
    def cy(self):
        return self.y + self.height / 2

    @property
    def top(self):
        return self.y + self.height

    # callers (Studio inspector / choice editor) read+write ``.text``
    @property
    def text(self):
        return self.value

    @text.setter
    def text(self, v):
        self.value = v or ""
        self.cursor = min(self.cursor, len(self.value))

    def contains(self, x, y):
        return (self.left <= x <= self.left + self.width
                and self.y <= y <= self.y + self.height)

    def update(self, dt):
        self._blink = (self._blink + dt) % 1.0

    def _emit(self):
        if self.on_change:
            self.on_change(self.value)

    # ── rendering ───────────────────────────────────────────────
    def draw(self):
        cx = self.left + self.width / 2
        cy = self.cy
        bg = (32, 32, 42) if self.focused else (24, 24, 30)
        arcade.draw_rect_filled(XYWH(cx, cy, self.width, self.height), color=bg)
        bc = (170, 150, 90) if self.focused else (60, 60, 72)
        arcade.draw_rect_outline(XYWH(cx, cy, self.width, self.height),
                                 color=bc, border_width=1)

        show = self.value
        is_placeholder = (not show and not self.focused and self.placeholder)
        if is_placeholder:
            show = self.placeholder
        color = (110, 110, 120) if is_placeholder else (222, 222, 228)

        if self.multiline:
            arcade.draw_text(show or " ", self.left + 6, self.y + self.height - 6,
                             color, font_size=self.font_size,
                             anchor_x="left", anchor_y="top",
                             multiline=True, width=int(self.width - 12))
        else:
            arcade.draw_text(show, self.left + 6, cy, color,
                             font_size=self.font_size,
                             anchor_x="left", anchor_y="center")

        if self.focused and self._blink < 0.5:
            before = self.value[: self.cursor]
            if self.multiline:
                last_line = before.split("\n")[-1]
                line_no = before.count("\n")
                cw = len(last_line) * self.font_size * 0.55
                cyy = self.y + self.height - 6 - line_no * (self.font_size + 4)
                arcade.draw_line(self.left + 6 + cw, cyy,
                                 self.left + 6 + cw, cyy - self.font_size,
                                 (222, 222, 228), 1)
            else:
                cw = len(before) * self.font_size * 0.55
                arcade.draw_line(self.left + 6 + cw, self.y + 4,
                                 self.left + 6 + cw, self.y + self.height - 4,
                                 (222, 222, 228), 1)

    # ── mouse ───────────────────────────────────────────────────
    def on_mouse_press(self, x, y, button):
        if self.contains(x, y) and button == arcade.MOUSE_BUTTON_LEFT:
            self.focused = True
            self.cursor = len(self.value)
            return True
        self.focused = False
        return False

    def on_mouse_release(self, x, y, button):
        return False

    def on_mouse_scroll(self, x, y, sx, sy):
        return False

    # ── keyboard ────────────────────────────────────────────────
    def on_key_press(self, key, mods):
        if not self.focused:
            return False
        c = self.cursor
        if key == arcade.key.BACKSPACE:
            if c > 0:
                self.value = self.value[:c - 1] + self.value[c:]
                self.cursor = c - 1
        elif key == arcade.key.DELETE:
            if c < len(self.value):
                self.value = self.value[:c] + self.value[c + 1:]
        elif key == arcade.key.LEFT:
            self.cursor = max(0, c - 1)
            return True
        elif key == arcade.key.RIGHT:
            self.cursor = min(len(self.value), c + 1)
            return True
        elif key == arcade.key.HOME:
            self.cursor = 0
            return True
        elif key == arcade.key.END:
            self.cursor = len(self.value)
            return True
        elif key == arcade.key.ENTER:
            if self.multiline:
                self.value = self.value[:c] + "\n" + self.value[c:]
                self.cursor = c + 1
            else:
                self.focused = False
                return True
        elif key == arcade.key.ESCAPE:
            self.focused = False
            return True
        else:
            return False
        self._emit()
        return True

    def on_text(self, text):
        if not self.focused or not text:
            return False
        # ignore control chars (newlines handled via on_key_press)
        text = "".join(ch for ch in text if ch == "\t" or ord(ch) >= 32)
        if not text:
            return False
        c = self.cursor
        self.value = self.value[:c] + text + self.value[c:]
        self.cursor = c + len(text)
        self._emit()
        return True


# ─── TypewriterTextArea ─────────────────────────────────────────
class TypewriterTextArea:
    """Scrollable text area with a typewriter reveal animation.

    Uses ``arcade.draw_text`` with ``multiline=True`` and a pixel ``width``
    for native, font-metric-accurate wrapping.
    """

    def __init__(self, left, bottom, width, height, font_size=15,
                 text_color=(214, 210, 196), bg_color=(30, 30, 35, 200),
                 line_spacing=4, padding=18, chars_per_second=90):
        self.left, self.bottom = left, bottom
        self.width, self.height = width, height
        self.font_size = font_size
        self.text_color = text_color
        self.bg_color = bg_color
        self.line_spacing = line_spacing
        self.padding = padding
        self.scroll_offset = 0
        self._full_text = ""
        self._revealed_chars = 0
        self._chars_per_second = chars_per_second
        self._reveal_timer = 0.0
        self._fully_revealed = True
        self._content_height = 0

    def update_position(self, left, bottom, width, height):
        self.left, self.bottom = left, bottom
        self.width, self.height = width, height

    def set_text(self, text, animate=True):
        self._full_text = text or ""
        self.scroll_offset = 0
        if animate and self._chars_per_second > 0 and self._full_text:
            self._revealed_chars = 0
            self._reveal_timer = 0.0
            self._fully_revealed = False
        else:
            self._revealed_chars = len(self._full_text)
            self._fully_revealed = True

    def skip_animation(self):
        self._revealed_chars = len(self._full_text)
        self._fully_revealed = True

    def set_speed(self, chars_per_second):
        self._chars_per_second = max(1, int(chars_per_second))

    @property
    def is_animating(self):
        return not self._fully_revealed

    def update(self, dt):
        if not self._fully_revealed:
            self._reveal_timer += dt
            add = int(self._reveal_timer * self._chars_per_second)
            if add > 0:
                self._revealed_chars = min(self._revealed_chars + add, len(self._full_text))
                self._reveal_timer = 0.0
                if self._revealed_chars >= len(self._full_text):
                    self._fully_revealed = True

    def draw(self):
        cx = self.left + self.width / 2
        cy = self.bottom + self.height / 2
        arcade.draw_rect_filled(XYWH(cx, cy, self.width, self.height),
                                color=self.bg_color)

        visible = self._full_text[: self._revealed_chars]
        if not visible:
            return

        text_w = self.width - self.padding * 2
        text_x = self.left + self.padding
        text_top = self.bottom + self.height - self.padding

        arcade.draw_text(
            visible, text_x, text_top + self.scroll_offset,
            self.text_color, font_size=self.font_size,
            width=int(text_w), multiline=True,
            anchor_x="left", anchor_y="top",
        )

        # Estimate content height for scrollbar
        avg_cpl = max(1, text_w / (self.font_size * 0.52))
        est_lines = (len(visible) / max(1, avg_cpl)
                     + visible.count("\n") * 1.5)
        line_h = self.font_size + self.line_spacing
        self._content_height = est_lines * line_h

        if self._content_height > self.height:
            bar_h = max(20, self.height * (self.height / self._content_height))
            max_s = max(1, self._content_height - self.height)
            bar_y = (self.bottom + self.height
                     - (self.scroll_offset / max_s) * (self.height - bar_h)
                     - bar_h / 2)
            arcade.draw_rect_filled(
                XYWH(self.left + self.width - 6, bar_y, 6, bar_h),
                color=(120, 120, 130, 140))

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        if (self.left <= x <= self.left + self.width
                and self.bottom <= y <= self.bottom + self.height):
            self.scroll_offset += scroll_y * 28
            max_s = max(0, self._content_height - self.height + self.padding * 2)
            self.scroll_offset = max(0, min(self.scroll_offset, max_s))
            return True
        return False


# ─── StatBar ────────────────────────────────────────────────────
class StatBar:
    def __init__(self, left, cy, width, height, label, value, max_value,
                 bar_color=(60, 160, 80), bg_color=(35, 35, 40)):
        self.left, self.cy = left, cy
        self.width, self.height = width, height
        self.label = label
        self.value = value
        self.max_value = max_value
        self.bar_color = bar_color
        self.bg_color = bg_color
        self.flash = 0.0   # 0..1 highlight fade after change

    def draw(self):
        cx = self.left + self.width / 2
        arcade.draw_rect_filled(XYWH(cx, self.cy, self.width, self.height),
                                color=self.bg_color)
        if self.max_value > 0:
            ratio = max(0, min(1, self.value / self.max_value))
            fw = ratio * self.width
            if fw > 0:
                # Use a slightly desaturated tint when very low
                col = self.bar_color
                if ratio < 0.25:
                    col = (200, 80, 60)  # warning red
                arcade.draw_rect_filled(
                    XYWH(self.left + fw / 2, self.cy, fw, self.height),
                    color=col)
        # flash highlight
        if self.flash > 0.01:
            a = int(140 * self.flash)
            arcade.draw_rect_filled(XYWH(cx, self.cy, self.width, self.height),
                                    color=(255, 240, 180, a))
        arcade.draw_rect_outline(XYWH(cx, self.cy, self.width, self.height),
                                 color=(85, 85, 95), border_width=1)
        arcade.draw_text(f"{self.label}: {self.value}/{self.max_value}",
                         self.left + 6, self.cy, (225, 225, 230), font_size=9,
                         anchor_x="left", anchor_y="center")

    def update(self, dt):
        if self.flash > 0:
            self.flash = max(0.0, self.flash - dt * 1.5)


# ─── InventorySlot ──────────────────────────────────────────────
class InventorySlot:
    def __init__(self, cx, cy, size, item_id="", item_name="", item_desc="",
                 icon_texture=None, item_type="misc", usable=False):
        self.cx, self.cy, self.size = cx, cy, size
        self.item_id = item_id
        self.item_name = item_name
        self.item_desc = item_desc
        self.icon_texture = icon_texture
        self.item_type = item_type
        self.usable = usable
        self.hovered = False
        self.selected = False

    def contains(self, x, y):
        return (abs(x - self.cx) <= self.size / 2
                and abs(y - self.cy) <= self.size / 2)

    def draw(self):
        if self.selected:
            bg = (110, 110, 70)
        elif self.hovered:
            bg = (90, 90, 105)
        else:
            bg = (50, 50, 60)
        arcade.draw_rect_filled(XYWH(self.cx, self.cy, self.size, self.size),
                                color=bg)
        # Type tint border
        type_colors = {"weapon": (200, 110, 80), "armor": (100, 130, 180),
                       "consumable": (90, 170, 90), "quest": (220, 190, 100),
                       "accessory": (180, 130, 200)}
        bc = type_colors.get(self.item_type, (110, 110, 120))
        arcade.draw_rect_outline(XYWH(self.cx, self.cy, self.size, self.size),
                                 color=bc, border_width=1)
        if self.icon_texture:
            arcade.draw_texture_rect(
                self.icon_texture,
                XYWH(self.cx, self.cy + 2, self.size - 8, self.size - 8))
        elif self.item_name:
            arcade.draw_text(self.item_name[:3].upper(), self.cx, self.cy + 3,
                             (210, 210, 215), font_size=10,
                             anchor_x="center", anchor_y="center", bold=True)
        if self.item_name:
            arcade.draw_text(self.item_name[:11], self.cx,
                             self.cy - self.size // 2 + 6,
                             (170, 170, 180), font_size=6,
                             anchor_x="center", anchor_y="center")
        # Use indicator
        if self.usable:
            arcade.draw_circle_filled(self.cx + self.size / 2 - 5,
                                      self.cy + self.size / 2 - 5,
                                      3, (90, 200, 90))


# ─── Tooltip ────────────────────────────────────────────────────
class Tooltip:
    def __init__(self):
        self.visible = False
        self.text = ""
        self.title = ""
        self.x = 0
        self.y = 0
        self.timer = 0.0
        self.delay = 0.25

    def show(self, x, y, title, text):
        if self.title != title:
            self.timer = 0.0
        self.title = title
        self.text = text
        self.x, self.y = x, y
        self.visible = True

    def hide(self):
        self.visible = False
        self.timer = 0.0

    def update(self, dt):
        if self.visible:
            self.timer += dt

    def draw(self, screen_w=None, screen_h=None):
        if not self.visible or self.timer < self.delay:
            return
        lines = textwrap.wrap(self.text, width=42) or [""]
        th = 18
        lh = 14
        pad = 10
        bw = min(320, max(len(self.title) * 8 + 20,
                          max((len(l) * 7 for l in lines), default=80) + 20))
        bh = th + len(lines) * lh + pad * 2
        bx = self.x + 15
        by = self.y + 15
        # keep inside screen
        if screen_w and bx + bw > screen_w:
            bx = self.x - bw - 10
        if screen_h and by + bh > screen_h:
            by = screen_h - bh - 10
        arcade.draw_rect_filled(XYWH(bx + bw // 2, by + bh // 2, bw, bh),
                                color=(20, 20, 28, 235))
        arcade.draw_rect_outline(XYWH(bx + bw // 2, by + bh // 2, bw, bh),
                                 color=(140, 140, 160), border_width=1)
        arcade.draw_text(self.title, bx + pad, by + bh - pad,
                         (230, 200, 130), font_size=11,
                         anchor_x="left", anchor_y="top", bold=True)
        ty = by + bh - pad - th
        for line in lines:
            arcade.draw_text(line, bx + pad, ty, (190, 190, 200),
                             font_size=9, anchor_x="left", anchor_y="top")
            ty -= lh


# ─── MessageLog ─────────────────────────────────────────────────
class MessageLog:
    def __init__(self, max_visible=5):
        self.messages: list[dict] = []
        self.max_visible = max_visible

    def add(self, text, duration=3.4, color=(255, 220, 100)):
        self.messages.append({"text": text, "timer": duration,
                              "max_timer": duration, "color": color})
        if len(self.messages) > 24:
            self.messages = self.messages[-24:]

    def update(self, dt):
        for m in self.messages:
            m["timer"] -= dt
        self.messages = [m for m in self.messages if m["timer"] > 0]

    def draw(self, cx, bottom_y):
        # Show most-recent N, fading by remaining timer
        recent = self.messages[-self.max_visible:]
        y = bottom_y
        for msg in reversed(recent):
            alpha = min(255, int(255 * (msg["timer"] / msg["max_timer"]) * 2))
            # Subtle bg pill
            tw = max(120, len(msg["text"]) * 7 + 24)
            arcade.draw_rect_filled(XYWH(cx, y + 8, tw, 22),
                                    color=(20, 20, 28, min(170, alpha)))
            arcade.draw_text(msg["text"], cx, y + 8,
                             (*msg["color"][:3], alpha),
                             font_size=12, anchor_x="center", anchor_y="center")
            y += 26


# ─── NodeWidget (Studio) ────────────────────────────────────────
class NodeWidget:
    def __init__(self, scene_id, title, x, y, width=180, height=64,
                 color=(50, 70, 100)):
        self.scene_id = scene_id
        self.title = title
        self.x, self.y = x, y
        self.width, self.height = width, height
        self.color = color
        self.selected = False
        self.dragging = False
        self.choice_count = 0
        self.has_error = False

    def contains(self, x, y):
        return (abs(x - self.x) <= self.width / 2
                and abs(y - self.y) <= self.height / 2)

    def draw(self):
        c = (self.color if not self.selected
             else _lighten(self.color, 50))
        arcade.draw_rect_filled(XYWH(self.x, self.y, self.width, self.height),
                                color=c)
        if self.has_error:
            bc = (220, 80, 60)
        elif self.selected:
            bc = (220, 200, 110)
        else:
            bc = (110, 110, 130)
        bw = 2 if (self.selected or self.has_error) else 1
        arcade.draw_rect_outline(XYWH(self.x, self.y, self.width, self.height),
                                 color=bc, border_width=bw)
        # Title bar
        tby = self.y + self.height / 2 - 11
        arcade.draw_rect_filled(XYWH(self.x, tby, self.width - 4, 18),
                                color=_darken(c, 30))
        arcade.draw_text(self.title[:24], self.x, tby, (230, 230, 235),
                         font_size=9, anchor_x="center", anchor_y="center",
                         bold=True)
        # ID + choice count
        arcade.draw_text(self.scene_id, self.x - self.width / 2 + 6,
                         self.y - 4, (180, 180, 190), font_size=7,
                         anchor_x="left", anchor_y="center")
        arcade.draw_text(f"{self.choice_count}↗", self.x + self.width / 2 - 8,
                         self.y - 4, (180, 200, 220), font_size=7,
                         anchor_x="right", anchor_y="center")

    def get_output_port(self):
        return (self.x + self.width / 2, self.y)

    def get_input_port(self):
        return (self.x - self.width / 2, self.y)


# ─── DiceRoller ─────────────────────────────────────────────────
class DiceRoller:
    """Animated 2d6 widget. Call ``start(result_dict)`` to play, then
    poll ``finished`` to advance the scene.

    The ``result_dict`` should be the dict returned by
    ``data_model.roll_check``.
    """
    DURATION = 1.4   # total roll time

    def __init__(self):
        self.active = False
        self.t = 0.0
        self.result: dict | None = None
        self._face1 = 1
        self._face2 = 1
        self.finished = False

    def start(self, result: dict):
        self.active = True
        self.finished = False
        self.t = 0.0
        self.result = result

    def reset(self):
        self.active = False
        self.finished = False
        self.t = 0.0
        self.result = None

    def update(self, dt):
        if not self.active or not self.result:
            return
        self.t += dt
        if self.t < self.DURATION - 0.2:
            # tumbling — flicker faces
            self._face1 = ((int(self.t * 14) % 6) + 1)
            self._face2 = ((int(self.t * 17 + 3) % 6) + 1)
        else:
            self._face1 = self.result["d1"]
            self._face2 = self.result["d2"]
        if self.t >= self.DURATION:
            self.finished = True

    def draw(self, cx, cy):
        if not self.active or not self.result:
            return
        # Backdrop
        arcade.draw_rect_filled(XYWH(cx, cy, 460, 200), color=(15, 15, 22, 232))
        arcade.draw_rect_outline(XYWH(cx, cy, 460, 200),
                                 color=(140, 130, 90), border_width=2)
        r = self.result
        arcade.draw_text(f"SKILL CHECK — {r['stat'].upper()} vs DC {r['dc']}",
                         cx, cy + 75, (230, 210, 140), font_size=14,
                         anchor_x="center", anchor_y="center", bold=True)
        # Two dice
        self._draw_die(cx - 60, cy + 5, self._face1)
        self._draw_die(cx + 60, cy + 5, self._face2)
        arcade.draw_text("+", cx, cy + 5, (220, 220, 220), font_size=22,
                         anchor_x="center", anchor_y="center", bold=True)
        # Sum + bonus + total
        if self.t >= self.DURATION - 0.2:
            arcade.draw_text(f"{r['d1']} + {r['d2']} + {r['bonus']} = {r['total']}",
                             cx, cy - 50, (220, 220, 220), font_size=14,
                             anchor_x="center", anchor_y="center")
        if self.finished:
            if r.get("critical_success"):
                msg, c = "CRITICAL SUCCESS!", (120, 230, 120)
            elif r.get("critical_failure"):
                msg, c = "CRITICAL FAILURE!", (230, 100, 100)
            elif r["success"]:
                msg, c = "SUCCESS", (120, 220, 120)
            else:
                msg, c = "FAILURE", (220, 100, 100)
            arcade.draw_text(msg, cx, cy - 78, c, font_size=15,
                             anchor_x="center", anchor_y="center", bold=True)
            arcade.draw_text("Click or press SPACE to continue",
                             cx, cy - 95, (160, 160, 175), font_size=9,
                             anchor_x="center", anchor_y="center")

    @staticmethod
    def _draw_die(cx, cy, face):
        arcade.draw_rect_filled(XYWH(cx, cy, 56, 56), color=(235, 230, 220))
        arcade.draw_rect_outline(XYWH(cx, cy, 56, 56), color=(60, 50, 40),
                                 border_width=2)
        # Pip layout 6 positions: top-left, top-right, mid-left, mid-right,
        #                         bot-left, bot-right, plus center.
        positions = {
            1: [(0, 0)],
            2: [(-1, -1), (1, 1)],
            3: [(-1, -1), (0, 0), (1, 1)],
            4: [(-1, -1), (1, 1), (-1, 1), (1, -1)],
            5: [(-1, -1), (1, 1), (-1, 1), (1, -1), (0, 0)],
            6: [(-1, -1), (1, 1), (-1, 1), (1, -1), (-1, 0), (1, 0)],
        }
        for px, py in positions.get(face, [(0, 0)]):
            arcade.draw_circle_filled(cx + px * 14, cy + py * 14, 4,
                                      (40, 30, 30))


# ─── Panel ──────────────────────────────────────────────────────
class Panel:
    """Modal-style panel with title bar and outline."""
    def __init__(self, cx, cy, w, h, title="", color=(22, 22, 32, 236),
                 border_color=(120, 120, 145)):
        self.cx, self.cy, self.w, self.h = cx, cy, w, h
        self.title = title
        self.color = color
        self.border_color = border_color

    def draw(self):
        arcade.draw_rect_filled(XYWH(self.cx, self.cy, self.w, self.h),
                                color=self.color)
        arcade.draw_rect_outline(XYWH(self.cx, self.cy, self.w, self.h),
                                 color=self.border_color, border_width=2)
        if self.title:
            arcade.draw_rect_filled(
                XYWH(self.cx, self.cy + self.h / 2 - 18, self.w, 30),
                color=(34, 34, 46, 240))
            arcade.draw_text(self.title, self.cx,
                             self.cy + self.h / 2 - 18,
                             (230, 210, 140), font_size=13,
                             anchor_x="center", anchor_y="center", bold=True)


# ─── TabBar ─────────────────────────────────────────────────────
class TabBar:
    def __init__(self, left, cy, width, height, tabs, active=0, on_change=None):
        self.left, self.cy = left, cy
        self.width, self.height = width, height
        self.tabs = tabs
        self.active = active
        self.on_change = on_change
        self.hovered = -1

    def _tab_w(self):
        return self.width / max(1, len(self.tabs))

    def contains(self, x, y):
        return (self.left <= x <= self.left + self.width
                and abs(y - self.cy) <= self.height / 2)

    def draw(self):
        tw = self._tab_w()
        for i, label in enumerate(self.tabs):
            cx = self.left + tw * i + tw / 2
            is_active = (i == self.active)
            if is_active:
                bg = (60, 70, 90)
            elif i == self.hovered:
                bg = (40, 44, 58)
            else:
                bg = (28, 28, 36)
            arcade.draw_rect_filled(XYWH(cx, self.cy, tw - 2, self.height),
                                    color=bg)
            tc = (230, 220, 180) if is_active else (170, 170, 180)
            arcade.draw_text(label, cx, self.cy, tc, font_size=11,
                             anchor_x="center", anchor_y="center",
                             bold=is_active)
            if is_active:
                arcade.draw_line(self.left + tw * i + 2, self.cy - self.height / 2,
                                 self.left + tw * (i + 1) - 2, self.cy - self.height / 2,
                                 (210, 200, 140), 2)

    def on_mouse_motion(self, x, y):
        if self.contains(x, y):
            tw = self._tab_w()
            self.hovered = int((x - self.left) / max(1, tw))
        else:
            self.hovered = -1

    def on_mouse_press(self, x, y, button):
        if (button == arcade.MOUSE_BUTTON_LEFT and self.contains(x, y)):
            tw = self._tab_w()
            idx = int((x - self.left) / max(1, tw))
            if 0 <= idx < len(self.tabs) and idx != self.active:
                self.active = idx
                if self.on_change:
                    self.on_change(idx)
            return True
        return False
