from __future__ import annotations

import ast
import base64
import json
import math
import sys
import threading
import time
from pathlib import Path
from types import FrameType
from typing import Any

from .debug_artifact import DebugTarget, load_debug_target
from .fixture import restore_debug_checkpoint
from .rpc import ModClient
from .runtime import (
    ensure_port_available,
    launch_smapi,
    resolve_smapi_path,
    terminate_launched_process,
)


class DebugStopped(BaseException):
    pass


def _init_command(source: str) -> str:
    try:
        expression = ast.parse(source, mode="eval").body
        if (
            not isinstance(expression, ast.Call)
            or not isinstance(expression.func, ast.Name)
            or expression.keywords
        ):
            raise ValueError
        arguments = [ast.literal_eval(argument) for argument in expression.args]
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"invalid task init command: {source}") from error
    parts = [expression.func.id, *(str(argument) for argument in arguments)]
    if any("%" in part or "\n" in part or "\r" in part for part in parts):
        raise ValueError(f"invalid task init command: {source}")
    return "%".join(parts)


def _lowercase_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key).lower(): _lowercase_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_lowercase_keys(item) for item in value]
    return value


def _observation(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    player = value["Player"]
    game = value["GameState"]
    farm = value["Farm"]
    position = player["Position"]
    if isinstance(position, dict):
        position = [position["X"], position["Y"]]
    directions = ["up", "right", "down", "left"]
    direction = player["FacingDirection"]
    return _lowercase_keys(
        {
            "health": str(player["Health"]),
            "energy": str(player["Stamina"]),
            "exhausted": player["Exhausted"],
            "money": str(player["Money"]),
            "location": player["Location"],
            "map_size": value["MetaData"]["MapSize"],
            "position": position,
            "facing_direction": (
                directions[direction] if direction in range(4) else "unknown"
            ),
            "inventory": player["Inventory"],
            "chosen_item": player["CurrentInventory"],
            "time": str(game["Time"]),
            "day": str(game["DayOfMonth"]),
            "season": game["Season"],
            "event_state": {
                "passing_out": game.get("PassingOut", False),
                "fade_to_black": game.get("FadeToBlack", False),
                "event_up": game.get("EventUp", False),
                "using_tool": game.get("UsingTool", False),
            },
            "farm_animals": farm["Animals"],
            "farm_pets": farm["Pets"],
            "farm_buildings": farm["Buildings"],
            "surroundings": value["SurroundingsData"],
            "crops": value["Crops"],
            "exits": value["Exits"],
            "buildings": value["Buildings"],
            "furniture": value["Furnitures"],
            "npcs": value["NPCs"],
            "shop_counters": value["ShopCounters"],
            "current_menu": value["CurrentMenuData"],
            "community_center_scrolls": value.get("CommunityCenterScrolls", []),
        }
    )


class DebugActions:
    def __init__(self, port: int, timeout: float):
        self.client = ModClient(port=port, command_timeout=timeout)
        self.lock = threading.Lock()

    def _send(self, command: str) -> str:
        with self.lock:
            return self.client.send(command)

    def move_relative(self, x: int, y: int) -> None:
        self._send(f"move_relative%{x}%{y}")

    def move_absolute(self, x: int, y: int) -> None:
        self._send(f"move_absolute%{x}%{y}")

    def craft(self, item: str) -> None:
        self._send(f"craft%{item}")

    def turn(self, direction: int) -> None:
        self._send(f"turn%{direction}")

    @staticmethod
    def _direction(direction: str) -> int:
        return {"up": 0, "right": 1, "down": 2, "left": 3}.get(direction, 0)

    def use(self, direction: str) -> None:
        self.turn(self._direction(direction))
        self._send("use")

    def choose_item(self, slot_index: int) -> None:
        self._send(f"choose_item%{slot_index}")

    def interact(self, direction: str) -> None:
        self.turn(self._direction(direction))
        self._send("interact")

    def choose_option(
        self,
        option_index: int,
        quantity: int | None = None,
        direction: str | None = None,
    ) -> None:
        direction_int = 1 if direction == "out" else 0
        self._send(f"choose_option%{option_index}%{quantity or 0}%{direction_int}")

    def attach_item(self, slot_index: int) -> None:
        self._send(f"attach%{slot_index}")

    def unattach_item(self) -> None:
        self._send("unattach")

    def observe(self, surroundings_size: int = -1) -> dict[str, Any]:
        return _observation(self._send(f"observe_v2_light%{surroundings_size}"))

    def menu(self, option: str, menu_name: str) -> None:
        if option == "close":
            self._send("exit_menu")
        elif option == "open" and menu_name == "map":
            self._send("open_map")
        self._send(f"menu%{option}%{menu_name}")

    def pause_game(self) -> None:
        self._send("pause")

    def resume_game(self) -> None:
        self._send("resume")


class DebugProgramHarness:
    def __init__(self, namespace: dict[str, Any]):
        self.namespace = namespace
        self.logs: list[Any] = []

    def invoke(self, function: str) -> Any:
        return self.namespace[function]()

    def log(self, message: Any) -> None:
        self.logs.append(message)


def _safe_repr(value: Any) -> str:
    try:
        rendered = repr(value)
    except Exception:
        rendered = f"<{type(value).__name__}>"
    return rendered if len(rendered) <= 2000 else rendered[:1997] + "..."


class DebugSession:
    def __init__(self, target: DebugTarget, actions: DebugActions):
        self.target = target
        self.actions = actions
        self.filename = (
            f"<stalley-debug:{target.run_id}:{target.event_sequence}>"
        )
        self.condition = threading.Condition()
        self.breakpoints: set[int] = set()
        self.status = "ready"
        self.current_line: int | None = None
        self.stack: list[dict[str, Any]] = []
        self.locals: dict[str, str] = {}
        self.observation: dict[str, Any] | None = (
            target.checkpoint.observation if target.checkpoint else None
        )
        self.error: str | None = None
        self.pause_requested = False
        self.step_once = False
        self.stop_requested = False
        self.thread: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.condition:
            return {
                "status": self.status,
                "currentLine": self.current_line,
                "breakpoints": sorted(
                    line - self.target.source_start_line + 1
                    for line in self.breakpoints
                ),
                "stack": list(self.stack),
                "locals": dict(self.locals),
                "observation": self.observation,
                "error": self.error,
            }

    def set_breakpoints(self, lines: list[int]) -> None:
        with self.condition:
            self.breakpoints = {
                self.target.source_start_line + line - 1
                for line in lines
                if line >= 1
            }

    def start(self) -> None:
        with self.condition:
            if self.thread and self.thread.is_alive():
                raise RuntimeError("debug program is already running")
            self.status = "running"
            self.error = None
            self.stop_requested = False
            self.thread = threading.Thread(
                target=self._run,
                name=f"debug-{self.target.function}",
                daemon=True,
            )
            self.thread.start()

    def _capture(self, frame: FrameType) -> None:
        frames = []
        current: FrameType | None = frame
        while current is not None:
            if current.f_code.co_filename == self.filename:
                frames.append(
                    {
                        "function": current.f_code.co_name,
                        "line": current.f_lineno,
                    }
                )
            current = current.f_back
        self.current_line = frame.f_lineno
        self.stack = frames
        self.locals = {
            name: _safe_repr(value)
            for name, value in frame.f_locals.items()
            if name not in {"actions", "program_harness"}
        }
        try:
            self.observation = self.actions.observe()
        except Exception:
            pass

    def _trace(self, frame: FrameType, event: str, _: Any):
        if frame.f_code.co_filename != self.filename:
            return self._trace
        if event != "line":
            return self._trace
        with self.condition:
            if self.stop_requested:
                raise DebugStopped()
            should_pause = (
                self.pause_requested
                or self.step_once
                or frame.f_lineno in self.breakpoints
            )
            if not should_pause:
                return self._trace
            self.pause_requested = False
            self.step_once = False

        self.actions.pause_game()
        with self.condition:
            self._capture(frame)
            self.status = "paused"
            while self.status == "paused" and not self.stop_requested:
                self.condition.wait()
            if self.stop_requested:
                raise DebugStopped()
        return self._trace

    def _run(self) -> None:
        namespace: dict[str, Any] = {"actions": self.actions}
        namespace["program_harness"] = DebugProgramHarness(namespace)
        try:
            code = compile(self.target.program, self.filename, "exec")
            exec(code, namespace)
            sys.settrace(self._trace)
            namespace[self.target.runtime_function]()
        except DebugStopped:
            with self.condition:
                self.status = "stopped"
        except BaseException as error:
            with self.condition:
                self.error = f"{type(error).__name__}: {error}"
                self.status = "failed"
        else:
            with self.condition:
                self.status = "completed"
        finally:
            sys.settrace(None)
            try:
                self.actions.resume_game()
            except Exception:
                pass

    def pause(self) -> None:
        with self.condition:
            if self.status != "running":
                raise RuntimeError("debug program is not running")
            self.pause_requested = True

    def resume(self, *, step: bool = False) -> None:
        with self.condition:
            if self.status != "paused":
                raise RuntimeError("debug program is not paused")
            self.actions.resume_game()
            self.step_once = step
            self.status = "running"
            self.condition.notify_all()

    def stop(self) -> None:
        with self.condition:
            self.stop_requested = True
            was_paused = self.status == "paused"
            self.condition.notify_all()
        if was_paused:
            try:
                self.actions.resume_game()
            except Exception:
                pass


class DebugController:
    def __init__(
        self,
        *,
        runs_dir: str | Path,
        saves_dir: str | Path,
        run_controller: Any,
        smapi_path: str | Path | None = None,
    ):
        self.runs_dir = Path(runs_dir).expanduser().resolve()
        self.saves_dir = Path(saves_dir).expanduser().resolve()
        self.run_controller = run_controller
        self.smapi_path = smapi_path
        self.lock = threading.RLock()
        self.target: DebugTarget | None = None
        self.session: DebugSession | None = None
        self.breakpoints: list[int] = []
        self.status = "idle"
        self.error: str | None = None
        self.process: Any = None
        self.port = 10783
        self.timeout = 90.0
        self.runtime_save_name: str | None = None
        self.generation = 0

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            target = self.target.as_dict() if self.target else None
            session = self.session.snapshot() if self.session else None
            status = session["status"] if session else self.status
            process_alive = (
                self.process is not None and self.process.poll() is None
            )
            return {
                "status": status,
                "target": target,
                "session": session,
                "breakpoints": list(self.breakpoints),
                "port": self.port,
                "error": self.error,
                "canRestart": bool(
                    process_alive
                    and self.target
                    and (self.target.checkpoint or self.target.task_start)
                    and session
                    and session["status"]
                    in {"paused", "completed", "failed", "stopped"}
                ),
            }

    def load(self, run_id: str, event_sequence: int, function: str) -> dict[str, Any]:
        self.stop()
        with self.lock:
            self.target = None
            self.breakpoints = []
            self.status = "idle"
        target = load_debug_target(
            self.runs_dir,
            run_id,
            event_sequence,
            function,
        )
        with self.lock:
            self.target = target
            self.status = "ready"
            self.error = None
        return self.snapshot()

    def set_breakpoints(self, lines: list[int]) -> dict[str, Any]:
        with self.lock:
            if not self.target:
                raise RuntimeError("no debug target is loaded")
            self.breakpoints = sorted({line for line in lines if line >= 1})
            if self.session:
                self.session.set_breakpoints(self.breakpoints)
        return self.snapshot()

    def start(
        self,
        *,
        port: int = 10783,
        sample_rate: int = 100,
        timeout: float = 90,
    ) -> None:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if type(sample_rate) is not int or not 1 <= sample_rate <= 100:
            raise ValueError("sample rate must be between 1 and 100")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        with self.lock:
            if self.target is None:
                raise RuntimeError("no debug target is loaded")
            if self.status in {
                "preparing",
                "launching",
                "connecting",
                "loading",
                "restarting",
            }:
                raise RuntimeError("debug runtime is already starting")
            previous_session = self.session
            previous_process = self.process
            if previous_session and previous_session.status in {"running", "paused"}:
                raise RuntimeError("debug program is already running")
            breakpoints = list(self.breakpoints)
            self.session = None
            self.process = None
            self.runtime_save_name = None
            self.generation += 1
            generation = self.generation
            self.port = port
            self.timeout = float(timeout)
            self.status = "preparing"
            self.error = None
        if previous_session:
            previous_session.stop()
        if previous_process is not None:
            terminate_launched_process(previous_process)
        threading.Thread(
            target=self._start,
            args=(generation, port, sample_rate, timeout, breakpoints),
            name="debug-runtime",
            daemon=True,
        ).start()

    def _restore_target(self, target: DebugTarget, port: int):
        if target.checkpoint:
            return restore_debug_checkpoint(
                target.checkpoint.path / "save",
                target.checkpoint.save_name,
                target.checkpoint.id,
                self.saves_dir,
                port=port,
            )
        if target.task_start:
            return restore_debug_checkpoint(
                target.task_start.save_dir,
                target.task_start.save_name,
                f"task-start-{target.run_id}",
                self.saves_dir,
                port=port,
            )
        raise RuntimeError("debug target has no restorable baseline")

    @staticmethod
    def _load_target_state(
        target: DebugTarget,
        client: ModClient,
        runtime_save_name: str,
        timeout: float,
    ) -> dict[str, Any]:
        raw_observation = client.load_fixture_until_ready(
            runtime_save_name,
            surroundings_size=-1,
            timeout=timeout,
        )
        observation = _observation(raw_observation)
        if target.task_start and not target.checkpoint:
            for command in target.task_start.init_commands:
                client.send(_init_command(command), timeout=timeout)
                time.sleep(1)
            observation = DebugActions(client.port, timeout).observe()
        return observation

    def _start(
        self,
        generation: int,
        port: int,
        sample_rate: int,
        timeout: float,
        breakpoints: list[int],
    ) -> None:
        process = None
        initial_observation = None
        try:
            with self.lock:
                target = self.target
            if target is None:
                return
            if target.checkpoint or target.task_start:
                self.run_controller.stop()
                executable = resolve_smapi_path(self.smapi_path)
                ensure_port_available(port)
                restored = self._restore_target(target, port)
                with self.lock:
                    if generation != self.generation:
                        return
                    self.status = "launching"
                process = launch_smapi(
                    executable,
                    port=port,
                    sample_rate=sample_rate,
                )
                with self.lock:
                    if generation != self.generation:
                        terminate_launched_process(process)
                        return
                    self.process = process
                    self.status = "connecting"
                client = ModClient(port=port, command_timeout=timeout)
                client.wait_for_server(timeout=timeout)
                with self.lock:
                    self.status = "loading"
                initial_observation = self._load_target_state(
                    target,
                    client,
                    restored.runtime_save_name,
                    timeout,
                )
                with self.lock:
                    if generation != self.generation:
                        return
                    self.runtime_save_name = restored.runtime_save_name
            else:
                run = self.run_controller.snapshot()
                if run.get("status") != "ready":
                    raise RuntimeError(
                        "source-only debugging needs a ready scenario in StalleyMod"
                    )
                port = int(run["port"])
                with self.lock:
                    if generation != self.generation:
                        return
                    self.port = port

            session = DebugSession(target, DebugActions(port, timeout))
            session.set_breakpoints(breakpoints)
            if initial_observation is not None:
                session.observation = initial_observation
            with self.lock:
                if generation != self.generation:
                    if process is not None:
                        terminate_launched_process(process)
                    return
                self.session = session
                self.status = "running"
            session.start()
        except Exception as error:
            if process is not None:
                terminate_launched_process(process)
            with self.lock:
                if generation == self.generation:
                    self.process = None
                    self.status = "error"
                    self.error = str(error)

    def restart(self) -> dict[str, Any]:
        with self.lock:
            target = self.target
            session = self.session
            process = self.process
            runtime_save_name = self.runtime_save_name
            if (
                target is None
                or not (target.checkpoint or target.task_start)
                or session is None
                or process is None
                or process.poll() is not None
                or runtime_save_name is None
            ):
                raise RuntimeError("debug runtime cannot be restarted")
            breakpoints = list(self.breakpoints)
            if session.status not in {"paused", "completed", "failed", "stopped"}:
                raise RuntimeError("pause the debug program before restarting")
            self.generation += 1
            generation = self.generation
            self.session = None
            self.status = "restarting"
            self.error = None
            port = self.port
            timeout = self.timeout
        session.stop()
        threading.Thread(
            target=self._restart,
            args=(
                generation,
                target,
                session,
                runtime_save_name,
                port,
                timeout,
                breakpoints,
            ),
            name="debug-restart",
            daemon=True,
        ).start()
        return self.snapshot()

    def _restart(
        self,
        generation: int,
        target: DebugTarget,
        previous_session: DebugSession,
        runtime_save_name: str,
        port: int,
        timeout: float,
        breakpoints: list[int],
    ) -> None:
        try:
            if previous_session.thread:
                previous_session.thread.join(timeout=5)
                if previous_session.thread.is_alive():
                    raise RuntimeError("debug program did not stop before restart")
            restored = self._restore_target(target, port)
            if restored.runtime_save_name != runtime_save_name:
                raise RuntimeError("restored save identity changed during restart")
            with self.lock:
                if generation != self.generation:
                    return
                self.status = "loading"
            client = ModClient(port=port, command_timeout=timeout)
            observation = self._load_target_state(
                target,
                client,
                runtime_save_name,
                timeout,
            )
            session = DebugSession(target, DebugActions(port, timeout))
            session.set_breakpoints(breakpoints)
            session.observation = observation
            with self.lock:
                if generation != self.generation:
                    return
                self.session = session
                self.status = "running"
            session.start()
        except Exception as error:
            with self.lock:
                if generation == self.generation:
                    self.status = "error"
                    self.error = str(error)
                    if self.process is not None and self.process.poll() is None:
                        self.session = previous_session
                    else:
                        self.process = None
                        self.runtime_save_name = None

    def pause(self) -> dict[str, Any]:
        if not self.session:
            raise RuntimeError("debug program has not started")
        self.session.pause()
        return self.snapshot()

    def observe(self) -> dict[str, Any]:
        observation = DebugActions(self.port, 90).observe()
        if self.session:
            with self.session.condition:
                self.session.observation = observation
        return observation

    def preview(self) -> dict[str, Any]:
        raw = ModClient(port=self.port, command_timeout=90).send("observe_v2%-1")
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
        return {
            "pixels": pixels,
            "width": width,
            "height": height,
            "format": "rgba8",
        }

    def resume(self, *, step: bool = False) -> dict[str, Any]:
        if not self.session:
            raise RuntimeError("debug program has not started")
        self.session.resume(step=step)
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self.lock:
            self.generation += 1
            session = self.session
            process = self.process
            self.session = None
            self.process = None
            self.runtime_save_name = None
            if self.target:
                self.status = "ready"
            else:
                self.status = "idle"
        if session:
            session.stop()
        if process is not None:
            terminate_launched_process(process)
        return self.snapshot()
