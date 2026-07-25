import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from harness.controller import RunController
from harness.fixture import RestoredFixture


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = 4321
        self.stdout = None
        self.terminated = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> int:
        return 0


class _FakeClient:
    observations = [
        json.dumps({"CurrentMenuData": {"Type": "LevelUpMenu"}}),
        json.dumps({"CurrentMenuData": None}),
    ]

    def __init__(self, **_kwargs: object) -> None:
        pass

    def wait_for_server(self, **_kwargs: object) -> None:
        pass

    def send(self, _command: str, **_kwargs: object) -> str:
        return self.observations[-1]

    def load_fixture_until_ready(self, *_args: object, **_kwargs: object) -> str:
        return self.observations[0]


class _ActionClient:
    commands: list[str] = []

    def __init__(self, **_kwargs: object) -> None:
        pass

    def send(self, command: str, **_kwargs: object) -> str:
        self.commands.append(command)
        if command.startswith("observe_v2%"):
            return json.dumps(
                {
                    "ScreenShot": "AQIDBA==",
                    "MetaData": {"ViewportSize": [1, 1]},
                }
            )
        if command.startswith("observe_v2_light%"):
            return json.dumps({"CurrentMenuData": {"type": "No Menu"}})
        if command == "move_step%up":
            return "True"
        if command == "interact":
            return "Message received"
        raise AssertionError(f"unexpected command: {command}")


class _SlowActionClient:
    started = threading.Event()
    release = threading.Event()

    def __init__(self, **_kwargs: object) -> None:
        pass

    def send(self, _command: str, **_kwargs: object) -> str:
        self.started.set()
        self.release.wait(timeout=2)
        return "True"


class RunControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.scenarios_dir = root / "scenarios"
        self.scenario_dir = self.scenarios_dir / "level-up-test"
        fixture = self.scenario_dir / "save"
        fixture.mkdir(parents=True)
        (fixture / "SaveGameInfo").write_text(
            "<Farmer><farmName>TestFarm</farmName></Farmer>",
            encoding="utf-8",
        )
        (fixture / "TestFarm_123").write_text(
            "<SaveGame><player><farmName>TestFarm</farmName></player>"
            "<uniqueIDForThisGame>123</uniqueIDForThisGame></SaveGame>",
            encoding="utf-8",
        )
        (self.scenario_dir / "scenario.json").write_text(
            json.dumps(
                {
                    "formatVersion": 1,
                    "id": "level-up-test",
                    "name": "Level-up test",
                    "fixture": {"saveFile": "TestFarm_123"},
                }
            ),
            encoding="utf-8",
        )
        self.saves_dir = root / "saves"
        self.process = _FakeProcess()
        self.controller = RunController(
            scenarios_dir=self.scenarios_dir,
            saves_dir=self.saves_dir,
        )
        self.addCleanup(self.controller.stop)
        _ActionClient.commands = []
        _SlowActionClient.started.clear()
        _SlowActionClient.release.clear()

    def _wait_for(self, status: str) -> dict[str, object]:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = self.controller.snapshot()
            if state["status"] == status:
                return state
            time.sleep(0.01)
        self.fail(f"controller never reached {status}: {self.controller.snapshot()}")

    def test_start_launches_and_exposes_the_exact_agent_observation(self) -> None:
        restored = RestoredFixture(
            path=self.saves_dir / "TestFarm_999",
            runtime_save_name="TestFarm_999",
        )

        with (
            mock.patch("harness.controller.resolve_smapi_path", return_value=Path("/smapi")),
            mock.patch("harness.controller.ensure_port_available"),
            mock.patch("harness.controller.restore_fixture", return_value=restored),
            mock.patch("harness.controller.launch_smapi", return_value=self.process),
            mock.patch("harness.controller.ModClient", _FakeClient),
        ):
            self.controller.start("level-up-test", port=6123)
            state = self._wait_for("ready")

        self.assertEqual(state["scenarioId"], "level-up-test")
        self.assertEqual(state["runtimeSaveName"], "TestFarm_999")
        self.assertEqual(state["pid"], 4321)
        self.assertEqual(
            state["observation"],
            {"CurrentMenuData": {"Type": "LevelUpMenu"}},
        )
        self.assertEqual(
            state["observationRaw"],
            json.dumps({"CurrentMenuData": {"Type": "LevelUpMenu"}}),
        )

    def test_refresh_observation_uses_the_normal_light_observation(self) -> None:
        self.controller._status = "ready"
        self.controller._scenario_id = "level-up-test"
        self.controller._port = 6123

        with mock.patch("harness.controller.ModClient", _FakeClient):
            observation = self.controller.refresh_observation()

        self.assertEqual(observation, {"CurrentMenuData": None})
        self.assertEqual(self.controller.snapshot()["observation"], observation)

    def test_start_rejects_a_second_run_while_the_first_is_active(self) -> None:
        self.controller._status = "loading"

        with self.assertRaisesRegex(RuntimeError, "already active"):
            self.controller.start("level-up-test", port=6123)

    def test_start_rejects_non_finite_timeout_and_non_boolean_attach(self) -> None:
        with self.assertRaisesRegex(ValueError, "timeout"):
            self.controller.start("level-up-test", timeout=float("nan"))

        with self.assertRaisesRegex(ValueError, "attach"):
            self.controller.start("level-up-test", attach="false")

    def test_log_output_from_an_old_run_is_not_mixed_into_the_next_run(self) -> None:
        self.controller._generation = 2

        self.controller._log("old SMAPI output", generation=1)

        self.assertEqual(self.controller.snapshot()["logs"], [])

    def _make_ready(self) -> None:
        self.controller._status = "ready"
        self.controller._scenario_id = "level-up-test"
        self.controller._port = 6123
        self.controller._observation = {"CurrentMenuData": {"type": "No Menu"}}
        self.controller._observation_raw = json.dumps(self.controller._observation)

    def test_recording_uses_the_normal_mod_command_and_persists_the_result(self) -> None:
        self._make_ready()

        with mock.patch("harness.controller.ModClient", _ActionClient):
            self.controller.start_recording(from_index=0)
            result = self.controller.execute_action("move_step", ["up"])
            self.controller.stop_recording()

        persisted = [
            json.loads(line)
            for line in (self.scenario_dir / "actions.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        self.assertEqual(_ActionClient.commands[0], "move_step%up")
        self.assertTrue(result["result"])
        self.assertEqual(persisted[0]["action"], "move_step")
        self.assertEqual(persisted[0]["arguments"], ["up"])
        self.assertIsInstance(persisted[0]["durationMs"], int)
        self.assertFalse(self.controller.snapshot()["recording"])

    def test_marked_snapshot_is_named_after_capture_and_preserves_raw_payload(self) -> None:
        self._make_ready()

        with mock.patch("harness.controller.ModClient", _ActionClient):
            marked = self.controller.mark_snapshot()
            saved = self.controller.save_marked_snapshot("after-start")

        snapshot_path = self.scenario_dir / "snapshots" / "after-start.json"
        self.assertTrue(marked["pending"])
        self.assertEqual(saved["name"], "after-start")
        self.assertEqual(
            snapshot_path.read_text(encoding="utf-8"),
            json.dumps({"CurrentMenuData": {"type": "No Menu"}}),
        )
        self.assertIsNone(self.controller.snapshot()["pendingSnapshot"])

    def test_replay_supports_single_step_then_run_all(self) -> None:
        self._make_ready()
        (self.scenario_dir / "actions.jsonl").write_text(
            json.dumps({"action": "move_step", "arguments": ["up"]}) + "\n"
            + json.dumps({"action": "interact", "arguments": []})
            + "\n",
            encoding="utf-8",
        )

        with mock.patch("harness.controller.ModClient", _ActionClient):
            first = self.controller.step_replay()
            self.assertEqual(self.controller.snapshot()["replay"]["status"], "stepped")
            self.controller.start_replay()
            self._wait_for_replay("completed")

        state = self.controller.snapshot()["replay"]
        self.assertEqual(first["action"], "move_step")
        self.assertEqual(state["nextIndex"], 2)
        self.assertEqual([item["action"] for item in state["results"]], ["move_step", "interact"])

    def _wait_for_replay(self, status: str) -> dict[str, object]:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            replay = self.controller.snapshot()["replay"]
            if replay["status"] == status:
                return replay
            time.sleep(0.01)
        self.fail(f"replay never reached {status}: {self.controller.snapshot()}")

    def test_preview_returns_raw_rgba_pixels_without_putting_them_in_run_polling(self) -> None:
        self._make_ready()

        with mock.patch("harness.controller.ModClient", _ActionClient):
            preview = self.controller.refresh_preview()

        self.assertEqual(preview["pixels"], "AQIDBA==")
        self.assertEqual(preview["width"], 1)
        self.assertEqual(preview["height"], 1)
        self.assertNotIn("preview", self.controller.snapshot())

    def test_assertion_report_combines_live_observation_and_replay_results(self) -> None:
        self._make_ready()
        (self.scenario_dir / "assertions.json").write_text(
            json.dumps(
                [
                    {
                        "id": "menu",
                        "source": "observation",
                        "path": "/CurrentMenuData/type",
                        "operator": "equals",
                        "expected": "No Menu",
                    }
                ]
            ),
            encoding="utf-8",
        )

        report = self.controller.run_assertions()

        self.assertTrue(report["passed"])
        self.assertEqual(self.controller.snapshot()["assertionReport"], report)

    def test_stopping_mid_action_does_not_leak_results_into_the_next_run(self) -> None:
        self._make_ready()
        failures: list[str] = []

        def execute() -> None:
            try:
                self.controller.execute_action("interact", [])
            except RuntimeError as error:
                failures.append(str(error))

        with mock.patch("harness.controller.ModClient", _SlowActionClient):
            worker = threading.Thread(target=execute)
            worker.start()
            self.assertTrue(_SlowActionClient.started.wait(timeout=1))
            self.controller.stop()
            _SlowActionClient.release.set()
            worker.join(timeout=2)

        self.assertIn("scenario changed", failures[0])
        self.assertEqual(self.controller.snapshot()["actionResults"], [])


if __name__ == "__main__":
    unittest.main()
