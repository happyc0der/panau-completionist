# AGENTS.md: setting up panau-completionist for someone

You are helping a person get Just Cause 2 (Steam, PC) to 100% with these tools. This file is the fast path and the list of mistakes to avoid. Everything here was learned the hard way during development.

## Setup (5 commands)

```bash
uv tool install git+https://github.com/happyc0der/panau-completionist   # or: uv tool install <clone folder>
panau                       # status: game folder, save folder, newest save, unlock state
panau launch-option         # prints the Steam launch option line; the PERSON pastes it into Steam
panau crashfix apply        # optional, game closed
panau config unlock always  # only if they don't want the "earned" unlock
```

- **Steam launch option**: Steam overwrites `localconfig.vdf` while it runs, so don't edit that file yourself.
  Have the person paste the line into **Properties > Launch Options**.
- **Windowed mode**: the game must run windowed (in-game Settings > Display); exclusive fullscreen hides overlays.

## Verify each piece

| Tool | Proof it works |
|---|---|
| save merge | `panau merge A B` dry run prints counts; after writing and loading in game, the game's next autosave (Save00, rewritten seconds after a load) still has the same collectible count and difficulty; `panau audit A B` exits 0 (it also checks the faction item counters; `panau repair --write` fixes a save merged with 1.0) |
| overlay | with the game running and unlocked, `panau overlay` shows red/white arrows; destroying a nearby target removes its arrow within ~0.3 s |
| cheats | `panau cheats` while in game: health stays full under fire; a clip never empties |
| unlock | `panau` prints `unlock: earned: ...` or `locked: ...` with the reason |

## Traps

1. **Never write a save while the game runs.** It autosaves over your file. Every writing command checks this; don't work around it.
2. **The autosave is the acceptance test.** After loading an edited save, the game rewrites Save00 within seconds. If the game rejected something, that rewrite is where the reset shows: difficulty back to 1, collected count drops, item lists shrink to `[95,3,13,3]`. Compare before and after.
3. **The section table at 0x200** must match the sections after any edit (`Save.to_bytes()` rebuilds it). A stale table makes the game silently reset sections; it is not a "validator", don't go hunting one.
4. **"Done" is per type**: the world-table bit means different things for different type keys. Use `panau/data/done_flags.json` via `save.world.is_done()`; never treat bit 1 as "done".
5. **Markers lie after a merge**: objects merged in as destroyed keep their in-game marker at "standing" (0xFB) forever. Trust the save for "standing"; trust a marker only when it says "destroyed" (0xFA).
6. **Don't run the game or the tools elevated.** An elevated launcher makes the game inherit admin rights. That breaks other tools' access to it, and the overlay's click-through windows stop working.
7. **Other game builds** (non-Steam, older patches) are refused by `panau.game.addresses.build_ok()`. Don't remove that check; the addresses are build-specific.
8. **Don't ship or download game files or other people's mods** into the repo. Wingsuit mods are installed from a zip the person downloaded.
9. **Stats 315 and 330** come back as 0 after a merge: the game recomputes them. Not a bug, and not completion-relevant.
10. **Steam Cloud** syncs the save folder; an edited save uploads on the next sync. That's normal, but tell the person.

## Layout

```
panau/
  cli.py          the `panau` command
  launch.py       Steam launch option entry (`panau-launch %command%`)
  unlock.py       earned/always unlock (story finished = activity km07 completed, difficulty 3)
  steam.py        finds Steam, the game, the save folder (config overrides: game_dir, save_dir)
  config.py       %APPDATA%\panau-completionist\config.json
  save/           format.py (sections, section table), world.py (progress table, SAMs), sections.py (per-section
                  best-of-both), merge.py (the full merge), audit.py, progress.py (difficulty, story)
  game/           memory.py (read/write another process), addresses.py (every address + build check),
                  live.py (what is left: save + in-memory table + live markers/pickups)
  overlay.py      arrows (one tiny window per arrow) and the optional radar
  cheats.py       health/ammo
  wingsuit.py     install/remove from a mod zip
  crashfix.py     the 16-byte exe patch
  data/           extracted game data (rebuild: tools/build_data.py)
tools/build_data.py  rebuilds panau/data from the person's install; --check compares with the shipped data
tests/           offline tests (python -m unittest); some use a real save via PANAU_TEST_SAVE
```

## Diagnosing "X isn't showing" / "X shows but is done"

1. Find what the overlay thinks: target label + group id near the camera (`panau.game.live.camera()` gives the camera position; `panau.data.targets()` the list).
2. Compare three things for that group: its world-table entries (`save.world.states()`), its live marker (`Progress.markers()`), and how it looks in the world (ask the person).
3. A wrong arrow on a merged-in object: see trap 5. A missing kind: check `tools/build_data.py`'s objective rules (the `act_*` marker text). A wrong per-type flag: fix `done_flags.json` with evidence from a live destruction, not a guess.
