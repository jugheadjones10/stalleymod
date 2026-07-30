from __future__ import annotations

import ast
import hashlib
import json
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class DebugArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class DebugCheckpoint:
    id: str
    path: Path
    save_name: str
    observation: dict[str, Any]
    position: tuple[float, float]
    facing_direction: int


@dataclass(frozen=True)
class TaskStartFallback:
    task: str
    save_type: str
    save_dir: Path
    save_name: str
    init_commands: list[str]


@dataclass(frozen=True)
class DebugTarget:
    run_id: str
    event_sequence: int
    function: str
    runtime_function: str
    source: str
    program: str
    source_start_line: int
    checkpoint: DebugCheckpoint | None
    task_start: TaskStartFallback | None = None

    def as_dict(self) -> dict[str, Any]:
        mode = "checkpoint" if self.checkpoint else "task-start" if self.task_start else "source-only"
        return {
            "runId": self.run_id,
            "eventSequence": self.event_sequence,
            "function": self.function,
            "source": self.source,
            "sourceStartLine": self.source_start_line,
            "checkpoint": (
                {
                    "id": self.checkpoint.id,
                    "observation": self.checkpoint.observation,
                }
                if self.checkpoint
                else None
            ),
            "taskStart": (
                {
                    "task": self.task_start.task,
                    "saveType": self.task_start.save_type,
                    "initCommandCount": len(self.task_start.init_commands),
                }
                if self.task_start
                else None
            ),
            "mode": mode,
        }


def _child(root: Path, name: str) -> Path:
    if not name or Path(name).name != name:
        raise DebugArtifactError("invalid run or checkpoint id")
    path = (root / name).resolve()
    if path.parent != root or not path.is_dir():
        raise DebugArtifactError(f"debug artifact not found: {name}")
    return path


