import json
import tempfile
import unittest
from pathlib import Path

from harness.catalog import (
    ScenarioCatalogError,
    delete_scenario,
    discover_saves,
    import_save_as_scenario,
    list_scenarios,
    scenario_details,
)


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.saves_dir = root / "saves"
        self.scenarios_dir = root / "scenarios"
        save_dir = self.saves_dir / "TestFarm_123"
        save_dir.mkdir(parents=True)
        (save_dir / "SaveGameInfo").write_text(
            "<Farmer><farmName>TestFarm</farmName></Farmer>",
            encoding="utf-8",
        )
        (save_dir / "TestFarm_123").write_text(
            "<SaveGame><player><farmName>TestFarm</farmName></player>"
            "<uniqueIDForThisGame>123</uniqueIDForThisGame></SaveGame>",
            encoding="utf-8",
        )

    def test_discovers_local_stardew_saves_without_modifying_them(self) -> None:
        saves = discover_saves(self.saves_dir)

        self.assertEqual(
            saves,
            [
                {
                    "name": "TestFarm_123",
                    "farmName": "TestFarm",
                    "uniqueId": 123,
                }
            ],
        )
        self.assertFalse((self.saves_dir / "TestFarm_123" / "scenario.json").exists())

    def test_discovery_hides_runtime_saves_created_by_the_harness(self) -> None:
        runtime = self.saves_dir / "RuntimeFarm_456"
        runtime.mkdir()
        (runtime / "SaveGameInfo").write_text(
            "<Farmer><farmName>RuntimeFarm</farmName></Farmer>",
            encoding="utf-8",
        )
        (runtime / "RuntimeFarm_456").write_text(
            "<SaveGame><player><farmName>RuntimeFarm</farmName></player>"
            "<uniqueIDForThisGame>456</uniqueIDForThisGame></SaveGame>",
            encoding="utf-8",
        )
        (runtime / ".stalleymod-harness.json").write_text(
            '{"managedBy":"stalleymod-scenario-harness"}',
            encoding="utf-8",
        )

        saves = discover_saves(self.saves_dir)

        self.assertEqual([save["name"] for save in saves], ["TestFarm_123"])

    def test_imports_a_save_as_a_valid_scenario_fixture(self) -> None:
        scenario = import_save_as_scenario(
            saves_dir=self.saves_dir,
            scenarios_dir=self.scenarios_dir,
            save_name="TestFarm_123",
            scenario_id="level-up-test",
            name="Level-up test",
            description="Reproduce the farming level-up.",
        )

        self.assertEqual(scenario.id, "level-up-test")
        self.assertEqual(scenario.save_file, "TestFarm_123")
        self.assertTrue(
            (
                self.scenarios_dir
                / "level-up-test"
                / "save"
                / "TestFarm_123"
            ).is_file()
        )
        metadata = json.loads(
            (
                self.scenarios_dir / "level-up-test" / "scenario.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["name"], "Level-up test")

    def test_import_refuses_to_replace_an_existing_scenario(self) -> None:
        destination = self.scenarios_dir / "level-up-test"
        destination.mkdir(parents=True)
        precious = destination / "notes.txt"
        precious.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(ScenarioCatalogError, "already exists"):
            import_save_as_scenario(
                saves_dir=self.saves_dir,
                scenarios_dir=self.scenarios_dir,
                save_name="TestFarm_123",
                scenario_id="level-up-test",
                name="Level-up test",
            )

        self.assertEqual(precious.read_text(encoding="utf-8"), "keep")

    def test_list_scenarios_surfaces_invalid_entries_without_hiding_valid_ones(self) -> None:
        import_save_as_scenario(
            saves_dir=self.saves_dir,
            scenarios_dir=self.scenarios_dir,
            save_name="TestFarm_123",
            scenario_id="valid-scenario",
            name="Valid scenario",
        )
        invalid = self.scenarios_dir / "broken-scenario"
        invalid.mkdir()
        (invalid / "scenario.json").write_text("not json", encoding="utf-8")

        catalog = list_scenarios(self.scenarios_dir)

        self.assertEqual([item["id"] for item in catalog["scenarios"]], ["valid-scenario"])
        self.assertEqual(catalog["errors"][0]["id"], "broken-scenario")

    def test_scenario_details_include_recorded_actions_and_snapshots(self) -> None:
        scenario = import_save_as_scenario(
            saves_dir=self.saves_dir,
            scenarios_dir=self.scenarios_dir,
            save_name="TestFarm_123",
            scenario_id="recorded-scenario",
            name="Recorded scenario",
        )
        (scenario.path / "actions.jsonl").write_text(
            '{"action":"move","arguments":{"direction":"up"}}\n'
            '{"action":"sleep","result":true}\n',
            encoding="utf-8",
        )
        snapshots = scenario.path / "snapshots"
        snapshots.mkdir()
        (snapshots / "level-up-menu.json").write_text(
            '{"CurrentMenuData":{"Type":"LevelUpMenu"}}',
            encoding="utf-8",
        )

        details = scenario_details(scenario)

        self.assertEqual(details["actions"][0]["action"], "move")
        self.assertEqual(details["snapshots"][0]["name"], "level-up-menu")
        self.assertEqual(
            details["snapshots"][0]["observation"]["CurrentMenuData"]["Type"],
            "LevelUpMenu",
        )

    def test_delete_moves_only_the_selected_scenario_to_recoverable_trash(self) -> None:
        scenario = import_save_as_scenario(
            saves_dir=self.saves_dir,
            scenarios_dir=self.scenarios_dir,
            save_name="TestFarm_123",
            scenario_id="delete-me",
            name="Delete me",
        )
        keep = import_save_as_scenario(
            saves_dir=self.saves_dir,
            scenarios_dir=self.scenarios_dir,
            save_name="TestFarm_123",
            scenario_id="keep-me",
            name="Keep me",
        )

        trashed = delete_scenario(self.scenarios_dir, "delete-me")

        self.assertFalse(scenario.path.exists())
        self.assertTrue(trashed.is_dir())
        self.assertEqual(trashed.parent, (self.scenarios_dir / ".trash").resolve())
        self.assertTrue(keep.path.is_dir())

    def test_delete_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(ScenarioCatalogError, "invalid"):
            delete_scenario(self.scenarios_dir, "../outside")

    def test_delete_refuses_a_symlinked_trash_directory(self) -> None:
        import_save_as_scenario(
            saves_dir=self.saves_dir,
            scenarios_dir=self.scenarios_dir,
            save_name="TestFarm_123",
            scenario_id="delete-me",
            name="Delete me",
        )
        outside = Path(self.temp_dir.name) / "outside-trash"
        outside.mkdir()
        (self.scenarios_dir / ".trash").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ScenarioCatalogError, "trash"):
            delete_scenario(self.scenarios_dir, "delete-me")

        self.assertTrue((self.scenarios_dir / "delete-me").is_dir())


if __name__ == "__main__":
    unittest.main()
