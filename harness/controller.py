from __future__ import annotations

import base64
import json
import math
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .fixture import restore_fixture
from .records import (
    append_action,
    evaluate_assertions,
    load_actions,
    load_assertions,
    save_snapshot,
    truncate_actions,
    validate_action,
)
from .rpc import ModClient
from .runtime import (
    ensure_port_available,
    launch_smapi,
    resolve_smapi_path,
    terminate_launched_process,
)
from .scenario import load_scenario


_ACTIVE_STATUSES = {
    "preparing",
    "launching",
    "connecting",
    "loading",
    "ready",
}


class RunController:
    def __init__(
        self,
        *,
        scenarios_dir: str | Path,
        saves_dir: str | Path,
        smapi_path: str | Path | None = None,
    ) -> None:
        self.scenarios_dir = Path(scenarios_dir).expanduser().resolve()
        self.saves_dir = Path(saves_dir).expanduser().resolve()
        self.smapi_path = smapi_path
        self._lock = threading.RLock()
        self._action_lock = threading.Lock()
        self._replay_condition = threading.Condition(self._lock)
        self._generation = 0
        self._status = "idle"
        self._scenario_id: str | None = None
        self._runtime_save_name: str | None = None
        self._port = 10783
        self._attach = False
        self._sample_rate = 100
        self._timeout = 90.0
        self._process: Any = None
        self._observation: dict[str, Any] | None = None
        self._observation_raw: str | None = None
        self._error: str | None = None
        self._logs: list[dict[str, str]] = []
        self._recording = False
        self._pending_snapshot: dict[str, Any] | None = None
        self._action_results: list[dict[str, Any]] = []
        self._replay_status = "idle"
        self._replay_next_index = 0
        self._replay_results: list[dict[str, Any]] = []
        self._replay_stop = False
        self._replay_load_error: str | None = None
        self._timeline_cursor = 0
        self._replay_thread: threading.Thread | None = None
        self._replay_thread_generation: int | None = None
        self._assertion_report: dict[str, Any] | None = None

    def _log(
        self,
        message: str,
        level: str = "info",
        *,
        generation: int | None = None,
    ) -> None:
        with self._lock:
            if generation is not None and generation != self._generation:
                return
            self._logs.append(
                {
                    "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "level": level,
                    "message": message,
                }
            )
            del self._logs[:-500]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            return {
                "status": self._status,
                "scenarioId": self._scenario_id,
                "runtimeSaveName": self._runtime_save_name,
                "port": self._port,
                "attached": self._attach,
                "pid": process.pid if process is not None else None,
                "observation": self._observation,
                "observationRaw": self._observation_raw,
                "error": self._error,
                "logs": list(self._logs),
                "recording": self._recording,
                "pendingSnapshot": (
                    {
                        key: value
                        for key, value in self._pending_snapshot.items()
                        if key != "raw"
                    }
                    if self._pending_snapshot is not None
                    else None
                ),
                "actionResults": list(self._action_results),
                "replay": {
                    "status": self._replay_status,
                    "nextIndex": self._replay_next_index,
                    "total": self._replay_total(),
                    "results": list(self._replay_results),
                    "error": self._replay_load_error,
                },
                "assertionReport": self._assertion_report,
            }

    def _replay_total(self) -> int:
        if self._scenario_id is None:
            return 0
        try:
            total = len(load_actions(self.scenarios_dir / self._scenario_id))
            self._replay_load_error = None
            return total
        except (OSError, ValueError) as error:
            self._replay_load_error = str(error)
            return 0

    def _set_status(self, generation: int, status: str) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            self._status = status
            return True

    def start(
        self,
        scenario_id: str,
        *,
        port: int = 10783,
        attach: bool = False,
        sample_rate: int = 100,
        timeout: float = 90,
    ) -> None:
        scenario_path = (self.scenarios_dir / scenario_id).resolve()
        if scenario_path.parent != self.scenarios_dir:
            raise ValueError("invalid scenario id")
        load_scenario(scenario_path)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if type(sample_rate) is not int or not 1 <= sample_rate <= 100:
            raise ValueError("sample rate must be between 1 and 100")
        if type(attach) is not bool:
            raise ValueError("attach must be a boolean")
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be greater than zero")

        with self._lock:
            if self._status in _ACTIVE_STATUSES:
                raise RuntimeError("a scenario run is already active")
            self._generation += 1
            generation = self._generation
            self._status = "preparing"
            self._scenario_id = scenario_id
            self._runtime_save_name = None
            self._port = port
            self._attach = attach
            self._sample_rate = sample_rate
            self._timeout = float(timeout)
            self._process = None
            self._observation = None
            self._observation_raw = None
            self._error = None
            self._logs = []
            self._recording = False
            self._pending_snapshot = None
            self._action_results = []
            self._replay_status = "idle"
            self._replay_next_index = 0
            self._replay_results = []
            self._replay_stop = False
            self._replay_load_error = None
            self._timeline_cursor = 0
            self._replay_thread = None
            self._replay_thread_generation = None
            self._assertion_report = None

        worker = threading.Thread(
            target=self._run,
            args=(generation,),
            name=f"scenario-{scenario_id}",
            daemon=True,
        )
        worker.start()

    def _read_process_output(self, process: Any, generation: int) -> None:
        if process.stdout is None:
            return
        for raw_line in iter(process.stdout.readline, b""):
            self._log(
                raw_line.decode("utf-8", errors="replace").rstrip(),
                generation=generation,
            )

    def _run(self, generation: int) -> None:
        with self._lock:
            scenario_id = self._scenario_id
            port = self._port
            attach = self._attach
            sample_rate = self._sample_rate
            timeout = self._timeout
        process = None
        try:
            scenario = load_scenario(self.scenarios_dir / str(scenario_id))
            client = ModClient(port=port, command_timeout=timeout)
            self._log(f"Validated scenario “{scenario.name}”.", generation=generation)

            if attach:
                self._set_status(generation, "connecting")
                self._log(
                    f"Connecting to an existing SMAPI process on port {port}.",
                    generation=generation,
                )
                client.wait_for_server(timeout=timeout)
                client.send("observe_v2_light%-1", timeout=timeout)
            else:
                executable = resolve_smapi_path(self.smapi_path)
                ensure_port_available(port)

            if not self._set_status(generation, "preparing"):
                return
            self._log("Restoring the original save fixture.", generation=generation)
            restored = restore_fixture(scenario, self.saves_dir, port=port)
            with self._lock:
                if generation != self._generation:
                    return
                self._runtime_save_name = restored.runtime_save_name

            if not attach:
                if not self._set_status(generation, "launching"):
                    return
                self._log(f"Launching SMAPI on port {port}.", generation=generation)
                process = launch_smapi(
                    executable,
                    port=port,
                    sample_rate=sample_rate,
                    capture_output=True,
                )
                with self._lock:
                    if generation != self._generation:
                        terminate_launched_process(process)
                        return
                    self._process = process
                threading.Thread(
                    target=self._read_process_output,
                    args=(process, generation),
                    name="smapi-output",
                    daemon=True,
                ).start()

            if not self._set_status(generation, "connecting"):
                return
            if not attach:
                self._log("Waiting for the mod interface.", generation=generation)
                client.wait_for_server(timeout=timeout)

            if not self._set_status(generation, "loading"):
                return
            self._log(
                f"Loading {restored.runtime_save_name}.",
                generation=generation,
            )
            raw_observation = client.load_fixture_until_ready(
                restored.runtime_save_name,
                surroundings_size=scenario.surroundings_size,
                timeout=timeout,
            )
            observation = json.loads(raw_observation)
            with self._lock:
                if generation != self._generation:
                    return
                self._observation = observation
                self._observation_raw = raw_observation
                self._status = "ready"
            self._log("Scenario is ready.", generation=generation)
        except Exception as error:
            if process is not None:
                terminate_launched_process(process)
            with self._lock:
                if generation == self._generation:
                    self._process = None
                    self._status = "error"
                    self._error = str(error)
            self._log(str(error), "error", generation=generation)

    def refresh_observation(self) -> dict[str, Any]:
        with self._lock:
            if self._status != "ready":
                raise RuntimeError("scenario is not ready")
            scenario = load_scenario(self.scenarios_dir / str(self._scenario_id))
            port = self._port
            timeout = self._timeout
            generation = self._generation
        with self._action_lock:
            raw = ModClient(port=port, command_timeout=timeout).send(
                f"observe_v2_light%{scenario.surroundings_size}",
                timeout=timeout,
            )
        observation = json.loads(raw)
        if not isinstance(observation, dict):
            raise RuntimeError("observation root is not a JSON object")
        with self._lock:
            if generation != self._generation or self._status != "ready":
                raise RuntimeError("scenario changed while observation was loading")
            self._observation = observation
            self._observation_raw = raw
        self._log("Observation refreshed.")
        return observation

    @staticmethod
    def _parse_result(raw: str) -> Any:
        normalized = raw.strip()
        if normalized == "True":
            return True
        if normalized == "False":
            return False
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def _scenario_path(self) -> Path:
        with self._lock:
            if self._scenario_id is None:
                raise RuntimeError("no scenario has been selected")
            return self.scenarios_dir / self._scenario_id

    def start_recording(self, *, from_index: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self._status != "ready":
                raise RuntimeError("scenario is not ready")
            if self._replay_status in {"running", "paused"}:
                raise RuntimeError("cannot record while replay is active")
            scenario_path = self._scenario_path()
        if from_index is not None:
            truncate_actions(scenario_path, from_index)
            cursor = from_index
        else:
            cursor = len(load_actions(scenario_path))
        with self._lock:
            self._recording = True
            self._timeline_cursor = cursor
        self._log(
            "Recording started."
            if from_index is None
            else f"Re-recording from action {from_index + 1}."
        )
        return self.snapshot()

    def stop_recording(self) -> dict[str, Any]:
        with self._lock:
            if not self._recording:
                raise RuntimeError("recording is not active")
            self._recording = False
        self._log("Recording stopped.")
        return self.snapshot()

    def execute_action(
        self,
        action: str,
        arguments: list[str],
        *,
        record: bool | None = None,
    ) -> dict[str, Any]:
        validated = validate_action({"action": action, "arguments": arguments})
        with self._lock:
            if self._status != "ready":
                raise RuntimeError("scenario is not ready")
            if record is None and self._replay_status in {"running", "stepping"}:
                raise RuntimeError("cannot issue a manual action while replay is active")
            port = self._port
            timeout = self._timeout
            should_record = self._recording if record is None else record
            scenario_path = self._scenario_path()
            generation = self._generation
        command = "%".join([validated["action"], *validated["arguments"]])
        started = time.monotonic()
        raw_result: str | None = None
        error_message: str | None = None
        try:
            with self._action_lock:
                raw_result = ModClient(
                    port=port,
                    command_timeout=timeout,
                ).send(command, timeout=timeout)
        except Exception as error:
            error_message = str(error)
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        result = None if raw_result is None else self._parse_result(raw_result)
        recorded = {
            "id": uuid.uuid4().hex,
            "action": validated["action"],
            "arguments": validated["arguments"],
            "recordedAt": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "durationMs": duration_ms,
            "result": result,
            "resultRaw": raw_result,
            "error": error_message,
        }
        with self._lock:
            if generation != self._generation or self._status != "ready":
                raise RuntimeError("scenario changed while the action was executing")
            if should_record:
                append_action(scenario_path, recorded)
            self._action_results.append(recorded)
            if should_record:
                self._timeline_cursor += 1
        if error_message is not None:
            self._log(f"{action} failed: {error_message}", "error")
            raise RuntimeError(error_message)
        self._log(f"{action} completed in {duration_ms} ms.")
        try:
            self.refresh_observation()
        except Exception as error:
            self._log(f"Could not refresh observation after {action}: {error}", "warning")
        return recorded

    def mark_snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._pending_snapshot is not None:
                raise RuntimeError("name or discard the pending checkpoint first")
        self.refresh_observation()
        with self._lock:
            if self._observation_raw is None:
                raise RuntimeError("no observation is available")
            marked = {
                "pending": True,
                "capturedAt": datetime.now().astimezone().isoformat(
                    timespec="milliseconds"
                ),
                "afterAction": self._timeline_cursor,
                "raw": self._observation_raw,
            }
            self._pending_snapshot = marked
        self._log("Observation checkpoint marked; give it a name to save it.")
        return {key: value for key, value in marked.items() if key != "raw"}

    def save_marked_snapshot(self, name: str) -> dict[str, Any]:
        with self._lock:
            if self._pending_snapshot is None:
                raise RuntimeError("no observation checkpoint is waiting to be named")
            pending = dict(self._pending_snapshot)
            scenario_path = self._scenario_path()
        save_snapshot(
            scenario_path,
            name,
            pending["raw"],
            captured_at=pending["capturedAt"],
            after_action=pending["afterAction"],
        )
        with self._lock:
            self._pending_snapshot = None
        self._log(f"Saved observation checkpoint “{name}”.")
        return {
            "name": name,
            "capturedAt": pending["capturedAt"],
            "afterAction": pending["afterAction"],
        }

    def cancel_marked_snapshot(self) -> None:
        with self._lock:
            self._pending_snapshot = None
        self._log("Discarded the pending observation checkpoint.")

    def refresh_preview(self) -> dict[str, Any]:
        with self._lock:
            if self._status != "ready":
                raise RuntimeError("scenario is not ready")
            scenario = load_scenario(self._scenario_path())
            port = self._port
            timeout = self._timeout
        with self._action_lock:
            raw = ModClient(port=port, command_timeout=timeout).send(
                f"observe_v2%{scenario.surroundings_size}",
                timeout=timeout,
            )
        try:
            observation = json.loads(raw)
            pixels = observation["ScreenShot"]
            width, height = observation["MetaData"]["ViewportSize"]
            decoded = base64.b64decode(pixels, validate=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("mod returned an invalid screenshot payload") from error
        if (
            type(width) is not int
            or type(height) is not int
            or width <= 0
            or height <= 0
            or len(decoded) != width * height * 4
        ):
            raise RuntimeError("mod screenshot dimensions do not match its RGBA payload")
        self._log("Game preview captured.")
        return {
            "pixels": pixels,
            "width": width,
            "height": height,
            "format": "rgba8",
        }

    def _append_replay_result(
        self,
        index: int,
        result: dict[str, Any],
        *,
        generation: int,
    ) -> bool:
        replay_result = dict(result, index=index)
        with self._lock:
            if generation != self._generation:
                return False
            self._replay_results.append(replay_result)
            self._replay_next_index = index + 1
            self._timeline_cursor = index + 1
            return True

    def step_replay(self) -> dict[str, Any]:
        with self._lock:
            if self._status != "ready":
                raise RuntimeError("scenario is not ready")
            if self._recording:
                raise RuntimeError("stop recording before replaying")
            if self._replay_status in {"running", "stepping"}:
                raise RuntimeError("replay is already running")
            index = self._replay_next_index
            generation = self._generation
            replay_worker_active = (
                self._replay_thread is not None
                and self._replay_thread_generation == generation
                and self._replay_thread.is_alive()
            )
            actions = load_actions(self._scenario_path())
            if index >= len(actions):
                self._replay_status = "completed"
                raise RuntimeError("replay has no remaining actions")
            self._replay_status = "stepping"
        try:
            action = actions[index]
            result = self.execute_action(
                action["action"],
                action["arguments"],
                record=False,
            )
            if not self._append_replay_result(
                index,
                result,
                generation=generation,
            ):
                return result
            with self._lock:
                if self._replay_status == "stepping":
                    self._replay_status = (
                        "completed"
                        if self._replay_next_index >= len(actions)
                        else "paused" if replay_worker_active else "stepped"
                    )
            return result
        except Exception:
            with self._lock:
                self._replay_status = "error"
            raise

    def start_replay(self) -> dict[str, Any]:
        with self._replay_condition:
            if self._status != "ready":
                raise RuntimeError("scenario is not ready")
            if self._recording:
                raise RuntimeError("stop recording before replaying")
            replay_worker_active = (
                self._replay_thread is not None
                and self._replay_thread_generation == self._generation
                and self._replay_thread.is_alive()
            )
            if self._replay_status in {"running", "stepping"} or (
                self._replay_status == "paused" and replay_worker_active
            ):
                raise RuntimeError("replay is already active")
            actions = load_actions(self._scenario_path())
            if self._replay_next_index >= len(actions):
                raise RuntimeError("replay has no remaining actions; reset the fixture")
            self._replay_status = "running"
            self._replay_stop = False
            generation = self._generation
            self._replay_condition.notify_all()
        worker = threading.Thread(
            target=self._run_replay,
            args=(generation, actions),
            name=f"replay-{self._scenario_id}",
            daemon=True,
        )
        with self._lock:
            self._replay_thread = worker
            self._replay_thread_generation = generation
        worker.start()
        self._log("Replay started.")
        return self.snapshot()

    def _run_replay(self, generation: int, actions: list[dict[str, Any]]) -> None:
        while True:
            with self._replay_condition:
                while (
                    generation == self._generation
                    and self._replay_status == "paused"
                    and not self._replay_stop
                ):
                    self._replay_condition.wait()
                if (
                    generation != self._generation
                    or self._replay_stop
                    or self._replay_status != "running"
                ):
                    return
                index = self._replay_next_index
                if index >= len(actions):
                    self._replay_status = "completed"
                    self._log("Replay completed.", generation=generation)
                    return
                action = actions[index]
            try:
                result = self.execute_action(
                    action["action"],
                    action["arguments"],
                    record=False,
                )
                self._append_replay_result(
                    index,
                    result,
                    generation=generation,
                )
            except Exception as error:
                with self._lock:
                    if generation == self._generation:
                        self._replay_status = "error"
                        self._error = str(error)
                return

    def pause_replay(self) -> dict[str, Any]:
        with self._replay_condition:
            if self._replay_status != "running":
                raise RuntimeError("replay is not running")
            self._replay_status = "paused"
        self._log("Replay paused.")
        return self.snapshot()

    def resume_replay(self) -> dict[str, Any]:
        with self._replay_condition:
            if self._replay_status != "paused":
                raise RuntimeError("replay is not paused")
            self._replay_status = "running"
            self._replay_condition.notify_all()
        self._log("Replay resumed.")
        return self.snapshot()

    def stop_replay(self) -> dict[str, Any]:
        with self._replay_condition:
            if self._replay_status not in {"running", "paused", "stepping"}:
                raise RuntimeError("replay is not active")
            self._replay_stop = True
            self._replay_status = "stopped"
            self._replay_condition.notify_all()
        self._log("Replay stopped.")
        return self.snapshot()

    def run_assertions(self) -> dict[str, Any]:
        with self._lock:
            if self._status != "ready":
                raise RuntimeError("scenario is not ready")
            scenario_path = self._scenario_path()
            observation = self._observation
            actions = (
                list(self._replay_results)
                if self._replay_results
                else list(self._action_results)
            )
        report = evaluate_assertions(
            load_assertions(scenario_path),
            observation=observation,
            actions=actions,
        )
        with self._lock:
            self._assertion_report = report
        self._log(
            f"Assertions: {report['passedCount']} passed, "
            f"{report['failedCount']} failed.",
            "info" if report["passed"] else "error",
        )
        return report

    def reset(self) -> None:
        with self._lock:
            if self._scenario_id is None:
                raise RuntimeError("no scenario has been selected")
            configuration = (
                self._scenario_id,
                self._port,
                self._attach,
                self._sample_rate,
                self._timeout,
            )
        self.stop()
        self.start(
            configuration[0],
            port=configuration[1],
            attach=configuration[2],
            sample_rate=configuration[3],
            timeout=configuration[4],
        )

    def stop(self) -> None:
        with self._replay_condition:
            self._generation += 1
            process = self._process
            self._process = None
            self._status = "idle"
            self._runtime_save_name = None
            self._observation = None
            self._observation_raw = None
            self._error = None
            self._recording = False
            self._pending_snapshot = None
            self._action_results = []
            self._replay_status = "idle"
            self._replay_next_index = 0
            self._replay_results = []
            self._replay_stop = True
            self._replay_load_error = None
            self._timeline_cursor = 0
            self._replay_thread = None
            self._replay_thread_generation = None
            self._assertion_report = None
            self._replay_condition.notify_all()
        if process is not None:
            terminate_launched_process(process)
            self._log("Stopped the SMAPI process.")
