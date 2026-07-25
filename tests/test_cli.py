import contextlib
import io
import json
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from harness.cli import main


class _HarnessProtocolHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        request = self.request.recv(4096).decode("utf-8")
        self.server.requests.append(request)
        if request.startswith("load_game_record%"):
            response = "True"
        elif request == "observe_v2_light%-1":
            response = json.dumps({"CurrentMenuData": {"Type": "LevelUpMenu"}})
        else:
            response = ""
        self.request.sendall((response + "<EOF>").encode("utf-8"))


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.scenario_dir = root / "scenarios" / "level-up-non-profession"
        fixture_dir = self.scenario_dir / "save"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "SaveGameInfo").write_text(
            "<Farmer><farmName>TestFarm</farmName></Farmer>",
            encoding="utf-8",
        )
        (fixture_dir / "TestFarm_123").write_text(
            "<SaveGame><player><farmName>TestFarm</farmName></player>"
            "<uniqueIDForThisGame>123</uniqueIDForThisGame></SaveGame>",
            encoding="utf-8",
        )
        (self.scenario_dir / "scenario.json").write_text(
            json.dumps(
                {
                    "formatVersion": 1,
                    "id": "level-up-non-profession",
                    "name": "Ordinary level-up",
                    "fixture": {"saveFile": "TestFarm_123"},
                }
            ),
            encoding="utf-8",
        )
        self.saves_dir = root / "live-saves"

    def test_prepare_restores_the_fixture_without_launching_stardew(self) -> None:
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "prepare",
                    str(self.scenario_dir),
                    "--saves-dir",
                    str(self.saves_dir),
                    "--port",
                    "6123",
                ]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertRegex(result["runtimeSaveName"], r"^TestFarm_[1-9][0-9]+$")
        self.assertTrue(Path(result["path"]).is_dir())

    def test_run_can_attach_load_and_capture_the_exact_mod_observation(self) -> None:
        server = socketserver.ThreadingTCPServer(
            ("127.0.0.1", 0),
            _HarnessProtocolHandler,
        )
        server.requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        port = server.server_address[1]
        observation_path = Path(self.temp_dir.name) / "initial-observation.json"
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "run",
                    str(self.scenario_dir),
                    "--attach",
                    "--saves-dir",
                    str(self.saves_dir),
                    "--port",
                    str(port),
                    "--observation-output",
                    str(observation_path),
                    "--timeout",
                    "2",
                ]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["attached"])
        self.assertIsNone(result["pid"])
        self.assertEqual(
            json.loads(observation_path.read_text(encoding="utf-8")),
            {"CurrentMenuData": {"Type": "LevelUpMenu"}},
        )
        self.assertIn(
            f"load_game_record%{result['runtimeSaveName']}",
            server.requests,
        )

    def test_run_refuses_an_occupied_launch_port_before_resetting_the_fixture(self) -> None:
        occupied_server = socketserver.ThreadingTCPServer(
            ("127.0.0.1", 0),
            _HarnessProtocolHandler,
        )
        occupied_server.daemon_threads = True
        occupied_server.requests = []
        thread = threading.Thread(target=occupied_server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(occupied_server.shutdown)
        self.addCleanup(occupied_server.server_close)
        port = occupied_server.server_address[1]

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(
                    [
                        "prepare",
                        str(self.scenario_dir),
                        "--saves-dir",
                        str(self.saves_dir),
                        "--port",
                        str(port),
                    ]
                ),
                0,
            )
        runtime_dirs = [
            path
            for path in self.saves_dir.iterdir()
            if path.name.startswith("TestFarm_")
        ]
        self.assertEqual(len(runtime_dirs), 1)
        runtime_name = runtime_dirs[0].name
        runtime_save = self.saves_dir / runtime_name / runtime_name
        runtime_save.write_text("<SaveGame><changed /></SaveGame>", encoding="utf-8")
        fake_smapi = Path(self.temp_dir.name) / "StardewModdingAPI"
        fake_smapi.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_smapi.chmod(0o755)

        with contextlib.redirect_stderr(io.StringIO()):
            exit_code = main(
                [
                    "run",
                    str(self.scenario_dir),
                    "--saves-dir",
                    str(self.saves_dir),
                    "--port",
                    str(port),
                    "--smapi-path",
                    str(fake_smapi),
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            runtime_save.read_text(encoding="utf-8"),
            "<SaveGame><changed /></SaveGame>",
        )

    def test_attach_preflights_the_server_before_resetting_the_fixture(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(
                    [
                        "prepare",
                        str(self.scenario_dir),
                        "--saves-dir",
                        str(self.saves_dir),
                        "--port",
                        "6124",
                    ]
                ),
                0,
            )
        runtime_dir = next(self.saves_dir.iterdir())
        runtime_save = runtime_dir / runtime_dir.name
        runtime_save.write_text("<SaveGame><changed /></SaveGame>", encoding="utf-8")

        with contextlib.redirect_stderr(io.StringIO()):
            exit_code = main(
                [
                    "run",
                    str(self.scenario_dir),
                    "--attach",
                    "--saves-dir",
                    str(self.saves_dir),
                    "--port",
                    "6124",
                    "--timeout",
                    "0.01",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            runtime_save.read_text(encoding="utf-8"),
            "<SaveGame><changed /></SaveGame>",
        )

    def test_observation_output_refuses_to_overwrite_an_existing_file(self) -> None:
        observation_path = Path(self.temp_dir.name) / "observation.json"
        observation_path.write_text("keep me", encoding="utf-8")

        with contextlib.redirect_stderr(io.StringIO()):
            exit_code = main(
                [
                    "run",
                    str(self.scenario_dir),
                    "--attach",
                    "--saves-dir",
                    str(self.saves_dir),
                    "--port",
                    "6125",
                    "--observation-output",
                    str(observation_path),
                    "--timeout",
                    "0.01",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(observation_path.read_text(encoding="utf-8"), "keep me")
        self.assertFalse(self.saves_dir.exists())

    def test_run_terminates_a_process_it_launched_when_runtime_setup_fails(self) -> None:
        fake_smapi = Path(self.temp_dir.name) / "StardewModdingAPI"
        fake_smapi.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_smapi.chmod(0o755)
        process = mock.Mock(pid=4321)
        process.poll.return_value = None
        process.wait.return_value = 0

        with (
            mock.patch("harness.cli.launch_smapi", return_value=process),
            mock.patch(
                "harness.cli.ModClient.wait_for_server",
                side_effect=OSError("server failed"),
            ),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = main(
                [
                    "run",
                    str(self.scenario_dir),
                    "--saves-dir",
                    str(self.saves_dir),
                    "--port",
                    "6126",
                    "--smapi-path",
                    str(fake_smapi),
                ]
            )

        self.assertEqual(exit_code, 1)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once()

    def test_rejects_non_finite_timeout_at_the_cli_boundary(self) -> None:
        with (
            mock.patch(
                "harness.cli.launch_smapi",
                side_effect=AssertionError("invalid input reached launch"),
            ),
            self.assertRaises(SystemExit),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            main(["run", str(self.scenario_dir), "--timeout", "nan"])

    def test_ui_command_starts_the_local_web_harness(self) -> None:
        with mock.patch("harness.cli.serve_ui") as serve_ui:
            exit_code = main(
                [
                    "ui",
                    "--no-open",
                    "--port",
                    "8766",
                    "--scenarios-dir",
                    str(self.scenario_dir.parent),
                    "--saves-dir",
                    str(self.saves_dir),
                ]
            )

        self.assertEqual(exit_code, 0)
        serve_ui.assert_called_once_with(
            host="127.0.0.1",
            port=8766,
            scenarios_dir=self.scenario_dir.parent,
            saves_dir=self.saves_dir,
            smapi_path=None,
            open_browser=False,
        )


if __name__ == "__main__":
    unittest.main()
