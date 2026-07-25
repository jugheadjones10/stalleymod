import json
import tempfile
import unittest
from pathlib import Path

from harness.scenario import ScenarioError, load_scenario


class ScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.scenario_dir = Path(self.temp_dir.name) / "level-up-non-profession"
        save_dir = self.scenario_dir / "save"
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
        (self.scenario_dir / "scenario.json").write_text(
            json.dumps(
                {
                    "$schema": "../scenario.schema.json",
                    "formatVersion": 1,
                    "id": "level-up-non-profession",
                    "name": "Ordinary level-up",
                    "description": "A level-up menu with an explicit OK choice.",
                    "fixture": {"saveFile": "TestFarm_123"},
                    "observation": {"surroundingsSize": -1},
                    "expectedStart": {"season": "spring", "day": 2},
                }
            ),
            encoding="utf-8",
        )

    def test_loads_a_valid_scenario_contract(self) -> None:
        scenario = load_scenario(self.scenario_dir)

        self.assertEqual(scenario.id, "level-up-non-profession")
        self.assertEqual(scenario.save_file, "TestFarm_123")
        self.assertEqual(scenario.surroundings_size, -1)

    def test_save_filename_prefix_may_differ_from_farm_name(self) -> None:
        save_dir = self.scenario_dir / "save"
        (save_dir / "TestFarm_123").write_text(
            "<SaveGame><player><farmName>Different Farm</farmName></player>"
            "<uniqueIDForThisGame>123</uniqueIDForThisGame></SaveGame>",
            encoding="utf-8",
        )
        (save_dir / "SaveGameInfo").write_text(
            "<Farmer><farmName>Different Farm</farmName></Farmer>",
            encoding="utf-8",
        )

        scenario = load_scenario(self.scenario_dir)

        self.assertEqual(scenario.save_file, "TestFarm_123")
        self.assertEqual(scenario.farm_name, "Different Farm")
        self.assertEqual(scenario.expected_start, {"season": "spring", "day": 2})

    def test_rejects_a_save_filename_that_can_escape_the_fixture(self) -> None:
        metadata_path = self.scenario_dir / "scenario.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["fixture"]["saveFile"] = "../real-save"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        with self.assertRaisesRegex(ScenarioError, "fixture.saveFile"):
            load_scenario(self.scenario_dir)

    def test_rejects_a_scenario_whose_id_does_not_match_its_directory(self) -> None:
        metadata_path = self.scenario_dir / "scenario.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["id"] = "different-scenario"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        with self.assertRaisesRegex(ScenarioError, "directory name"):
            load_scenario(self.scenario_dir)

    def test_rejects_a_non_string_schema_reference(self) -> None:
        metadata_path = self.scenario_dir / "scenario.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["$schema"] = {"unexpected": "object"}
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        with self.assertRaisesRegex(ScenarioError, r"\$schema"):
            load_scenario(self.scenario_dir)

    def test_rejects_save_game_info_as_the_main_save_file(self) -> None:
        metadata_path = self.scenario_dir / "scenario.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["fixture"]["saveFile"] = "SaveGameInfo"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        with self.assertRaisesRegex(ScenarioError, "distinct"):
            load_scenario(self.scenario_dir)

    def test_rejects_missing_or_malformed_save_xml(self) -> None:
        (self.scenario_dir / "save" / "SaveGameInfo").write_text(
            "<Farmer>",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ScenarioError, "valid XML"):
            load_scenario(self.scenario_dir)


if __name__ == "__main__":
    unittest.main()
