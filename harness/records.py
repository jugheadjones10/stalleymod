from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable


_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_ACTION = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_OPERATORS = {"equals", "notEquals", "exists", "notExists", "contains"}
_MISSING = object()


class RecordError(ValueError):
    """Raised when recorded scenario data is invalid or cannot be persisted."""


def _scenario_path(path: str | Path) -> Path:
    scenario = Path(path).resolve()
    if not scenario.is_dir():
        raise RecordError(f"scenario directory not found: {scenario}")
    return scenario


def _validate_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value) or len(value) > 80:
        raise RecordError(f"{label} must use lowercase kebab-case")
    return value


def validate_action(action: Any, *, line: int | None = None) -> dict[str, Any]:
    prefix = f"actions.jsonl line {line}: " if line is not None else ""
    if not isinstance(action, dict):
        raise RecordError(f"{prefix}action record must be a JSON object")
    command = action.get("action")
    arguments = action.get("arguments", [])
    if not isinstance(command, str) or not _ACTION.fullmatch(command):
        raise RecordError(f"{prefix}action must be a valid mod method name")
    if not isinstance(arguments, list) or any(
        not isinstance(argument, str) for argument in arguments
    ):
        raise RecordError(f"{prefix}arguments must be an array of strings")
    if len(arguments) > 32:
        raise RecordError(f"{prefix}arguments may contain at most 32 strings")
    encoded = "%".join([command, *arguments]).encode("utf-8")
    if any("%" in argument or "\n" in argument or "\r" in argument or "\0" in argument for argument in arguments):
        raise RecordError(f"{prefix}arguments may not contain %, newlines, or NUL bytes")
    if len(encoded) > 255:
        raise RecordError(f"{prefix}command exceeds the mod's 255-byte protocol limit")
    return dict(action, action=command, arguments=list(arguments))


def load_actions(path: str | Path) -> list[dict[str, Any]]:
    scenario = _scenario_path(path)
    actions_path = scenario / "actions.jsonl"
    if not actions_path.exists():
        return []
    actions: list[dict[str, Any]] = []
    try:
        with actions_path.open(encoding="utf-8") as action_file:
            for line_number, line in enumerate(action_file, start=1):
                if not line.strip():
                    continue
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError as error:
                    raise RecordError(
                        f"actions.jsonl line {line_number}: invalid JSON"
                    ) from error
                actions.append(validate_action(decoded, line=line_number))
    except (OSError, UnicodeError) as error:
        raise RecordError(f"could not read actions.jsonl: {error}") from error
    return actions


