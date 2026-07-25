import time
import unittest

from harness.suite import RegressionSuite


class _SuiteController:
    def __init__(self) -> None:
        self.scenario_id: str | None = None
        self.status = "idle"
        self.replay_status = "idle"

    def start(self, scenario_id: str, **_options: object) -> None:
        self.scenario_id = scenario_id
        self.status = "ready"
        self.replay_status = "idle"

    def snapshot(self) -> dict[str, object]:
        return {
            "status": self.status,
            "scenarioId": self.scenario_id,
            "error": None,
            "observation": {"scenario": self.scenario_id},
            "replay": {
                "status": self.replay_status,
                "total": 1,
                "nextIndex": 1 if self.replay_status == "completed" else 0,
                "results": [],
            },
        }

    def start_replay(self) -> dict[str, object]:
        self.replay_status = "completed"
        return self.snapshot()

    def run_assertions(self) -> dict[str, object]:
        passed = self.scenario_id != "failing"
        return {
            "passed": passed,
            "total": 1,
            "passedCount": int(passed),
            "failedCount": int(not passed),
            "results": [],
        }

    def stop(self) -> None:
        self.status = "idle"


class RegressionSuiteTests(unittest.TestCase):
    def test_suite_runs_scenarios_sequentially_and_reports_failures(self) -> None:
        controller = _SuiteController()
        suite = RegressionSuite(controller)

        suite.start(["passing", "failing"], port=6123, timeout=1)
        deadline = time.monotonic() + 2
        while suite.snapshot()["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.01)
        report = suite.snapshot()

        self.assertEqual(report["status"], "completed")
        self.assertFalse(report["passed"])
        self.assertEqual(
            [result["status"] for result in report["results"]],
            ["passed", "failed"],
        )
        self.assertEqual(report["completedCount"], 2)

    def test_suite_rejects_duplicate_or_empty_scenario_lists(self) -> None:
        suite = RegressionSuite(_SuiteController())

        with self.assertRaisesRegex(ValueError, "at least one"):
            suite.start([])
        with self.assertRaisesRegex(ValueError, "unique"):
            suite.start(["same", "same"])


if __name__ == "__main__":
    unittest.main()
