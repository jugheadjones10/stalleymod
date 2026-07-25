from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import datetime
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any

from .scenario import Scenario, ScenarioError, load_scenario
from .records import RecordError, load_assertions, load_checkpoints


_SAVE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}\Z")
_SCENARIO_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class ScenarioCatalogError(RuntimeError):
    """Raised when a scenario cannot be discovered or imported."""


def _xml_child_text(root: element_tree.Element, name: str) -> str | None:
    return next(
        (
            child.text
            for child in root.iter()
            if child.tag.rsplit("}", maxsplit=1)[-1] == name
        ),
        None,
    )


def discover_saves(saves_dir: str | Path) -> list[dict[str, object]]:
    root = Path(saves_dir).expanduser()
    if not root.is_dir():
        return []

    saves: list[dict[str, object]] = []
    for directory in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if directory.is_symlink() or not directory.is_dir():
            continue
        if (directory / ".stalleymod-harness.json").exists():
            continue
        main_save = directory / directory.name
        info = directory / "SaveGameInfo"
        if (
            not _SAVE_NAME.fullmatch(directory.name)
            or not main_save.is_file()
            or main_save.is_symlink()
            or not info.is_file()
            or info.is_symlink()
        ):
            continue
        try:
            save_root = element_tree.parse(main_save).getroot()
            farm_name = _xml_child_text(save_root, "farmName")
            unique_id_text = _xml_child_text(save_root, "uniqueIDForThisGame")
            unique_id = int(unique_id_text or "")
        except (OSError, ValueError, element_tree.ParseError):
            continue
        save_prefix, separator, save_id = directory.name.rpartition("_")
        if (
            not separator
            or not save_prefix
            or save_id != str(unique_id)
            or unique_id <= 0
        ):
            continue
        saves.append(
            {
                "name": directory.name,
                "farmName": farm_name,
                "uniqueId": unique_id,
            }
        )
    return saves


def _scenario_summary(scenario: Scenario) -> dict[str, Any]:
    actions_path = scenario.path / "actions.jsonl"
    snapshots_dir = scenario.path / "snapshots"
    action_count = 0
    if actions_path.is_file():
        with actions_path.open(encoding="utf-8") as actions:
            action_count = sum(1 for line in actions if line.strip())
    snapshot_count = (
        sum(1 for path in snapshots_dir.glob("*.json") if path.is_file())
        if snapshots_dir.is_dir()
        else 0
    )
    return {
        "id": scenario.id,
        "name": scenario.name,
        "description": scenario.description,
        "farmName": scenario.farm_name,
        "saveFile": scenario.save_file,
        "actionCount": action_count,
        "snapshotCount": snapshot_count,
    }


