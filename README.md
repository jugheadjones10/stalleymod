# Stalley Mod

The Stardew Valley mod used by StarDojo agents. This repository is also the
home for the fixture recording, replay, observation snapshot, and debugging
harness.

## Build and deploy

Install Stardew Valley and SMAPI, then run:

```bash
dotnet build -c Release
```

`Pathoschild.Stardew.ModBuildConfig` auto-detects the game and copies the
compiled mod into the game's `Mods` directory.

If the game isn't detected, copy `StardojoMod.csproj.user.example` to
`StardojoMod.csproj.user` and set `GamePath`. The `.user` file is ignored
because it contains machine-specific IDE and game settings.

## Scenario harness

Install [uv](https://docs.astral.sh/uv/) and a current Node.js release first.
Start the local harness UI from the repository root:

```bash
uv run python -m harness ui
```

That one command installs the Python dependencies, builds the React UI when
needed, opens `http://127.0.0.1:8765`, and provides the normal workflow:

1. Import a local Stardew save as a scenario fixture.
2. Select the scenario and optionally change the mod port or enable debugger
   attach mode.
3. Start the scenario, enable recording, and issue normal mod actions from the
   Action panel.
4. Mark exact observation checkpoints with **Snapshot** or
   <kbd>⌘/Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd>.
5. Reset and use run-all, pause, resume, or single-step replay controls.
6. Add selected-field assertions and run one scenario or a regression suite.
7. Inspect the live observation, game preview, action results, snapshots,
   assertion failures, and SMAPI logs.

The importer copies the selected save into `scenarios/`; it never edits the
live save. Review imported fixtures for player names or other personal data
before publishing them.

Use `--no-open` if the browser should not open automatically, or `--port` to
change the UI port:

```bash
uv run python -m harness ui --no-open --port 8766
```

The UI follows the `stalley-v2` viewer architecture: a FastAPI backend serves a
React/Vite/Tailwind workspace with a scenario browser, action timeline,
record/replay controls, exact live observations, an on-demand game preview,
checkpoint and assertion inspectors, regression reports, and streaming logs.

### Debug recorded Stalley functions

Start the harness with access to the `stalley-v2` run directory:

```bash
uv run python -m harness ui --runs-dir ../stalley-v2/runs
```

In the Stalley run viewer, open a complete function implementation and choose
**Debug in StalleyMod**. The debugger workspace supports source breakpoints,
pause, continue, single-step, stack and local inspection, observations, and
game previews.

Failed implementations recorded by the current Stalley runtime open with
their exact pre-call save checkpoint. When no checkpoint exists, the debugger
automatically restores the run's task save template and applies its original
`init_commands`. If the task metadata is unavailable, it falls back to the
currently loaded scenario.

For frontend development, run FastAPI and Vite separately:

```bash
uv run python -m harness ui --no-open
cd harness/frontend
npm install
npm run dev
```

Vite opens its development server and proxies `/api` to the harness on port
8765. Production launches build and serve the frontend through FastAPI.

The CLI remains available for automation and headless runs:

```bash
uv run python -m harness list
uv run python -m harness validate scenarios/<scenario-id>
uv run python -m harness prepare scenarios/<scenario-id> --port 6000
uv run python -m harness run scenarios/<scenario-id> --port 6000
```

`run` resolves SMAPI from `--smapi-path`, `STARDEW_APP_PATH`, or the standard
Steam location on macOS. It restores the fixture to a port-scoped save folder,
loads that save through the mod's existing `load_game_record` command, and
polls `observe_v2_light` until the normal agent observation is valid JSON.

Scenario deletion is recoverable: the UI moves the fixture to
`scenarios/.trash/`. Re-recording from a selected step deliberately truncates
that step and later actions, so reset to the correct fixture state before using
it.

For IDE debugging, launch SMAPI under the debugger first and attach the harness
to its port:

```bash
uv run python -m harness run scenarios/<scenario-id> \
  --attach \
  --port 6000 \
  --observation-output /tmp/level-up-observation.json
```

The harness only replaces runtime save folders containing its ownership marker.
It refuses to overwrite an existing unmarked folder. See
[`scenarios/README.md`](scenarios/README.md) for the scenario contract and
fixture workflow.

Run the harness tests with:

```bash
uv run python -m unittest discover -s tests -v
```

## Using this repository through StarDojo

StarDojo includes this repository at `StardojoMod/` as a Git submodule:

```bash
git clone --recurse-submodules <stardojo-repository-url>
```

For an existing StarDojo checkout:

```bash
git submodule update --init --recursive
```

When developing in the submodule, switch to a branch before committing:

```bash
cd StardojoMod
git switch main
```
