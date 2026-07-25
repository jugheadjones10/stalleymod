from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Any


_SCENARIO_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class RegressionSuite:
    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._status = "idle"
        self._scenario_ids: list[str] = []
        self._current_scenario_id: str | None = None
        self._results: list[dict[str, Any]] = []
        self._error: str | None = None
        self._started_at: str | None = None
        self._finished_at: str | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            passed = (
                self._status == "completed"
                and all(result["status"] == "passed" for result in self._results)
            )
            return {
                "status": self._status,
                "passed": passed,
                "scenarioIds": list(self._scenario_ids),
                "currentScenarioId": self._current_scenario_id,
                "completedCount": len(self._results),
                "total": len(self._scenario_ids),
                "results": list(self._results),
                "error": self._error,
                "startedAt": self._started_at,
                "finishedAt": self._finished_at,
            }

    def start(
        self,
        scenario_ids: list[str],
        *,
        port: int = 10783,
        attach: bool = False,
        sample_rate: int = 100,
        timeout: float = 90,
    ) -> dict[str, Any]:
        if not scenario_ids:
            raise ValueError("suite must contain at least one scenario")
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("suite scenario ids must be unique")
        if any(
            not isinstance(scenario_id, str)
            or not _SCENARIO_ID.fullmatch(scenario_id)
            for scenario_id in scenario_ids
        ):
            raise ValueError("suite scenario ids must use lowercase kebab-case")
        with self._lock:
            if self._status == "running":
                raise RuntimeError("a regression suite is already running")
            run_status = self.controller.snapshot().get("status")
            if run_status not in {"idle", "error"}:
                raise RuntimeError("stop the active scenario before running the suite")
            self._status = "running"
            self._scenario_ids = list(scenario_ids)
            self._current_scenario_id = None
            self._results = []
            self._error = None
            self._started_at = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )
            self._finished_at = None
            self._stop_event.clear()
        threading.Thread(
            target=self._run,
            args=(port, attach, sample_rate, timeout),
            name="regression-suite",
            daemon=True,
        ).start()
        return self.snapshot()

    def _wait_for_run(self, terminal: set[str], timeout: float | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + timeout if timeout is not None else None
        while not self._stop_event.is_set():
            state = self.controller.snapshot()
            if state.get("status") in terminal:
                return state
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeError("scenario did not become ready before its deadline")
            time.sleep(0.05)
        raise RuntimeError("suite stopped")

    def _wait_for_replay(self) -> dict[str, Any]:
        while not self._stop_event.is_set():
            state = self.controller.snapshot()
            replay = state.get("replay", {})
            if replay.get("status") in {"completed", "error", "stopped"}:
                return state
            time.sleep(0.05)
        raise RuntimeError("suite stopped")

    def _run(
        self,
        port: int,
        attach: bool,
        sample_rate: int,
        timeout: float,
    ) -> None:
        try:
            for scenario_id in self._scenario_ids:
                if self._stop_event.is_set():
                    break
                with self._lock:
                    self._current_scenario_id = scenario_id
                started = time.monotonic()
                result: dict[str, Any] = {
                    "scenarioId": scenario_id,
                    "status": "error",
                    "durationMs": 0,
                    "report": None,
                    "error": None,
                }
                try:
                    self.controller.start(
                        scenario_id,
                        port=port,
                        attach=attach,
                        sample_rate=sample_rate,
                        timeout=timeout,
                    )
                    state = self._wait_for_run({"ready", "error"}, timeout + 30)
                    if state.get("status") == "error":
                        raise RuntimeError(str(state.get("error") or "scenario failed"))
                    replay = state.get("replay", {})
                    if replay.get("error"):
                        raise RuntimeError(str(replay["error"]))
                    if replay.get("total", 0) > 0:
                        self.controller.start_replay()
                        state = self._wait_for_replay()
                        if state.get("replay", {}).get("status") != "completed":
                            raise RuntimeError(
                                str(state.get("error") or "scenario replay failed")
                            )
                    report = self.controller.run_assertions()
                    result["report"] = report
                    result["status"] = "passed" if report["passed"] else "failed"
                except Exception as error:
                    result["error"] = str(error)
                finally:
                    result["durationMs"] = max(
                        0,
                        round((time.monotonic() - started) * 1000),
                    )
                    with self._lock:
                        self._results.append(result)
                    self.controller.stop()
            with self._lock:
                self._status = "stopped" if self._stop_event.is_set() else "completed"
        except Exception as error:
            with self._lock:
                self._status = "error"
                self._error = str(error)
        finally:
            with self._lock:
                self._current_scenario_id = None
                self._finished_at = datetime.now().astimezone().isoformat(
                    timespec="seconds"
                )

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._status != "running":
                return self.snapshot()
            self._stop_event.set()
            self._status = "stopped"
        self.controller.stop()
        return self.snapshot()
