# Stalley Mod scenarios

A scenario is a public, versioned test fixture for one reproducible Stardew
Valley state. The harness supports scenario discovery, local-save import,
validation, deterministic fixture restore, SMAPI launch/attach, action
recording, deterministic replay, exact observation checkpoints, selected-field
assertions, and regression-suite execution through a local web UI.

## Layout

```text
scenarios/
└── level-up-non-profession/
    ├── save/
    │   ├── SaveGameInfo
    │   └── TestFarm_123
    ├── scenario.json
    ├── actions.jsonl
    └── snapshots/
        └── level-up-menu.json
```

Only `scenario.json` and the two save files are required. `actions.jsonl`,
`snapshots/`, and `assertions.json` are created by the UI as the scenario
becomes a reproducible test.

## `scenario.json`

```json
{
  "$schema": "../scenario.schema.json",
  "formatVersion": 1,
  "id": "level-up-non-profession",
  "name": "Ordinary level-up requiring explicit OK",
  "description": "Starts before sleeping into a non-profession farming level-up.",
  "fixture": {
    "saveFile": "TestFarm_123"
  },
  "observation": {
    "surroundingsSize": -1
  },
  "expectedStart": {
    "season": "spring",
    "day": 2,
    "location": "FarmHouse"
  }
}
```

The directory name must equal `id`. `fixture.saveFile` is the main save XML
filename in `save/`; it may not contain a path separator or equal
`SaveGameInfo`. Its filename must end in the save's
`_<uniqueIDForThisGame>` value. The filename prefix is Stardew's save/player
label and may differ from the farm name; `SaveGameInfo` must contain the same
farm name as the main save. Both files must be well-formed XML.
`observation.surroundingsSize` is passed unchanged to `observe_v2_light`; `-1`
means the full visible viewport.

`expectedStart` remains descriptive fixture metadata. Executable regression
checks belong in `assertions.json`.

The machine-readable contract is
[`scenario.schema.json`](scenario.schema.json). The runtime validator rejects
unknown fields so misspellings fail early.

## Recording and replay

Press **Start** to restore and load the fixture. Press **Record**, then issue a
normal mod method in the Action panel. Arguments are positional strings, for
example `move_step` with `["up"]` or `choose_option` with
`["0", "0", "down"]`.

Each issued command is appended to `actions.jsonl` with its raw and parsed
result, elapsed time, timestamp, and error. The same percent-delimited mod
interface is used during recording and replay. The public line contract is
[`action.schema.json`](action.schema.json).

**Run all** replays from the current cursor; **Pause** stops between actions,
**Resume** continues, and **Step** executes exactly one action. Use **Reset**
before replaying again from the original fixture. **Re-record here** truncates
the selected action and everything after it, then resumes recording from that
point.

## Observation checkpoints

Press **Snapshot** or <kbd>⌘/Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd> while the
web UI is focused. The harness immediately fetches `observe_v2_light` and holds
the exact raw response while you name it. Saving creates
`snapshots/<name>.json` without reformatting or overwriting an existing
checkpoint.

The **Game preview** tab separately fetches `observe_v2`, validates its raw RGBA
payload against `MetaData.ViewportSize`, and renders it in a canvas. Screenshot
bytes are intentionally excluded from normal run polling and persisted
observation snapshots.

## Assertions and suites

Assertions use JSON Pointer paths against the latest observation or a replayed
action result. Supported operators are `equals`, `notEquals`, `contains`,
`exists`, and `notExists`. Action assertions also identify a zero-based
`actionIndex`. The public file contract is
[`assertions.schema.json`](assertions.schema.json).

The **Regression suite** control runs selected scenarios sequentially. Each
scenario restores its fixture, loads Stardew, replays all recorded actions, and
evaluates its assertions. Failed scenarios remain available for graphical
inspection and debugger attach runs.

Deleting a scenario moves it to `scenarios/.trash/` with a timestamp rather
than permanently erasing it. Snapshot deletion is permanent and requires a
confirmation in the UI.

## Fixture restore behavior

For port `6000`, a fixture whose main file is `TestFarm_123` is copied to a
deterministic runtime identity such as:

```text
<Stardew saves>/TestFarm_<deterministic-runtime-id>/
├── .stalleymod-harness.json
├── SaveGameInfo
└── TestFarm_<deterministic-runtime-id>
```

The exact numeric ID is derived from the scenario, original save ID, and port.
The copied XML's `uniqueIDForThisGame` is rewritten to the same ID without
reserializing the rest of the XML. This preserves namespace declarations and
other save details exactly while keeping Stardew's later save destination
inside the harness-owned runtime folder instead of the fixture's original
canonical folder.

The source fixture is never edited. Every prepare or run copies it again, so
changes made by the previous game session are discarded. Resets are serialized
with a per-runtime lock and replace only a folder whose regular ownership marker
matches the scenario and runtime identity. An unmarked collision, symlinked
marker, or concurrent reset causes the command to stop without deleting that
folder.

If a process crashes and leaves a `.stalleymod.lock` file, first confirm no
harness process is using that runtime identity, then remove only that specific
lock file before retrying.

`--observation-output` also refuses an existing path rather than truncating it.
If a newly launched SMAPI process fails before the scenario is ready, the CLI
terminates that process. Attach mode verifies that the requested port accepts a
connection before restoring the fixture.

The default save directory is `%APPDATA%/StardewValley/Saves` on Windows and
`~/.config/StardewValley/Saves` on macOS/Linux. Override it with `--saves-dir`
for testing or nonstandard installations.

## Creating the first level-up fixture

1. Create or play a save to the moment immediately before the reproducible
   level-up sequence.
2. Run `uv run python -m harness ui`.
3. Select **Import a save fixture**, choose the save, and name the scenario.
4. Ensure the copied save XML contains
   `<pauseWhenOutOfFocus>false</pauseWhenOutOfFocus>` so loading it does not
   freeze an unfocused debug session.
5. Select the new scenario and press **Start**.
6. Press **Record**, issue the actions that reach the level-up, and mark the
   important observations as snapshots.
7. Press **Reset**, then **Run all** to confirm the sequence is reproducible.

Do not add a personal save without reviewing it for player names and other
data you do not intend to publish.
