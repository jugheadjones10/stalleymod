from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Sequence

from .fixture import FixtureRestoreError, restore_fixture
from .rpc import ModConnectionError, ModClient, ModProtocolError
from .runtime import (
    HarnessRuntimeError,
    default_saves_dir,
    ensure_port_available,
    launch_smapi,
    resolve_smapi_path,
    terminate_launched_process,
)
from .scenario import ScenarioError, load_scenario
from .server import serve_ui


_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


def _sample_rate(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 100:
        raise argparse.ArgumentTypeError("must be between 1 and 100")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m harness",
        description="Fixture-driven testing and debugging harness for Stalley Mod.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list valid scenarios")
    list_parser.add_argument(
        "--scenarios-dir",
        type=Path,
        default=_REPOSITORY_ROOT / "scenarios",
    )

    validate_parser = subparsers.add_parser("validate", help="validate one scenario")
    validate_parser.add_argument("scenario", type=Path)

    ui_parser = subparsers.add_parser("ui", help="open the local scenario harness UI")
    ui_parser.add_argument("--port", type=_port, default=8765)
    ui_parser.add_argument(
        "--scenarios-dir",
        type=Path,
        default=_REPOSITORY_ROOT / "scenarios",
    )
    ui_parser.add_argument("--saves-dir", type=Path)
    ui_parser.add_argument("--smapi-path", type=Path)
    ui_parser.add_argument(
        "--runs-dir",
        type=Path,
    )
    ui_parser.add_argument("--no-open", action="store_true")

    for command in ("prepare", "run"):
        command_parser = subparsers.add_parser(
            command,
            help=(
                "restore a scenario fixture"
                if command == "prepare"
                else "restore and load a scenario in Stardew"
            ),
        )
        command_parser.add_argument("scenario", type=Path)
        command_parser.add_argument("--port", type=_port, default=10783)
        command_parser.add_argument("--saves-dir", type=Path)

    run_parser = subparsers.choices["run"]
    run_parser.add_argument("--attach", action="store_true")
    run_parser.add_argument("--smapi-path", type=Path)
    run_parser.add_argument("--sample-rate", type=_sample_rate, default=100)
    run_parser.add_argument("--timeout", type=_positive_float, default=90)
    run_parser.add_argument("--observation-output", type=Path)
    return parser


def _result(data: dict[str, object]) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _saves_dir(configured: Path | None) -> Path:
    return configured if configured is not None else default_saves_dir()


def _list_scenarios(directory: Path) -> int:
    if not directory.is_dir():
        raise ScenarioError(f"scenario directory not found: {directory}")
    scenarios = [
        load_scenario(path)
        for path in sorted(directory.iterdir(), key=lambda item: item.name)
        if path.is_dir() and (path / "scenario.json").is_file()
    ]
    _result(
        {
            "scenarios": [
                {"id": scenario.id, "name": scenario.name, "path": str(scenario.path)}
                for scenario in scenarios
            ]
        }
    )
    return 0


def _observation_output_path(configured: Path | None) -> Path | None:
    if configured is None:
        return None
    path = configured.expanduser().absolute()
    if os.path.lexists(path):
        raise HarnessRuntimeError(
            f"observation output already exists; refusing to overwrite it: {path}"
        )
    return path


def _write_new_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as error:
        raise HarnessRuntimeError(
            f"observation output already exists; refusing to overwrite it: {path}"
        ) from error
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ModConnectionError("scenario run timed out")
    return remaining


def _prepare(args: argparse.Namespace) -> tuple[object, object]:
    scenario = load_scenario(args.scenario)
    restored = restore_fixture(scenario, _saves_dir(args.saves_dir), port=args.port)
    return scenario, restored


def _run(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    observation_path = _observation_output_path(args.observation_output)
    client = ModClient(port=args.port, command_timeout=args.timeout)
    process = None
    if args.attach:
        client.wait_for_server(timeout=args.timeout)
        client.send("observe_v2_light%-1", timeout=args.timeout)
    else:
        executable = resolve_smapi_path(args.smapi_path)
        ensure_port_available(args.port)

    restored = restore_fixture(
        scenario,
        _saves_dir(args.saves_dir),
        port=args.port,
    )
    try:
        if not args.attach:
            process = launch_smapi(
                executable,
                port=args.port,
                sample_rate=args.sample_rate,
            )

        deadline = time.monotonic() + args.timeout
        if not args.attach:
            client.wait_for_server(timeout=_remaining(deadline))
        raw_observation = client.load_fixture_until_ready(
            restored.runtime_save_name,
            surroundings_size=scenario.surroundings_size,
            timeout=_remaining(deadline),
        )
        if observation_path is not None:
            _write_new_file(observation_path, raw_observation.encode("utf-8"))
    except BaseException:
        if process is not None:
            terminate_launched_process(process)
        raise

    _result(
        {
            "scenarioId": scenario.id,
            "runtimeSaveName": restored.runtime_save_name,
            "port": args.port,
            "attached": args.attach,
            "pid": process.pid if process is not None else None,
            "observationOutput": (
                str(observation_path) if observation_path is not None else None
            ),
        }
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return _list_scenarios(args.scenarios_dir)
        if args.command == "validate":
            scenario = load_scenario(args.scenario)
            _result({"scenarioId": scenario.id, "valid": True})
            return 0
        if args.command == "ui":
            options = {
                "host": "127.0.0.1",
                "port": args.port,
                "scenarios_dir": args.scenarios_dir,
                "saves_dir": _saves_dir(args.saves_dir),
                "smapi_path": args.smapi_path,
                "open_browser": not args.no_open,
            }
            if args.runs_dir is not None:
                options["runs_dir"] = args.runs_dir
            serve_ui(**options)
            return 0
        if args.command == "prepare":
            scenario, restored = _prepare(args)
            _result(
                {
                    "scenarioId": scenario.id,
                    "runtimeSaveName": restored.runtime_save_name,
                    "path": str(restored.path),
                }
            )
            return 0
        if args.command == "run":
            return _run(args)
        parser.error(f"unknown command: {args.command}")
    except ScenarioError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (
        FixtureRestoreError,
        HarnessRuntimeError,
        ModConnectionError,
        ModProtocolError,
        OSError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 2