def _events(run_dir: Path) -> list[dict[str, Any]]:
    events = []
    try:
        lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DebugArtifactError("run event log was not found") from error
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _definitions(source: str) -> list[tuple[str, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise DebugArtifactError(f"recorded Python source is invalid: {error}") from error
    return [
        (node.name, ast.get_source_segment(source, node) or "")
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _program_at(events: list[dict[str, Any]], sequence: int) -> str:
    definitions: dict[str, str] = {}
    for event in events:
        if int(event.get("sequence", -1)) > sequence:
            break
        source = event.get("source")
        if not isinstance(source, str):
            continue
        for name, definition in _definitions(source):
            definitions[name] = definition
    if not definitions:
        raise DebugArtifactError("no complete Python function exists at this event")
    return "\n\n".join(definitions.values())


def _function(program: str, requested: str) -> tuple[str, str, int]:
    candidates = [requested]
    if not requested.startswith("__implementation_"):
        candidates.insert(0, f"__implementation_{requested}")
    tree = ast.parse(program)
    for candidate in candidates:
        node = next(
            (
                item
                for item in tree.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == candidate
            ),
            None,
        )
        if node is not None:
            return (
                candidate,
                ast.get_source_segment(program, node) or "",
                node.lineno,
            )
    raise DebugArtifactError(f"function is not implemented at this event: {requested}")


def _load_checkpoint(run_dir: Path, metadata: dict[str, Any]) -> DebugCheckpoint:
    checkpoint_id = metadata.get("id")
    if not isinstance(checkpoint_id, str):
        raise DebugArtifactError("checkpoint metadata has no id")
    path = _child((run_dir / "checkpoints").resolve(), checkpoint_id)
    try:
        stored = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        observation = json.loads((path / "observation.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DebugArtifactError("checkpoint metadata is incomplete") from error
    save_name = stored.get("save_name")
    if not isinstance(save_name, str) or Path(save_name).name != save_name:
        raise DebugArtifactError("checkpoint has no valid save name")
    save_path = (path / "save").resolve()
    if save_path.parent != path or not save_path.is_dir():
        raise DebugArtifactError("checkpoint save is missing")
    try:
        save_root = element_tree.parse(save_path / save_name).getroot()
        player = save_root.find("player")
        position = player.find("Position")
        saved_position = (
            float(position.findtext("X")),
            float(position.findtext("Y")),
        )
        facing_direction = int(player.findtext("FacingDirection"))
    except (AttributeError, OSError, TypeError, ValueError, element_tree.ParseError) as error:
        raise DebugArtifactError("checkpoint player position is missing") from error
    return DebugCheckpoint(
        id=checkpoint_id,
        path=path,
        save_name=save_name,
        observation=observation if isinstance(observation, dict) else {},
        position=saved_position,
        facing_direction=facing_direction,
    )


def _task_start(root: Path, run_dir: Path) -> TaskStartFallback | None:
    try:
        status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    task = status.get("task") if isinstance(status, dict) else None
    if not isinstance(task, str):
        return None
    task_type, separator, task_id_text = task.rpartition(" ")
    if (
        not separator
        or not task_type.replace("_", "").replace("-", "").isalnum()
        or not task_id_text.isdigit()
    ):
        return None

    stalley_root = root.parent
    suite_root = (stalley_root / "tasks" / "task_suite").resolve()
    suite_path = (suite_root / f"{task_type}.yaml").resolve()
    if suite_path.parent != suite_root or not suite_path.is_file():
        return None
    try:
        suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise DebugArtifactError(f"task configuration is invalid: {error}") from error
    tasks = list(suite.values()) if isinstance(suite, dict) else []
    task_id = int(task_id_text)
    if task_id >= len(tasks) or not isinstance(tasks[task_id], dict):
        raise DebugArtifactError(f"task configuration was not found: {task}")
    configuration = tasks[task_id]

    save_type = configuration.get("save_type")
    commands = configuration.get("init_commands")
    if not isinstance(save_type, str) or Path(save_type).name != save_type:
        raise DebugArtifactError(f"task has no valid save type: {task}")
    if commands is None:
        commands = []
    if not isinstance(commands, list) or not all(
        isinstance(command, str) for command in commands
    ):
        raise DebugArtifactError(f"task has invalid init commands: {task}")

    saves_root = (stalley_root / "tasks" / "saves").resolve()
    save_type_dir = (saves_root / save_type).resolve()
    if save_type_dir.parent != saves_root or not save_type_dir.is_dir():
        raise DebugArtifactError(f"task save template was not found: {save_type}")
    profiles = [
        path
        for path in save_type_dir.iterdir()
        if path.is_dir() and not path.is_symlink()
    ]
    if len(profiles) != 1:
        raise DebugArtifactError(
            f"task save template must contain one save: {save_type}"
        )
    save_dir = profiles[0].resolve()
    save_name = save_dir.name
    if not (save_dir / save_name).is_file():
        raise DebugArtifactError(f"task save file was not found: {save_name}")
    return TaskStartFallback(
        task=task,
        save_type=save_type,
        save_dir=save_dir,
        save_name=save_name,
        init_commands=commands,
    )


def load_debug_target(
    runs_dir: str | Path,
    run_id: str,
    event_sequence: int,
    function: str,
) -> DebugTarget:
    root = Path(runs_dir).expanduser().resolve()
    run_dir = _child(root, run_id)
    events = _events(run_dir)
    if not any(int(event.get("sequence", -1)) == event_sequence for event in events):
        raise DebugArtifactError("event was not found in this run")

    program = _program_at(events, event_sequence)
    runtime_function, source, source_start_line = _function(program, function)
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    checkpoint_metadata = next(
        (
            checkpoint
            for event in events
            for checkpoint in [event.get("checkpoint")]
            if isinstance(checkpoint, dict)
            and checkpoint.get("source_hash") == source_hash
        ),
        None,
    )
    checkpoint = (
        _load_checkpoint(run_dir, checkpoint_metadata)
        if checkpoint_metadata is not None
        else None
    )
    if checkpoint is not None:
        try:
            program = (checkpoint.path / "program.py").read_text(encoding="utf-8")
        except OSError as error:
            raise DebugArtifactError("checkpoint program is missing") from error
        runtime_function, source, source_start_line = _function(program, function)
    task_start = _task_start(root, run_dir) if checkpoint is None else None

    return DebugTarget(
        run_id=run_id,
        event_sequence=event_sequence,
        function=function.removeprefix("__implementation_"),
        runtime_function=runtime_function,
        source=source,
        program=program,
        source_start_line=source_start_line,
        checkpoint=checkpoint,
        task_start=task_start,
    )
