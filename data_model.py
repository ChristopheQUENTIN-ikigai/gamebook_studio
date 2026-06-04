"""
data_model.py — Core data structures for Gamebook Studio.

Entities: Choice, Scene, Item, PlayerState, GameBook

Extensions over the baseline:
    * Skill-check rolls on choices: ``roll: "stat:DC"`` with optional
      ``fail_target`` and ``fail_effects``.
    * Item-use effects (``consumable``/``use_effects``).
    * Achievements declared at book level.
    * Save metadata (timestamp, scene title, stats snapshot) for slot previews.
    * Project validation (broken targets, dead ends, orphans, missing items).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
import json
import os
import time
import random


# ─── Choice ─────────────────────────────────────────────────────
@dataclass
class Choice:
    """A single decision a player can take from a scene."""
    text: str
    target: str
    conditions: dict = field(default_factory=dict)
    effects: dict = field(default_factory=dict)
    roll: str = ""              # e.g. "might:14"
    fail_target: str = ""       # scene id on roll failure
    fail_effects: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"text": self.text, "target": self.target,
             "conditions": self.conditions, "effects": self.effects}
        if self.roll:         d["roll"] = self.roll
        if self.fail_target:  d["fail_target"] = self.fail_target
        if self.fail_effects: d["fail_effects"] = self.fail_effects
        if self.tags:         d["tags"] = self.tags
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Choice":
        return cls(
            text=d.get("text", ""),
            target=d.get("target", ""),
            conditions=d.get("conditions", {}) or {},
            effects=d.get("effects", {}) or {},
            roll=d.get("roll", "") or "",
            fail_target=d.get("fail_target", "") or "",
            fail_effects=d.get("fail_effects", {}) or {},
            tags=list(d.get("tags", []) or []),
        )


# ─── Scene ──────────────────────────────────────────────────────
@dataclass
class Scene:
    id: str
    title: str
    body: str
    choices: list = field(default_factory=list)
    illustration: str = ""
    sound: str = ""
    ambient: str = ""
    position: tuple = (0, 0)
    on_enter: list = field(default_factory=list)   # list[dict] of effects
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "body": self.body,
            "choices": [c.to_dict() if isinstance(c, Choice) else c for c in self.choices],
            "illustration": self.illustration, "sound": self.sound,
            "ambient": self.ambient,
            "position": {"x": self.position[0], "y": self.position[1]},
            "on_enter": self.on_enter, "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        choices = [Choice.from_dict(c) if isinstance(c, dict) else c
                   for c in d.get("choices", [])]
        pos = d.get("position", {"x": 0, "y": 0})
        return cls(
            id=d["id"], title=d.get("title", d["id"]), body=d.get("body", ""),
            choices=choices,
            illustration=d.get("illustration", ""),
            sound=d.get("sound", ""), ambient=d.get("ambient", ""),
            position=(pos.get("x", 0), pos.get("y", 0)),
            on_enter=d.get("on_enter", []) or [],
            tags=list(d.get("tags", []) or []),
        )

    def is_ending(self) -> bool:
        if not self.choices:
            return True
        return any(t in self.tags for t in ("ending", "victory", "defeat", "death"))


# ─── Item ───────────────────────────────────────────────────────
@dataclass
class Item:
    id: str
    name: str
    description: str
    icon: str = ""
    item_type: str = "misc"      # weapon, armor, accessory, consumable, quest, misc
    stackable: bool = False
    consumable: bool = False
    use_effects: dict = field(default_factory=dict)
    effects: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"id": self.id, "name": self.name, "description": self.description,
             "icon": self.icon, "type": self.item_type,
             "stackable": self.stackable, "effects": self.effects}
        if self.consumable:  d["consumable"] = True
        if self.use_effects: d["use_effects"] = self.use_effects
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        item_type = d.get("type", "misc")
        consumable = d.get("consumable", item_type == "consumable")
        return cls(
            id=d["id"], name=d.get("name", d["id"]),
            description=d.get("description", ""),
            icon=d.get("icon", ""), item_type=item_type,
            stackable=d.get("stackable", False),
            consumable=consumable,
            use_effects=d.get("use_effects", {}) or {},
            effects=d.get("effects", {}) or {},
        )


# ─── PlayerState ────────────────────────────────────────────────
@dataclass
class PlayerState:
    name: str = "Adventurer"
    stats: dict = field(default_factory=dict)
    max_stats: dict = field(default_factory=dict)
    inventory: list = field(default_factory=list)
    max_inventory: int = 12
    gold: int = 0
    codewords: list = field(default_factory=list)
    disciplines: list = field(default_factory=list)
    current_scene: str = ""
    visited_scenes: list = field(default_factory=list)
    notebook: list = field(default_factory=list)
    flags: dict = field(default_factory=dict)
    history: list = field(default_factory=list)        # last N scene ids
    play_seconds: float = 0.0
    achievements: list = field(default_factory=list)
    choices_made: int = 0
    rolls_succeeded: int = 0
    rolls_failed: int = 0

    # ── inventory ───────────────────────────────────────────────
    def has_item(self, item_id: str) -> bool:
        return item_id in self.inventory

    def add_item(self, item_id: str) -> bool:
        if len(self.inventory) >= self.max_inventory:
            return False
        self.inventory.append(item_id)
        return True

    def remove_item(self, item_id: str) -> bool:
        if item_id in self.inventory:
            self.inventory.remove(item_id)
            return True
        return False

    # ── stats ───────────────────────────────────────────────────
    def modify_stat(self, stat: str, amount: int) -> int:
        if stat not in self.stats:
            return 0
        before = self.stats[stat]
        cap = self.max_stats.get(stat, 999)
        self.stats[stat] = max(0, min(before + amount, cap))
        return self.stats[stat] - before

    # ── conditions ──────────────────────────────────────────────
    def check_condition(self, conditions: dict) -> bool:
        for key, value in conditions.items():
            base = _strip_suffix(key)
            if base == "has_item":
                if not self.has_item(value):
                    return False
            elif base == "not_has_item":
                if self.has_item(value):
                    return False
            elif base == "min_stat":
                sn, mv = _split_pair(value)
                if sn is not None and self.stats.get(sn, 0) < _to_int(mv):
                    return False
            elif base == "max_stat":
                sn, mv = _split_pair(value)
                if sn is not None and self.stats.get(sn, 0) > _to_int(mv):
                    return False
            elif base == "has_codeword":
                if value not in self.codewords:
                    return False
            elif base in ("not_codeword", "not_has_codeword"):
                if value in self.codewords:
                    return False
            elif base == "min_gold":
                if self.gold < _to_int(value):
                    return False
            elif base == "max_gold":
                if self.gold > _to_int(value):
                    return False
            elif base == "flag":
                fname, fval = _split_pair(value)
                if fname is not None and str(self.flags.get(fname, "")) != fval:
                    return False
            elif base == "visited":
                if value not in self.visited_scenes:
                    return False
            elif base == "not_visited":
                if value in self.visited_scenes:
                    return False
            elif base.startswith("min_"):       # README direct form: min_<stat>
                if self.stats.get(base[4:], 0) < _to_int(value):
                    return False
            elif base.startswith("max_"):       # README direct form: max_<stat>
                if self.stats.get(base[4:], 0) > _to_int(value):
                    return False
        return True

    def condition_failure_reason(self, conditions: dict,
                                 item_lookup: dict | None = None) -> str:
        item_lookup = item_lookup or {}
        for key, value in conditions.items():
            base = _strip_suffix(key)
            if base == "has_item" and not self.has_item(value):
                return f"Need: {item_lookup.get(value, value)}"
            if base == "not_has_item" and self.has_item(value):
                return f"Cannot carry: {item_lookup.get(value, value)}"
            if base == "min_stat":
                sn, mv = _split_pair(value)
                if sn is not None and self.stats.get(sn, 0) < _to_int(mv):
                    return f"Need {sn.upper()} ≥ {mv}"
            if base == "max_stat":
                sn, mv = _split_pair(value)
                if sn is not None and self.stats.get(sn, 0) > _to_int(mv):
                    return f"Need {sn.upper()} ≤ {mv}"
            if base.startswith("min_") and base not in ("min_stat", "min_gold"):
                sn = base[4:]
                if self.stats.get(sn, 0) < _to_int(value):
                    return f"Need {sn.upper()} ≥ {value}"
            if base.startswith("max_") and base not in ("max_stat", "max_gold"):
                sn = base[4:]
                if self.stats.get(sn, 0) > _to_int(value):
                    return f"Need {sn.upper()} ≤ {value}"
            if base == "min_gold" and self.gold < _to_int(value):
                return f"Need {value} gold"
            if base == "max_gold" and self.gold > _to_int(value):
                return f"Carrying too much gold"
            if base == "has_codeword" and value not in self.codewords:
                return f"Need codeword: {value}"
            if base in ("not_codeword", "not_has_codeword") and value in self.codewords:
                return f"Locked by codeword: {value}"
            if base == "flag":
                fn, fv = _split_pair(value)
                if fn is not None and str(self.flags.get(fn, "")) != fv:
                    return f"Need {fn} = {fv}"
            if base == "visited" and value not in self.visited_scenes:
                return f"Must first visit: {value}"
            if base == "not_visited" and value in self.visited_scenes:
                return f"Already visited: {value}"
        return ""

    # ── effects ─────────────────────────────────────────────────
    def apply_effects(self, effects: dict) -> list[str]:
        """Apply an effect dict, returning user-visible messages.

        Tolerant of two authoring styles:
          * canonical colon form  ``{"stat": "endurance:-1"}``
          * README direct form    ``{"stat_endurance": -1}``
        Suffixed duplicate keys (``add_item2``, ``stat_b``) are resolved to
        their base verb, so callers do **not** need to re-iterate.
        """
        messages: list[str] = []
        for key, value in effects.items():
            base = _strip_suffix(key)
            if base == "add_item":
                if self.add_item(str(value)):
                    messages.append(f"Acquired: {value}")
                else:
                    messages.append("Inventory full!")
            elif base == "remove_item":
                if self.remove_item(str(value)):
                    messages.append(f"Lost: {value}")
            elif base == "stat":
                stat_name, amount = _parse_stat_effect(key, value)
                if stat_name is None:
                    continue
                delta = self.modify_stat(stat_name, amount)
                sign = "+" if delta >= 0 else ""
                messages.append(f"{stat_name.upper()} {sign}{delta}")
            elif base == "gold":
                amt = _to_int(value)
                self.gold = max(0, self.gold + amt)
                messages.append(f"Gold {'+' if amt >= 0 else ''}{amt}")
            elif base == "add_codeword":
                if value not in self.codewords:
                    self.codewords.append(str(value))
                    messages.append(f"Codeword: {value}")
            elif base == "remove_codeword":
                if value in self.codewords:
                    self.codewords.remove(str(value))
            elif base == "set_flag":
                fname, fval = _split_pair(value)
                if fname is not None:
                    self.flags[fname] = fval
            elif base in ("note", "add_note"):
                self.notebook.append(str(value))
                messages.append(f"Notebook: {value}")
            elif base == "achieve":
                if value not in self.achievements:
                    self.achievements.append(str(value))
                    messages.append(f"★ Achievement: {value}")
        return messages

    # ── serialisation ───────────────────────────────────────────
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PlayerState":
        ps = cls()
        for k, v in d.items():
            if hasattr(ps, k):
                setattr(ps, k, v)
        return ps


# ─── helpers ────────────────────────────────────────────────────
_KNOWN_BASES = (
    "has_item", "not_has_item", "min_stat", "max_stat",
    "has_codeword", "not_has_codeword", "not_codeword",
    "min_gold", "max_gold",
    "flag", "visited", "not_visited",
    "add_item", "remove_item", "stat", "gold",
    "add_codeword", "remove_codeword", "set_flag",
    "add_note", "note", "achieve",
)
# Longer bases first so e.g. ``not_has_codeword`` is matched before ``not_codeword``.
_BASES_BY_LEN = tuple(sorted(_KNOWN_BASES, key=len, reverse=True))


def _strip_suffix(key: str) -> str:
    """Resolve a possibly-suffixed key to its base verb.

    Handles both underscore suffixes (``add_item_2``, ``stat_b``) and bare
    digit suffixes (``add_item2``, ``stat3``) used by the bundled books, plus
    README-style stat keys (``stat_endurance`` -> ``stat``).
    """
    if key in _KNOWN_BASES:
        return key
    for base in _BASES_BY_LEN:
        if key.startswith(base):
            tail = key[len(base):]
            if tail == "" or tail[:1] == "_" or tail.isdigit():
                return base
    return key


def _to_int(value) -> int:
    """Best-effort int coercion (``"-3"`` -> -3, ``2.0`` -> 2, junk -> 0)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _split_pair(value):
    """Split ``"name:val"`` -> ``("name", "val")``; returns ``(None, None)`` if
    there is no separator."""
    s = str(value)
    if ":" not in s:
        return None, None
    name, val = s.split(":", 1)
    return name.strip(), val.strip()


