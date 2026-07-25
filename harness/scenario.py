from __future__ import annotations

import json
import re
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCENARIO_FORMAT_VERSION = 1
_SCENARIO_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SAVE_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}\Z")
_TOP_LEVEL_FIELDS = {
    "$schema",
    "formatVersion",
    "id",
    "name",
    "description",
    "fixture",
    "observation",
    "expectedStart",
}


class ScenarioError(ValueError):
    """Raised when a scenario does not satisfy the public format contract."""


@dataclass(frozen=True)
class Scenario:
    path: Path
    id: str
    name: str
    description: str
    save_file: str
    farm_name: str
    unique_id: int
    surroundings_size: int
    expected_start: dict[str, Any]

    @property
    def save_dir(self) -> Path:
        return self.path / "save"


def _require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioError(f"{field} must be a JSON object")
    return value


def _require_string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ScenarioError(f"{field} must be a non-empty string")
    return value


def _load_xml(path: Path) -> element_tree.Element:
    if not path.is_file() or path.is_symlink():
        raise ScenarioError(f"required fixture file is missing: {path.name}")
    try:
        return element_tree.parse(path).getroot()
    except (element_tree.ParseError, OSError) as error:
        raise ScenarioError(f"fixture file must contain valid XML: {path.name}") from error


def _child(element: element_tree.Element, name: str) -> element_tree.Element | None:
    return next(
        (
            child
            for child in element
            if child.tag.rsplit("}", maxsplit=1)[-1] == name
        ),
        None,
    )


def _save_identity(
    save_root: element_tree.Element,
    info_root: element_tree.Element,
    save_file: str,
) -> tuple[str, int]:
    if save_root.tag.rsplit("}", maxsplit=1)[-1] != "SaveGame":
        raise ScenarioError("fixture.saveFile must contain a SaveGame XML document")
    if info_root.tag.rsplit("}", maxsplit=1)[-1] != "Farmer":
        raise ScenarioError("SaveGameInfo must contain a Farmer XML document")

    player = _child(save_root, "player")
    farm_name_element = _child(player, "farmName") if player is not None else None
    unique_id_element = _child(save_root, "uniqueIDForThisGame")
    info_farm_name_element = _child(info_root, "farmName")
    farm_name = farm_name_element.text if farm_name_element is not None else None
    info_farm_name = (
        info_farm_name_element.text if info_farm_name_element is not None else None
    )
    unique_id_text = unique_id_element.text if unique_id_element is not None else None

    if not farm_name or not unique_id_text:
        raise ScenarioError(
            "main save must define player.farmName and uniqueIDForThisGame"
        )
    try:
        unique_id = int(unique_id_text)
    except ValueError as error:
        raise ScenarioError("uniqueIDForThisGame must be a positive integer") from error
    if not 1 <= unique_id <= (1 << 63) - 1:
        raise ScenarioError("uniqueIDForThisGame must be a positive 64-bit integer")
    if info_farm_name != farm_name:
        raise ScenarioError("SaveGameInfo farmName must match the main save")
    save_prefix, separator, save_id = save_file.rpartition("_")
    if not separator or not save_prefix or save_id != str(unique_id):
        raise ScenarioError(
            "fixture.saveFile must end with _<uniqueIDForThisGame>"
        )
    return farm_name, unique_id


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path).expanduser()
    metadata_path = scenario_path if scenario_path.name == "scenario.json" else scenario_path / "scenario.json"
    scenario_dir = metadata_path.parent.resolve()

    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ScenarioError(f"scenario metadata not found: {metadata_path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScenarioError(f"scenario metadata is not valid UTF-8 JSON: {metadata_path}") from error

    metadata = _require_object(raw, "scenario")
    unknown_fields = sorted(set(metadata) - _TOP_LEVEL_FIELDS)
    if unknown_fields:
        raise ScenarioError(f"unknown scenario field(s): {', '.join(unknown_fields)}")
    if "$schema" in metadata:
        _require_string(metadata["$schema"], "$schema", allow_empty=True)

    format_version = metadata.get("formatVersion")
    if type(format_version) is not int or format_version != SCENARIO_FORMAT_VERSION:
        raise ScenarioError(
            f"formatVersion must be {SCENARIO_FORMAT_VERSION}; got {format_version!r}"
        )

    scenario_id = _require_string(metadata.get("id"), "id")
    if not _SCENARIO_ID.fullmatch(scenario_id):
        raise ScenarioError("id must use lowercase kebab-case")
    if scenario_dir.name != scenario_id:
        raise ScenarioError(
            f"scenario id {scenario_id!r} must match its directory name {scenario_dir.name!r}"
        )

    name = _require_string(metadata.get("name"), "name")
    description = _require_string(
        metadata.get("description", ""),
        "description",
        allow_empty=True,
    )

    fixture = _require_object(metadata.get("fixture"), "fixture")
    unknown_fixture_fields = sorted(set(fixture) - {"saveFile"})
    if unknown_fixture_fields:
        raise ScenarioError(
            f"unknown fixture field(s): {', '.join(unknown_fixture_fields)}"
        )
    save_file = _require_string(fixture.get("saveFile"), "fixture.saveFile")
    if not _SAVE_FILE.fullmatch(save_file):
        raise ScenarioError(
            "fixture.saveFile may contain only letters, numbers, underscores, and hyphens"
        )
    if save_file == "SaveGameInfo":
        raise ScenarioError("fixture.saveFile and SaveGameInfo must be distinct files")

    observation = _require_object(metadata.get("observation", {}), "observation")
    unknown_observation_fields = sorted(set(observation) - {"surroundingsSize"})
    if unknown_observation_fields:
        raise ScenarioError(
            f"unknown observation field(s): {', '.join(unknown_observation_fields)}"
        )
    surroundings_size = observation.get("surroundingsSize", -1)
    if type(surroundings_size) is not int or surroundings_size < -1:
        raise ScenarioError("observation.surroundingsSize must be an integer of -1 or greater")

    expected_start = _require_object(metadata.get("expectedStart", {}), "expectedStart")
    save_dir = scenario_dir / "save"
    if not save_dir.is_dir() or save_dir.is_symlink():
        raise ScenarioError(f"scenario save fixture directory is missing: {save_dir}")
    for child in save_dir.iterdir():
        if child.is_symlink() or not child.is_file():
            raise ScenarioError(f"save fixtures may contain regular files only: {child.name}")
        if child.name == ".stalleymod-harness.json":
            raise ScenarioError(f"save fixture uses reserved filename: {child.name}")

    info_root = _load_xml(save_dir / "SaveGameInfo")
    save_root = _load_xml(save_dir / save_file)
    farm_name, unique_id = _save_identity(save_root, info_root, save_file)

    return Scenario(
        path=scenario_dir,
        id=scenario_id,
        name=name,
        description=description,
        save_file=save_file,
        farm_name=farm_name,
        unique_id=unique_id,
        surroundings_size=surroundings_size,
        expected_start=expected_start,
    )
