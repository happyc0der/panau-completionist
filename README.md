# panau-completionist

Tools for getting **Just Cause 2** (Steam, PC) to 100%:

| Tool | What it does |
|---|---|
| **Save merge** | Combines two saves into one, taking the best of both: every collectible, destroyed object, settlement, race, black market unlock and stat either save has. |
| **Arrow overlay** | Puts an arrow on screen over every remaining collectible (white) and sabotage target (red), with edge arrows for the nearest ones off screen. Arrows disappear the instant you grab or destroy the thing. |
| **Cheats** | Infinite health and ammo. |
| **Wingsuit** | Installs or removes a community wingsuit mod from its zip. |
| **Crash fix** | A 16-byte patch for the game's most common random crash. |
| **Audit** | Checks that a save really holds the best of other saves (read-only). |

The overlay, cheats and wingsuit are **earned** by default: they unlock once your save shows the story finished
(mercenary mode) on **Hardcore**. Prefer them from the start? `panau config unlock always`.

> Windows only. Works with the Steam version of the game; other builds are detected and refused, never written to.

## Install

Needs Python 3.10+ ([uv](https://docs.astral.sh/uv/) recommended). No other dependencies.

```bash
uv tool install git+https://github.com/happyc0der/panau-completionist
```

Then run `panau`. It shows what it found: the game folder, your save folder, your newest save, and whether the
unlock is earned.

```text
panau-completionist 1.0.0
  game       D:\SteamLibrary\steamapps\common\Just Cause 2
  saves      C:\Program Files (x86)\Steam\userdata\<id>\8190\remote
  save       JustCause2Save00.sav: Hardcore, story finished, 1306 collectibles
  unlock     earned: story finished on Hardcore
```

## Play with the overlay and cheats

Set this once as the game's Steam launch option (**Steam > Just Cause 2 > Properties > Launch Options**); `panau launch-option` prints the exact line for your PC:

```text
"C:\Users\<you>\.local\bin\panau-launch.exe" %command%
```

From then on, **Play** starts the game, plus the overlay and cheats if they're unlocked. Both close themselves when
the game exits. Add game arguments after `%command%`, for example `%command% /frameratecap=120`.

Run the game **windowed** (Settings > Display: fullscreen off). Exclusive fullscreen hides every overlay. The
overlay stretches the window into a borderless full-screen window for you.

| Key (game focused) | Does |
|---|---|
| F6 | Arrow range: 250 m, 500 m (start), 1.5 km, 5 km, off |
| F9 | Show everything, collectibles only, or sabotage only |
| F7 / F8 | Small radar on/off, and its range |
| F10 / F11 | Cheats: health on/off, ammo on/off |

You can also start them by hand while the game runs: `panau overlay`, `panau cheats`.

## Merge two saves

Your saves live in `Steam\userdata\<id>\8190\remote`. Save00 is the autosave (**Continue** loads it), and Save01/Save02 are File 1/File 2 in the load menu.

1. Copy the two saves somewhere safe first.
2. Dry run: `panau merge base.sav other.sav`. **Base** is the save with the furthest story; **other** is the save
   to take extra progress from. It prints what would come over.
3. Write it: close the game, then `panau merge base.sav other.sav --out 1` writes File 1 (or `--out merged.sav` for a file).
   Whatever was in that slot is kept once in `%APPDATA%\panau-completionist\backups`.
4. Load it in game. The game rewrites the autosave right after loading; if it didn't like something it resets
   the save there, so check your % and collectible count look right.
5. `panau audit base.sav other.sav` confirms the result holds everything both had.

What comes over: collectibles, destroyed objects (all 3,559 sabotage targets the game tracks), SAM sites,
settlement counters and discovery, races and other activities (best times too), stats, black market unlocks and
the higher difficulty. Missions and faction progress stay the base's; `--take-missions` merges them too
(experimental, not verified in game).

## Wingsuit

The mods are other people's work, so they're not included. Download one, then install it from its zip:

- [JC2 Wingsuit Mod](https://videogamemods.com/vgm/justcause2/mods/jc2-wingsuit-mod) by mctheminer (2017, Just Cause 3 style: Space to fly, Shift for speed)
- [Just Cause 2 Wingsuit (Or Superman)](https://videogamemods.com/vgm/justcause2/mods/just-cause-2-wingsuit-or-superman) (2010)

```bash
panau wingsuit install "C:\Users\<you>\Downloads\Wingsuit-JC2-Mod.zip"
panau wingsuit remove
```

## Crash fix

```bash
panau crashfix apply      # backs up the original exe once
panau crashfix restore
```

It fixes the crash at `JustCause2.exe+0x209D00` (an access violation reading 0x224), which is the cause of most random crashes. Steam's "Verify integrity of game files" undoes it.

## How it works

- **Saves**: a stream of sections plus a **section table at 0x200** that the game uses to find each section. The
  merge rebuilds that table whenever a section changes size; without it the game silently resets parts of the save
  (that was the cause of every failed merge during development). See `panau/save/format.py`.
- **Progress**: a 23,833-slot hash table of (type, object) keys with one bit each. The bit means something
  different per type, so `panau/data/done_flags.json` records which value means destroyed/collected per type.
- **What counts**: the target list comes from the game's own files. Every sabotage target is an object whose
  objective marker carries an `act_*` display text (`tools/build_data.py` rebuilds the list from your install).
- **Real time**: the game keeps every loaded objective marker and pickup in lists in memory; a marker's status bit
  flips the moment its target blows up, and a pickup's flag the moment you grab it. The overlay reads those 5 times
  a second, and your save and the game's in-memory progress table for everything farther away.
- **Safety**: everything outside the game only reads memory, except the cheats' two values. Before reading or
  writing anything, the tools check the game's code at three known addresses and refuse a different build.

## Limitations

- Steam build only (checked at runtime).
- Two stat records (stats 315 and 330) are reset by the game itself after a merge; they don't affect completion.
- The four item lists in a save aren't merged: their flags switch on and off during play, so "more" isn't "better".
- After a merge, objects that came from the other save show their in-game objective marker as still standing (the game
  never refreshes it). The overlay goes by the save, so they get no arrow.
- Faction items (skulls, black boxes) aren't tracked yet.

## For AI agents

If an agent (Claude Code, Codex, Cursor...) is setting this up for someone, point it at **[AGENTS.md](AGENTS.md)**:
setup in five commands, how to verify each tool, and the traps (writing a save while the game runs, trusting an
in-game marker after a merge, running elevated).

## Credits and license

Reverse engineering, tools and data extraction: this repo, MIT licensed. Wingsuit mods: their authors, linked above.
Not affiliated with Avalanche Studios or Square Enix. Single-player use; back up your saves.
