# Staelly Mod

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