def append_action(path: str | Path, action: dict[str, Any]) -> dict[str, Any]:
    scenario = _scenario_path(path)
    validated = validate_action(action)
    payload = json.dumps(validated, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        with (scenario / "actions.jsonl").open("a", encoding="utf-8") as action_file:
            action_file.write(payload)
            action_file.flush()
            os.fsync(action_file.fileno())
    except OSError as error:
        raise RecordError(f"could not append actions.jsonl: {error}") from error
    return validated


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def truncate_actions(path: str | Path, count: int) -> None:
    scenario = _scenario_path(path)
    actions = load_actions(scenario)
    if type(count) is not int or not 0 <= count <= len(actions):
        raise RecordError(f"action count must be between 0 and {len(actions)}")
    payload = "".join(
        json.dumps(action, ensure_ascii=False, separators=(",", ":")) + "\n"
        for action in actions[:count]
    )
    try:
        _atomic_write(scenario / "actions.jsonl", payload)
    except OSError as error:
        raise RecordError(f"could not rewrite actions.jsonl: {error}") from error


def _load_checkpoints(scenario: Path) -> dict[str, dict[str, Any]]:
    path = scenario / "checkpoints.json"
    if not path.exists():
        return {}
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RecordError(f"checkpoints.json is not valid UTF-8 JSON: {error}") from error
    if not isinstance(decoded, dict):
        raise RecordError("checkpoints.json must contain a JSON object")
    return {
        name: metadata
        for name, metadata in decoded.items()
        if isinstance(name, str) and isinstance(metadata, dict)
    }


def load_checkpoints(path: str | Path) -> dict[str, dict[str, Any]]:
    return _load_checkpoints(_scenario_path(path))


def save_snapshot(
    path: str | Path,
    name: str,
    raw_observation: str,
    *,
    captured_at: str | None = None,
    after_action: int | None = None,
) -> Path:
    scenario = _scenario_path(path)
    snapshot_name = _validate_name(name, "snapshot name")
    if not isinstance(raw_observation, str):
        raise RecordError("observation must be a JSON string")
    try:
        decoded = json.loads(raw_observation)
    except json.JSONDecodeError as error:
        raise RecordError("observation must contain valid JSON") from error
    if not isinstance(decoded, dict):
        raise RecordError("observation root must be a JSON object")

    snapshots = scenario / "snapshots"
    snapshots.mkdir(exist_ok=True)
    destination = snapshots / f"{snapshot_name}.json"
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as error:
        raise RecordError(f"snapshot already exists: {snapshot_name}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(raw_observation)
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise RecordError(f"could not save snapshot: {error}") from error
    if captured_at is not None or after_action is not None:
        checkpoints = _load_checkpoints(scenario)
        checkpoints[snapshot_name] = {
            "capturedAt": captured_at,
            "afterAction": after_action,
        }
        try:
            _atomic_write(
                scenario / "checkpoints.json",
                json.dumps(checkpoints, ensure_ascii=False, indent=2) + "\n",
            )
        except OSError as error:
            destination.unlink(missing_ok=True)
            raise RecordError(f"could not update checkpoints.json: {error}") from error
    return destination


def delete_snapshot(path: str | Path, name: str) -> None:
    scenario = _scenario_path(path)
    snapshot_name = _validate_name(name, "snapshot name")
    destination = scenario / "snapshots" / f"{snapshot_name}.json"
    try:
        destination.unlink()
    except FileNotFoundError as error:
        raise RecordError(f"snapshot not found: {snapshot_name}") from error
    except OSError as error:
        raise RecordError(f"could not delete snapshot: {error}") from error
    checkpoints = _load_checkpoints(scenario)
    if snapshot_name in checkpoints:
        del checkpoints[snapshot_name]
        try:
            _atomic_write(
                scenario / "checkpoints.json",
                json.dumps(checkpoints, ensure_ascii=False, indent=2) + "\n",
            )
        except OSError as error:
            raise RecordError(f"could not update checkpoints.json: {error}") from error


def _validate_assertion(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RecordError("each assertion must be a JSON object")
    unknown = set(value) - {
        "id",
        "source",
        "actionIndex",
        "path",
        "operator",
        "expected",
    }
    if unknown:
        raise RecordError(f"unknown assertion field(s): {', '.join(sorted(unknown))}")
    assertion_id = _validate_name(value.get("id"), "assertion id")
    source = value.get("source")
    if source not in {"observation", "action"}:
        raise RecordError(f"assertion {assertion_id}: source must be observation or action")
    path = value.get("path")
    if not isinstance(path, str) or (path and not path.startswith("/")):
        raise RecordError(f"assertion {assertion_id}: path must be a JSON Pointer")
    operator = value.get("operator")
    if operator not in _OPERATORS:
        raise RecordError(
            f"assertion {assertion_id}: operator must be one of {', '.join(sorted(_OPERATORS))}"
        )
    action_index = value.get("actionIndex")
    if source == "action" and (type(action_index) is not int or action_index < 0):
        raise RecordError(
            f"assertion {assertion_id}: actionIndex must be a non-negative integer"
        )
    if source == "observation" and action_index is not None:
        raise RecordError(f"assertion {assertion_id}: actionIndex is only valid for actions")
    if operator not in {"exists", "notExists"} and "expected" not in value:
        raise RecordError(f"assertion {assertion_id}: expected is required")
    try:
        json.dumps(value.get("expected"))
    except (TypeError, ValueError) as error:
        raise RecordError(f"assertion {assertion_id}: expected must be JSON") from error
    return dict(value)


def load_assertions(path: str | Path) -> list[dict[str, Any]]:
    scenario = _scenario_path(path)
    assertions_path = scenario / "assertions.json"
    if not assertions_path.exists():
        return []
    try:
        decoded = json.loads(assertions_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RecordError(f"assertions.json is not valid UTF-8 JSON: {error}") from error
    if not isinstance(decoded, list):
        raise RecordError("assertions.json must contain an array")
    assertions = [_validate_assertion(value) for value in decoded]
    ids = [assertion["id"] for assertion in assertions]
    if len(ids) != len(set(ids)):
        raise RecordError("assertion ids must be unique")
    return assertions


def replace_assertions(path: str | Path, assertions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    scenario = _scenario_path(path)
    values = list(assertions)
    if len(values) > 500:
        raise RecordError("a scenario may contain at most 500 assertions")
    validated = [_validate_assertion(value) for value in values]
    ids = [assertion["id"] for assertion in validated]
    if len(ids) != len(set(ids)):
        raise RecordError("assertion ids must be unique")
    try:
        _atomic_write(
            scenario / "assertions.json",
            json.dumps(validated, ensure_ascii=False, indent=2) + "\n",
        )
    except OSError as error:
        raise RecordError(f"could not write assertions.json: {error}") from error
    return validated


def _resolve_pointer(value: Any, pointer: str) -> Any:
    current = value
    if pointer == "":
        return current
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return _MISSING
            if index < 0 or index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def evaluate_assertions(
    assertions: Iterable[dict[str, Any]],
    *,
    observation: dict[str, Any] | None,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for raw_assertion in assertions:
        assertion = _validate_assertion(raw_assertion)
        if assertion["source"] == "observation":
            root: Any = observation if observation is not None else _MISSING
        else:
            index = assertion["actionIndex"]
            root = actions[index] if index < len(actions) else _MISSING
        actual = (
            _resolve_pointer(root, assertion["path"])
            if root is not _MISSING
            else _MISSING
        )
        operator = assertion["operator"]
        expected = assertion.get("expected")
        if operator == "exists":
            passed = actual is not _MISSING
        elif operator == "notExists":
            passed = actual is _MISSING
        elif operator == "equals":
            passed = actual is not _MISSING and actual == expected
        elif operator == "notEquals":
            passed = actual is not _MISSING and actual != expected
        else:
            try:
                passed = actual is not _MISSING and (
                    isinstance(actual, (list, str, dict)) and expected in actual
                )
            except TypeError:
                passed = False
        result = dict(assertion, passed=passed)
        result["actual"] = None if actual is _MISSING else actual
        if actual is _MISSING:
            result["missing"] = True
        results.append(result)
    passed_count = sum(1 for result in results if result["passed"])
    return {
        "passed": passed_count == len(results),
        "total": len(results),
        "passedCount": passed_count,
        "failedCount": len(results) - passed_count,
        "results": results,
    }