def scenario_details(scenario: Scenario) -> dict[str, Any]:
    details = _scenario_summary(scenario)
    actions: list[dict[str, Any]] = []
    actions_path = scenario.path / "actions.jsonl"
    if actions_path.is_file():
        with actions_path.open(encoding="utf-8") as action_file:
            for index, line in enumerate(action_file, start=1):
                if not line.strip():
                    continue
                try:
                    action = json.loads(line)
                    if not isinstance(action, dict):
                        raise ValueError("action must be a JSON object")
                    actions.append(action)
                except (json.JSONDecodeError, ValueError) as error:
                    actions.append({"line": index, "error": str(error)})

    snapshots: list[dict[str, Any]] = []
    try:
        checkpoints = load_checkpoints(scenario.path)
    except RecordError:
        checkpoints = {}
    snapshots_dir = scenario.path / "snapshots"
    if snapshots_dir.is_dir():
        for path in sorted(snapshots_dir.glob("*.json"), key=lambda item: item.name):
            try:
                observation = json.loads(path.read_text(encoding="utf-8"))
                snapshots.append(
                    {
                        "name": path.stem,
                        "observation": observation,
                        **checkpoints.get(path.stem, {}),
                    }
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                snapshots.append({"name": path.stem, "error": str(error)})

    details.update(
        {
            "expectedStart": scenario.expected_start,
            "surroundingsSize": scenario.surroundings_size,
            "actions": actions,
            "snapshots": snapshots,
            "assertions": [],
            "assertionsError": None,
        }
    )
    try:
        details["assertions"] = load_assertions(scenario.path)
    except RecordError as error:
        details["assertionsError"] = str(error)
    return details


def list_scenarios(scenarios_dir: str | Path) -> dict[str, list[dict[str, Any]]]:
    root = Path(scenarios_dir).expanduser()
    if not root.exists():
        return {"scenarios": [], "errors": []}
    if not root.is_dir():
        raise ScenarioCatalogError(f"scenario path is not a directory: {root}")

    scenarios: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir() or not (path / "scenario.json").is_file():
            continue
        try:
            scenarios.append(_scenario_summary(load_scenario(path)))
        except (OSError, ScenarioError) as error:
            errors.append({"id": path.name, "error": str(error)})
    return {"scenarios": scenarios, "errors": errors}


def import_save_as_scenario(
    *,
    saves_dir: str | Path,
    scenarios_dir: str | Path,
    save_name: str,
    scenario_id: str,
    name: str,
    description: str = "",
) -> Scenario:
    if not _SAVE_NAME.fullmatch(save_name):
        raise ScenarioCatalogError("save name is invalid")
    if not _SCENARIO_ID.fullmatch(scenario_id):
        raise ScenarioCatalogError("scenario id must use lowercase kebab-case")
    if not isinstance(name, str) or not name.strip():
        raise ScenarioCatalogError("scenario name is required")
    if len(name.strip()) > 120:
        raise ScenarioCatalogError("scenario name must be 120 characters or fewer")
    if not isinstance(description, str):
        raise ScenarioCatalogError("scenario description must be a string")
    if len(description) > 2000:
        raise ScenarioCatalogError(
            "scenario description must be 2000 characters or fewer"
        )

    source = Path(saves_dir).expanduser().resolve() / save_name
    saves_root = Path(saves_dir).expanduser().resolve()
    if source.parent != saves_root or source.is_symlink() or not source.is_dir():
        raise ScenarioCatalogError(f"save not found: {save_name}")
    if not any(item["name"] == save_name for item in discover_saves(saves_root)):
        raise ScenarioCatalogError(f"save is not a valid Stardew fixture: {save_name}")

    root = Path(scenarios_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / scenario_id
    if destination.exists():
        raise ScenarioCatalogError(f"scenario already exists: {scenario_id}")

    with tempfile.TemporaryDirectory(prefix=".stalleymod-import-", dir=root) as temporary:
        candidate = Path(temporary) / scenario_id
        fixture = candidate / "save"
        fixture.mkdir(parents=True)
        for child in source.iterdir():
            if child.is_symlink() or not child.is_file():
                raise ScenarioCatalogError(
                    f"save contains a non-regular file: {child.name}"
                )
            shutil.copy2(child, fixture / child.name, follow_symlinks=False)
        metadata = {
            "$schema": "../scenario.schema.json",
            "formatVersion": 1,
            "id": scenario_id,
            "name": name.strip(),
            "description": description.strip(),
            "fixture": {"saveFile": save_name},
            "observation": {"surroundingsSize": -1},
            "expectedStart": {},
        }
        (candidate / "scenario.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        scenario = load_scenario(candidate)
        try:
            candidate.rename(destination)
        except FileExistsError as error:
            raise ScenarioCatalogError(
                f"scenario already exists: {scenario_id}"
            ) from error

    return load_scenario(destination)


def delete_scenario(scenarios_dir: str | Path, scenario_id: str) -> Path:
    if not isinstance(scenario_id, str) or not _SCENARIO_ID.fullmatch(scenario_id):
        raise ScenarioCatalogError("scenario id is invalid")
    root = Path(scenarios_dir).expanduser().resolve()
    source = (root / scenario_id).resolve()
    if source.parent != root or source.is_symlink() or not source.is_dir():
        raise ScenarioCatalogError(f"scenario not found: {scenario_id}")
    try:
        load_scenario(source)
    except (OSError, ScenarioError) as error:
        raise ScenarioCatalogError(f"scenario not found: {scenario_id}") from error

    trash = root / ".trash"
    if trash.is_symlink() or (trash.exists() and not trash.is_dir()):
        raise ScenarioCatalogError("scenario trash path is not a regular directory")
    trash.mkdir(exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    destination = trash / f"{scenario_id}-{timestamp}"
    try:
        source.rename(destination)
    except OSError as error:
        raise ScenarioCatalogError(f"could not delete scenario: {error}") from error
    return destination
