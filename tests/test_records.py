import json
import tempfile
import unittest
from pathlib import Path

from harness.records import (
    RecordError,
    append_action,
    delete_snapshot,
    evaluate_assertions,
    load_actions,
    load_assertions,
    load_checkpoints,
    replace_assertions,
    save_snapshot,
    truncate_actions,
)


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.scenario_dir = Path(self.temp_dir.name) / "scenario"
        self.scenario_dir.mkdir()

    def test_action_records_round_trip_and_can_be_truncated_for_rerecording(self) -> None:
        append_action(
            self.scenario_dir,
            {
                "id": "first",
                "action": "move_step",
                "arguments": ["up"],
                "recordedAt": "2026-07-24T13:00:00+08:00",
                "durationMs": 12,
                "result": True,
                "resultRaw": "True",
                "error": None,
            },
        )
        append_action(
            self.scenario_dir,
            {
                "id": "second",
                "action": "interact",
                "arguments": [],
                "recordedAt": "2026-07-24T13:00:01+08:00",
                "durationMs": 4,
                "result": None,
                "resultRaw": "Message received",
                "error": None,
            },
        )

        self.assertEqual([action["id"] for action in load_actions(self.scenario_dir)], ["first", "second"])

        truncate_actions(self.scenario_dir, 1)

        self.assertEqual([action["id"] for action in load_actions(self.scenario_dir)], ["first"])

    def test_snapshot_preserves_the_exact_agent_observation_and_delete_is_explicit(self) -> None:
        raw = '{\n  "CurrentMenuData": {"type": "LevelUpMenu"}\n}'

        path = save_snapshot(
            self.scenario_dir,
            "level-up-menu",
            raw,
            captured_at="2026-07-24T13:00:00+08:00",
            after_action=2,
        )

        self.assertEqual(path.read_text(encoding="utf-8"), raw)
        self.assertEqual(
            load_checkpoints(self.scenario_dir)["level-up-menu"]["afterAction"],
            2,
        )
        with self.assertRaisesRegex(RecordError, "already exists"):
            save_snapshot(self.scenario_dir, "level-up-menu", raw)
        delete_snapshot(self.scenario_dir, "level-up-menu")
        self.assertFalse(path.exists())
        self.assertNotIn("level-up-menu", load_checkpoints(self.scenario_dir))

    def test_assertions_evaluate_observation_and_action_results(self) -> None:
        assertions = [
            {
                "id": "menu-type",
                "source": "observation",
                "path": "/CurrentMenuData/type",
                "operator": "equals",
                "expected": "LevelUpMenu",
            },
            {
                "id": "first-action-succeeded",
                "source": "action",
                "actionIndex": 0,
                "path": "/result",
                "operator": "equals",
                "expected": True,
            },
            {
                "id": "has-options",
                "source": "observation",
                "path": "/CurrentMenuData/options",
                "operator": "contains",
                "expected": "OK",
            },
        ]
        replace_assertions(self.scenario_dir, assertions)

        loaded = load_assertions(self.scenario_dir)
        report = evaluate_assertions(
            loaded,
            observation={
                "CurrentMenuData": {
                    "type": "LevelUpMenu",
                    "options": ["OK"],
                }
            },
            actions=[{"result": True}],
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["passedCount"], 3)
        self.assertEqual(report["failedCount"], 0)
        self.assertEqual(report["results"][0]["actual"], "LevelUpMenu")

    def test_assertion_validation_rejects_unsafe_or_ambiguous_shapes(self) -> None:
        with self.assertRaisesRegex(RecordError, "JSON Pointer"):
            replace_assertions(
                self.scenario_dir,
                [
                    {
                        "id": "bad",
                        "source": "observation",
                        "path": "CurrentMenuData.type",
                        "operator": "equals",
                        "expected": "LevelUpMenu",
                    }
                ],
            )

        with self.assertRaisesRegex(RecordError, "actionIndex"):
            replace_assertions(
                self.scenario_dir,
                [
                    {
                        "id": "bad-action",
                        "source": "action",
                        "path": "/result",
                        "operator": "exists",
                    }
                ],
            )

    def test_invalid_action_file_is_reported_instead_of_replayed(self) -> None:
        (self.scenario_dir / "actions.jsonl").write_text(
            json.dumps({"action": "move%up", "arguments": []}) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RecordError, "line 1"):
            load_actions(self.scenario_dir)


if __name__ == "__main__":
    unittest.main()
