import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from harness.server import create_app


class _FakeController:
    def __init__(self) -> None:
        self.started: tuple[str, dict[str, object]] | None = None
        self.calls: list[tuple[str, object]] = []

    def snapshot(self) -> dict[str, object]:
        return {
            "status": "idle",
            "scenarioId": None,
            "observation": None,
            "logs": [],
        }

    def start(self, scenario_id: str, **options: object) -> None:
        self.started = (scenario_id, options)

    def reset(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def refresh_observation(self) -> dict[str, object]:
        return {"GameState": {"Season": "spring"}}

    def start_recording(self, *, from_index: int | None = None) -> dict[str, object]:
        self.calls.append(("start_recording", from_index))
        return self.snapshot()

    def stop_recording(self) -> dict[str, object]:
        self.calls.append(("stop_recording", None))
        return self.snapshot()

    def execute_action(self, action: str, arguments: list[str]) -> dict[str, object]:
        self.calls.append(("execute_action", (action, arguments)))
        return {"action": action, "arguments": arguments, "result": True}

    def mark_snapshot(self) -> dict[str, object]:
        self.calls.append(("mark_snapshot", None))
        return {"pending": True}

    def save_marked_snapshot(self, name: str) -> dict[str, object]:
        self.calls.append(("save_marked_snapshot", name))
        return {"name": name}

    def cancel_marked_snapshot(self) -> None:
        self.calls.append(("cancel_marked_snapshot", None))

    def refresh_preview(self) -> dict[str, object]:
        return {"pixels": "AQIDBA==", "width": 1, "height": 1, "format": "rgba8"}

    def start_replay(self) -> dict[str, object]:
        self.calls.append(("start_replay", None))
        return self.snapshot()

    def pause_replay(self) -> dict[str, object]:
        self.calls.append(("pause_replay", None))
        return self.snapshot()

    def resume_replay(self) -> dict[str, object]:
        self.calls.append(("resume_replay", None))
        return self.snapshot()

    def step_replay(self) -> dict[str, object]:
        self.calls.append(("step_replay", None))
        return {"action": "move_step"}

    def stop_replay(self) -> dict[str, object]:
        self.calls.append(("stop_replay", None))
        return self.snapshot()

    def run_assertions(self) -> dict[str, object]:
        self.calls.append(("run_assertions", None))
        return {"passed": True, "total": 0, "passedCount": 0, "failedCount": 0, "results": []}


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.scenarios_dir = root / "scenarios"
        self.saves_dir = root / "saves"
        save = self.saves_dir / "TestFarm_123"
        save.mkdir(parents=True)
        (save / "SaveGameInfo").write_text(
            "<Farmer><farmName>TestFarm</farmName></Farmer>",
            encoding="utf-8",
        )
        (save / "TestFarm_123").write_text(
            "<SaveGame><player><farmName>TestFarm</farmName></player>"
            "<uniqueIDForThisGame>123</uniqueIDForThisGame></SaveGame>",
            encoding="utf-8",
        )
        self.controller = _FakeController()
        self.token = "test-token"
        self.frontend_dir = root / "frontend"
        self.frontend_dir.mkdir()
        (self.frontend_dir / "index.html").write_text(
            "<!doctype html><title>Stalley Scenario Harness</title>",
            encoding="utf-8",
        )
        self.app = create_app(
            scenarios_dir=self.scenarios_dir,
            saves_dir=self.saves_dir,
            controller=self.controller,
            token=self.token,
            frontend_dir=self.frontend_dir,
        )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        authorized: bool = True,
    ) -> tuple[int, dict[str, object]]:
        headers: dict[str, str] = {}
        if authorized:
            headers["X-Harness-Token"] = self.token
        response = self.client.request(
            method,
            path,
            headers=headers,
            json=payload,
        )
        return response.status_code, response.json()

    def test_bootstrap_lists_local_saves_and_current_run_state(self) -> None:
        status, body = self._json("/api/bootstrap")

        self.assertEqual(status, 200)
        self.assertEqual(body["saves"][0]["name"], "TestFarm_123")
        self.assertEqual(body["run"]["status"], "idle")
        self.assertTrue(body["capabilities"]["recording"])
        self.assertTrue(body["capabilities"]["replay"])
        self.assertTrue(body["capabilities"]["snapshots"])

    def test_import_and_start_can_be_driven_entirely_through_the_api(self) -> None:
        import_status, imported = self._json(
            "/api/scenarios/import",
            method="POST",
            payload={
                "saveName": "TestFarm_123",
                "scenarioId": "level-up-test",
                "name": "Level-up test",
                "description": "",
            },
        )
        start_status, _ = self._json(
            "/api/run/start",
            method="POST",
            payload={
                "scenarioId": "level-up-test",
                "port": 6123,
                "attach": False,
            },
        )

        self.assertEqual(import_status, 201)
        self.assertEqual(imported["scenario"]["id"], "level-up-test")
        self.assertEqual(start_status, 202)
        self.assertEqual(
            self.controller.started,
            (
                "level-up-test",
                {
                    "port": 6123,
                    "attach": False,
                    "sample_rate": 100,
                    "timeout": 90,
                },
            ),
        )

    def test_mutating_requests_require_the_page_token(self) -> None:
        status, body = self._json(
            "/api/run/start",
            method="POST",
            payload={"scenarioId": "anything"},
            authorized=False,
        )

        self.assertEqual(status, 403)
        self.assertIn("token", body["error"])

    def test_serves_the_harness_page_with_a_strict_content_security_policy(self) -> None:
        response = self.client.get("/")
        html = response.text

        self.assertIn("Stalley Scenario Harness", html)
        self.assertIn(
            "default-src 'self'",
            response.headers["content-security-policy"],
        )
        self.assertEqual(response.headers["x-frame-options"], "DENY")

    def test_record_action_snapshot_preview_and_replay_controls_are_exposed(self) -> None:
        endpoints = [
            ("/api/run/record/start", {"fromIndex": 2}),
            ("/api/run/actions", {"action": "move_step", "arguments": ["up"]}),
            ("/api/run/snapshots/mark", {}),
            ("/api/run/snapshots/save", {"name": "level-up-menu"}),
            ("/api/run/replay/start", {}),
            ("/api/run/replay/pause", {}),
            ("/api/run/replay/resume", {}),
            ("/api/run/replay/step", {}),
            ("/api/run/replay/stop", {}),
            ("/api/run/assertions", {}),
        ]

        statuses = [
            self._json(path, method="POST", payload=payload)[0]
            for path, payload in endpoints
        ]
        preview_status, preview = self._json("/api/run/preview", method="POST", payload={})

        self.assertTrue(all(status == 200 for status in statuses))
        self.assertEqual(preview_status, 200)
        self.assertEqual(preview["preview"]["width"], 1)
        self.assertIn(("execute_action", ("move_step", ["up"])), self.controller.calls)

    def test_assertions_can_be_saved_and_scenario_delete_is_recoverable(self) -> None:
        self._json(
            "/api/scenarios/import",
            method="POST",
            payload={
                "saveName": "TestFarm_123",
                "scenarioId": "delete-me",
                "name": "Delete me",
            },
        )
        assertion_status, _ = self._json(
            "/api/scenarios/delete-me/assertions",
            method="PUT",
            payload={
                "assertions": [
                    {
                        "id": "season",
                        "source": "observation",
                        "path": "/GameState/Season",
                        "operator": "equals",
                        "expected": "spring",
                    }
                ]
            },
        )
        delete_status, deleted = self._json(
            "/api/scenarios/delete-me/delete",
            method="POST",
            payload={"scenarioId": "delete-me"},
        )

        self.assertEqual(assertion_status, 200)
        self.assertEqual(delete_status, 200)
        self.assertEqual(deleted["deletedScenarioId"], "delete-me")
        self.assertFalse((self.scenarios_dir / "delete-me").exists())


if __name__ == "__main__":
    unittest.main()