def _parse_stat_effect(key, value):
    """Resolve a stat effect to ``(stat_name, amount)`` from either
    ``{"stat": "endurance:-1"}`` or ``{"stat_endurance": -1}``.

    Returns ``(None, 0)`` when the key/value cannot be interpreted (caller
    should skip)."""
    if isinstance(value, str) and ":" in value:
        name, amt = value.split(":", 1)
        return name.strip(), _to_int(amt)
    if str(key).lower().startswith("stat_"):
        name = key[5:].strip()
        if name and not name.isdigit():
            return name, _to_int(value)
    return None, 0


# ─── GameBook ───────────────────────────────────────────────────
@dataclass
class GameBook:
    title: str = "Untitled"
    author: str = "Unknown"
    description: str = ""
    version: str = "1.0"
    cover: str = ""
    start_scene: str = ""
    scenes: dict = field(default_factory=dict)
    items: dict = field(default_factory=dict)
    rules: dict = field(default_factory=dict)
    stat_names: list = field(default_factory=lambda: ["skill", "stamina", "luck"])
    initial_stats: dict = field(default_factory=lambda: {"skill": 10, "stamina": 20, "luck": 8})
    initial_max_stats: dict = field(default_factory=lambda: {"skill": 12, "stamina": 24, "luck": 12})
    initial_items: list = field(default_factory=list)
    initial_gold: int = 0
    theme_color: tuple = (80, 60, 40)
    achievements: dict = field(default_factory=dict)   # id -> {name, hint}
    folder_path: str = ""

    # ── scene helpers ───────────────────────────────────────────
    def get_scene(self, scene_id: str) -> Optional[Scene]:
        return self.scenes.get(scene_id)

    def add_scene(self, scene: Scene) -> None:
        self.scenes[scene.id] = scene

    def remove_scene(self, scene_id: str) -> None:
        self.scenes.pop(scene_id, None)

    def new_scene_id(self, prefix: str = "scene") -> str:
        i = 1
        while f"{prefix}_{i:03d}" in self.scenes:
            i += 1
        return f"{prefix}_{i:03d}"

    def create_player(self) -> PlayerState:
        ps = PlayerState()
        ps.stats = dict(self.initial_stats)
        ps.max_stats = dict(self.initial_max_stats)
        ps.inventory = list(self.initial_items)
        ps.gold = self.initial_gold
        ps.current_scene = self.start_scene
        return ps

    # ── validation report ───────────────────────────────────────
    def validate(self) -> dict:
        broken: list = []      # (scene_id, choice_idx, target)
        dead_ends: list = []
        orphans: list = []
        missing_items: list = []

        reached: set = set()
        if self.start_scene in self.scenes:
            stack = [self.start_scene]
            while stack:
                sid = stack.pop()
                if sid in reached:
                    continue
                reached.add(sid)
                sc = self.scenes.get(sid)
                if not sc:
                    continue
                for ch in sc.choices:
                    d = ch.to_dict() if isinstance(ch, Choice) else ch
                    for tgt_key in ("target", "fail_target"):
                        t = d.get(tgt_key, "")
                        if t and t in self.scenes:
                            stack.append(t)

        for sid, sc in self.scenes.items():
            for i, ch in enumerate(sc.choices):
                d = ch.to_dict() if isinstance(ch, Choice) else ch
                tgt = d.get("target", "")
                if tgt and tgt not in self.scenes:
                    broken.append((sid, i, tgt))
                ft = d.get("fail_target", "")
                if ft and ft not in self.scenes:
                    broken.append((sid, i, ft))
                for ekey, eval_ in (d.get("effects") or {}).items():
                    base = _strip_suffix(ekey)
                    if base in ("add_item", "remove_item") and eval_ not in self.items:
                        missing_items.append((sid, ekey, eval_))
                for ckey, cval in (d.get("conditions") or {}).items():
                    base = _strip_suffix(ckey)
                    if base in ("has_item", "not_has_item") and cval not in self.items:
                        missing_items.append((sid, ckey, cval))
            if not sc.choices and not sc.is_ending():
                dead_ends.append(sid)
            if sid not in reached:
                orphans.append(sid)

        return {"broken_targets": broken, "dead_ends": dead_ends,
                "orphans": orphans, "missing_items": missing_items,
                "reached": len(reached), "total": len(self.scenes)}

    # ── serialisation ───────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "title": self.title, "author": self.author, "description": self.description,
            "version": self.version, "cover": self.cover, "start_scene": self.start_scene,
            "scenes": {k: v.to_dict() for k, v in self.scenes.items()},
            "items": {k: v.to_dict() for k, v in self.items.items()},
            "rules": self.rules, "stat_names": self.stat_names,
            "initial_stats": self.initial_stats, "initial_max_stats": self.initial_max_stats,
            "initial_items": self.initial_items, "initial_gold": self.initial_gold,
            "theme_color": list(self.theme_color),
            "achievements": self.achievements,
        }

    @classmethod
    def from_dict(cls, d: dict, folder_path: str = "") -> "GameBook":
        gb = cls()
        gb.title = d.get("title", "Untitled")
        gb.author = d.get("author", "Unknown")
        gb.description = d.get("description", "")
        gb.version = d.get("version", "1.0")
        gb.cover = d.get("cover", "")
        gb.start_scene = d.get("start_scene", "")
        gb.scenes = {k: Scene.from_dict(v) for k, v in d.get("scenes", {}).items()}
        gb.items = {k: Item.from_dict(v) for k, v in d.get("items", {}).items()}
        gb.rules = d.get("rules", {}) or {}
        gb.stat_names = list(d.get("stat_names", ["skill", "stamina", "luck"]))
        gb.initial_stats = dict(d.get("initial_stats", {"skill": 10, "stamina": 20, "luck": 8}))
        gb.initial_max_stats = dict(d.get("initial_max_stats",
                                          {"skill": 12, "stamina": 24, "luck": 12}))
        gb.initial_items = list(d.get("initial_items", []))
        gb.initial_gold = int(d.get("initial_gold", 0))
        gb.theme_color = tuple(d.get("theme_color", [80, 60, 40]))
        gb.achievements = dict(d.get("achievements", {}) or {})
        gb.folder_path = folder_path
        return gb

    def save(self, path: str | None = None) -> None:
        if path is None:
            path = os.path.join(self.folder_path, "project.json")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, folder_path: str) -> "GameBook":
        path = os.path.join(folder_path, "project.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data, folder_path)


# ─── Save / Load helpers ────────────────────────────────────────
def save_game(player_state: PlayerState, folder_path: str,
              slot_name: str = "quicksave",
              scene_title: str = "") -> str:
    saves_dir = os.path.join(folder_path, "saves")
    os.makedirs(saves_dir, exist_ok=True)
    data = player_state.to_dict()
    data["_timestamp"] = time.time()
    data["_slot"] = slot_name
    data["_scene_title"] = scene_title
    path = os.path.join(saves_dir, f"{slot_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def load_game(folder_path: str, slot_name: str = "quicksave") -> Optional[PlayerState]:
    path = os.path.join(folder_path, "saves", f"{slot_name}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return PlayerState.from_dict(data)


def list_saves(folder_path: str) -> list[dict]:
    saves_dir = os.path.join(folder_path, "saves")
    if not os.path.exists(saves_dir):
        return []
    saves: list[dict] = []
    for f in os.listdir(saves_dir):
        if not f.endswith(".json"):
            continue
        path = os.path.join(saves_dir, f)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        saves.append({
            "slot": data.get("_slot", f[:-5]),
            "timestamp": data.get("_timestamp", 0),
            "scene": data.get("current_scene", "?"),
            "scene_title": data.get("_scene_title", ""),
            "stats": data.get("stats", {}),
            "gold": data.get("gold", 0),
            "play_seconds": data.get("play_seconds", 0),
            "visited": len(data.get("visited_scenes", [])),
            "path": path,
        })
    saves.sort(key=lambda s: s["timestamp"], reverse=True)
    return saves


def delete_save(folder_path: str, slot_name: str) -> bool:
    path = os.path.join(folder_path, "saves", f"{slot_name}.json")
    try:
        os.remove(path)
        return True
    except OSError:
        return False


# ─── Dice / skill-check resolver ────────────────────────────────
def roll_check(spec: str, player: PlayerState,
               rng: random.Random | None = None) -> dict:
    """Resolve a 'stat:DC' roll: 2d6 + ⌊stat/2⌋ vs DC."""
    rng = rng or random.Random()
    parts = spec.split(":")
    stat_name = parts[0].strip()
    dc = int(parts[1]) if len(parts) > 1 else 10
    d1, d2 = rng.randint(1, 6), rng.randint(1, 6)
    bonus = player.stats.get(stat_name, 0) // 2
    total = d1 + d2 + bonus
    return {"d1": d1, "d2": d2, "bonus": bonus, "total": total,
            "stat": stat_name, "dc": dc, "success": total >= dc,
            "critical_success": d1 == 6 and d2 == 6,
            "critical_failure": d1 == 1 and d2 == 1}
