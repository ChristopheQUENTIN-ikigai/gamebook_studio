# Gamebook Studio

An interactive-fiction engine, player, and visual editor for branching
gamebook adventures, written in Python with the
[Arcade](https://api.arcade.academy/) 3.x framework.

This release ships with three full-length sample books that show off the
engine's range: a high-fantasy adventure (*Shadows of Eldrath*), a
cosmic-horror investigation (*Whispers of R'lyeh*), and a cyberpunk caper
(*Neon Galaxy*). Each is a complete, self-contained gamebook of 25–27 scenes
with its own art, items, and tone.

---

## Highlights

* **Skill checks with animated 2d6 dice.** Choices can declare
  `roll: "stat:DC"` and the engine will roll, animate the dice, and route
  to a separate `fail_target` on failure — a Fighting-Fantasy-style mechanic
  that turns choices into real gambles.
* **Inventory with usable consumables.** Items can be marked
  `consumable: true` with `use_effects` that apply when the player uses
  them — no more inert objects sitting in the bag.
* **Character sheet, scene history, recap & back.** The player can review
  every scene visited, step back one move, and read a full character
  sheet at any time.
* **Endings screen with statistics & achievements.** Each playthrough ends
  with a recap of stats, time played, and the achievements the run earned.
* **Five save slots with previews.** Manual saves, an autosave, and a
  quicksave each show the scene title, time played, and timestamp.
* **Curated main menu.** A two-pane library browser with cover art,
  metadata, "continue last save" detection, an in-app settings panel, and
  an achievements browser.
* **Visual editor.** A node-graph studio with full inline editing — edit
  titles, bodies, tags, and a **rich per-choice editor** (text, target, roll,
  fail-target, conditions, effects, and tags); add / duplicate / delete
  scenes; mark any scene as the start; validate the project for broken
  targets, dead ends, and orphans; and play-test from any selected scene.

---

## Installation

```bash
# Python 3.11 or newer is required.
pip install arcade pillow

# Then, from this directory:
./run.sh
# or
python3 main.py
```

CLI flags:

```
python3 main.py [--verbose] [--book BOOK_FOLDER] [--no-textures]
```

* `--verbose`        Print extra startup diagnostics.
* `--book NAME`      Open a book directly into the player (skips the menu).
* `--no-textures`    Skip placeholder texture generation at startup.

---

## Default key bindings

### Anywhere

| Key       | Action            |
| --------- | ----------------- |
| `H`       | Show / hide help  |
| `F`       | Toggle fullscreen |
| `ESC`     | Back / exit       |

### Player

| Key       | Action                                |
| --------- | ------------------------------------- |
| `1`–`9`   | Pick the matching choice              |
| `SPACE`   | Skip typewriter, confirm dice roll    |
| `S`       | Open save-slot menu                   |
| `L`       | Open load-slot menu                   |
| `R`       | Quicksave                             |
| `I`       | Toggle the inventory tab              |
| `N`       | Toggle the notes tab                  |
| `C`       | Open the character sheet              |
| `B`       | Step back to the previous scene       |
| `TAB`     | Cycle the sidebar tabs (Stats/Notes/Visited) |
| `O`       | Open / close the settings overlay     |
| `E`       | Jump straight into the studio editor  |

The player toolbar also exposes click targets for each of these: `≡` help,
`⚙` settings, `S` save, `L` load, `C` character sheet, `↶` back, and `⌂`
quit to the library.

### Studio

| Key                | Action                                |
| ------------------ | ------------------------------------- |
| Left-click         | Select a node                         |
| Left-drag          | Move the selected node                |
| Middle-drag        | Pan the camera                        |
| Scroll wheel       | Zoom the camera                       |
| `+` / `=`          | Add a new scene at the cursor         |
| `Ctrl`+`D`         | Duplicate the selected scene          |
| `-` / `Delete`     | Delete the selected scene (confirm)   |
| `V`                | Validate (broken links, dead ends…)   |
| `S`                | Save the project                      |

Switching node selection auto-applies any pending inspector edits, so you
never lose changes by clicking another node before pressing **Apply**.

All of these are remappable in `config.json` under the `keys` block.

---

## Project structure

```
gamebook_studio/
├── main.py            # views (menu / player / studio) + entry point
├── data_model.py      # GameBook, Scene, Choice, Item, PlayerState, save/load
├── ui_widgets.py      # Buttons, inputs, sliders, dice roller, panels…
├── texture_gen.py     # procedural placeholder art generator
├── config.json        # window, keys, display, audio, gameplay
├── run.sh             # convenience launcher
├── assets/            # generated illustrations, icons, backgrounds
└── library/
    ├── shadows_of_eldrath/
    │   ├── project.json    # the entire book in one JSON file
    │   ├── illustrations/
    │   ├── icons/
    │   └── saves/          # per-book save slots
    ├── whispers_of_rlyeh/
    └── neon_galaxy/
```

---

## Authoring a gamebook

A gamebook is a single `project.json` file in `library/<your_book>/`.
Drop the folder in `library/` and it appears on the main menu.

### Top-level shape

```json
{
  "title": "My Book",
  "author": "Me",
  "description": "A short pitch shown on the menu.",
  "version": "1.0",
  "cover": "illustrations/cover.png",
  "start_scene": "scene_001",
  "stat_names": ["might", "wit", "valor"],
  "initial_stats":     { "might": 10, "wit": 8, "valor": 12 },
  "initial_max_stats": { "might": 14, "wit": 14, "valor": 16 },
  "initial_items": ["ranger_sword"],
  "initial_gold": 5,
  "theme_color": [40, 60, 80],
  "achievements": { "first_ending": { "name": "...", "hint": "..." } },
  "items":  { "ranger_sword": { "name": "Ranger's Sword", "...": "..." } },
  "scenes": { "scene_001": { "title": "...", "body": "...", "choices": [...] } }
}
```

### Scenes

```json
"scene_001": {
  "id": "scene_001",
  "title": "The Ashgate Falls",
  "body": "Long-form narrative text. Two newlines for a paragraph break.",
  "choices": [ ... ],
  "tags": ["start"],
  "illustration": "illustrations/ashgate.png",
  "ambient_color": [30, 30, 50],
  "position": [0, 0]
}
```

`tags` carry meaning to the engine: `start`, `ending`, `victory`, `defeat`,
`death`, `combat`, `boss`, `climax`, `encounter`, `revelation`, `lore`.
The studio uses tags to colour-code nodes; the player uses `victory` /
`defeat` / `death` to drive the ending screen.

### Choices

A choice can be as simple as:

```json
{ "text": "Take the road north.", "target": "scene_005" }
```

…or as complex as:

```json
{
  "text": "Vault from the rampart onto the courier's wagon below.",
  "roll": "valor:9",
  "target": "scene_002",
  "fail_target": "scene_002",
  "effects":      { "stat_endurance": -1 },
  "fail_effects": { "stat_endurance": -3 },
  "conditions":   { "min_might": 8, "has_item": "ranger_sword" },
  "tags": ["skill_check"]
}
```

#### Skill checks

`"roll": "<stat>:<DC>"` triggers an animated 2d6 + ⌊stat/2⌋ check at choice
time. On success the engine routes to `target` and applies `effects`; on
failure it routes to `fail_target` (or `target` if absent) and applies
`fail_effects`. A natural 12 is a critical hit, a natural 2 a critical fail.

#### Effects

Effects live under `effects` (and optionally `fail_effects`). Keys you can
use:

| Key                       | Meaning                                     |
| ------------------------- | ------------------------------------------- |
| `stat_<name>: ±N`         | Adjust a stat (clamped to its max)          |
| `add_item: "item_id"`     | Grant an item                               |
| `remove_item: "item_id"`  | Take an item away                           |
| `gold: ±N`                | Adjust gold                                 |
| `add_codeword: "..."`     | Set a flag the player keeps forever         |
| `remove_codeword: "..."`  | Clear that flag                             |
| `add_note: "..."`         | Append a line to the player's journal       |

If you need more than one of the same effect on a single choice, suffix the
key with a digit: `add_item`, `add_item2`, `add_item3` all work (an
`add_item_2` underscore form is accepted too). The engine strips the suffix
before applying, so each entry runs independently.

##### Two equivalent syntaxes

The engine accepts **both** the *direct* form above and a *colon* form where
the stat name or threshold travels inside the value. The bundled sample books
use the colon form, so you will see both in the wild — they are interchangeable:

```jsonc
// direct form                       // colon form (equivalent)
{ "stat_valor": -2 }            ==   { "stat": "valor:-2" }
{ "min_might": 12 }             ==   { "min_stat": "might:12" }
{ "max_wit": 8 }                ==   { "max_stat": "wit:8" }
```

Integer values may be written as numbers (`-2`) or strings (`"-2"`); the
editor's choice panel coerces numeric text back to integers on save.

#### Conditions

Choices that fail their `conditions` block become locked, and the player
sees a hint about *why* (e.g. *"Requires might 10."*, *"Need iron_key."*).
As with effects, `min_<stat>: N` and `min_stat: "<stat>:N"` are equivalent.

| Condition key             | Meaning                                  |
| ------------------------- | ---------------------------------------- |
| `min_<stat>: N`           | Stat must be ≥ N                         |
| `max_<stat>: N`           | Stat must be ≤ N                         |
| `has_item: "id"`          | Player must own the item                 |
| `not_has_item: "id"`      | Player must *not* own the item           |
| `has_codeword: "..."`     | Codeword must be set                     |
| `not_has_codeword: "..."` | Codeword must not be set                 |
| `min_gold: N`             | Gold must be ≥ N                         |
| `max_gold: N`             | Gold must be ≤ N                         |
| `visited: "scene_id"`     | The given scene must have been visited   |
| `not_visited: "scene_id"` | The given scene must *not* have been     |

### Items

```json
"healing_root": {
  "id": "healing_root",
  "name": "Healing Root",
  "description": "A bitter tuber that knits flesh together.",
  "icon": "icons/healing_root.png",
  "tags": ["consumable", "healing"],
  "stackable": true,
  "value": 6,
  "consumable": true,
  "use_effects": { "stat_endurance": 4 }
}
```

Set `consumable: true` and provide `use_effects` to make an item the player
can click in their inventory to apply its effect. Consumables are removed
on use.

### Achievements

Books can declare custom achievements via the `achievements` block at the
top level. Each entry is an `id → { "name", "hint" }`. The engine awards
six default achievements automatically:

| ID              | Awarded for…                                            |
| --------------- | ------------------------------------------------------- |
| `first_ending`  | Reaching any ending.                                    |
| `victor`        | Reaching a scene tagged `victory`.                      |
| `fallen`        | Reaching a scene tagged `defeat` or `death`.            |
| `completionist` | Visiting every scene in a single run.                   |
| `collector`     | Owning every item the book defines (in a single run).   |
| `lucky`         | Finishing without a single failed roll.                 |

Books are free to add as many extra achievements as they want. They appear
in the menu's achievements browser and on the ending screen.

---

## Save format

Saves live in `library/<book>/saves/<slot>.json` and contain the entire
`PlayerState` plus a few metadata fields:

```json
{
  "current_scene": "scene_007",
  "stats": { "might": 9, ... },
  "inventory": ["ranger_sword", "iron_key"],
  "gold": 12,
  "codewords": ["found_warden_key"],
  "notes": ["I should bring a torch next time."],
  "visited_scenes": ["scene_001", "scene_002", "scene_007"],
  "history": [ ... ],
  "achievements": ["first_ending"],
  "play_seconds": 412.7,
  "_timestamp": 1735128371.4,
  "_slot": "slot_1",
  "_scene_title": "The Old Mine Road"
}
```

Slot names are arbitrary, but the engine treats `autosave` and `quicksave`
specially in the slot-picker UI.

---

## License

The Python engine and editor are released under the MIT License.
The three bundled gamebooks and their generated artwork are CC-BY-SA 4.0.
