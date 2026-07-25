import json
import tempfile
import unittest
from pathlib import Path

from harness.fixture import FixtureRestoreError, restore_fixture
from harness.scenario import load_scenario


class FixtureRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.scenario_dir = root / "scenarios" / "level-up-non-profession"
        save_dir = self.scenario_dir / "save"
        save_dir.mkdir(parents=True)
        (save_dir / "SaveGameInfo").write_text(
            "<Farmer><farmName>TestFarm</farmName></Farmer>",
            encoding="utf-8",
        )
        (save_dir / "TestFarm_123").write_text(
            "<SaveGame><player><farmName>TestFarm</farmName></player>"
            "<uniqueIDForThisGame>123</uniqueIDForThisGame>"
            "<dayOfMonth>2</dayOfMonth></SaveGame>",
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
        self.scenario = load_scenario(self.scenario_dir)
        self.saves_dir = root / "live-saves"

    def test_restores_to_a_port_scoped_runtime_save(self) -> None:
        restored = restore_fixture(self.scenario, self.saves_dir, port=6000)

        self.assertRegex(restored.runtime_save_name, r"^TestFarm_[1-9][0-9]+$")
        self.assertNotEqual(restored.runtime_save_name, "TestFarm_123")
        self.assertTrue((restored.path / restored.runtime_save_name).is_file())
        self.assertTrue((restored.path / "SaveGameInfo").is_file())
        runtime_xml = (restored.path / restored.runtime_save_name).read_text(
            encoding="utf-8"
        )
        runtime_id = restored.runtime_save_name.removeprefix("TestFarm_")
        self.assertIn(
            f"<uniqueIDForThisGame>{runtime_id}</uniqueIDForThisGame>",
            runtime_xml,
        )
        marker = json.loads(
            (restored.path / ".stalleymod-harness.json").read_text(encoding="utf-8")
        )
        self.assertEqual(marker["scenarioId"], "level-up-non-profession")
        self.assertIn("<uniqueIDForThisGame>123</uniqueIDForThisGame>", (
            self.scenario_dir / "save" / "TestFarm_123"
        ).read_text(encoding="utf-8"))

    def test_repeated_restore_discards_changes_from_the_previous_run(self) -> None:
        first = restore_fixture(self.scenario, self.saves_dir, port=6000)
        runtime_save = first.path / first.runtime_save_name
        runtime_save.write_text("<SaveGame><changed /></SaveGame>", encoding="utf-8")

        second = restore_fixture(self.scenario, self.saves_dir, port=6000)

        self.assertIn(
            "<dayOfMonth>2</dayOfMonth>",
            (second.path / second.runtime_save_name).read_text(encoding="utf-8"),
        )

    def test_identity_rewrite_preserves_xml_namespace_declarations(self) -> None:
        source = self.scenario_dir / "save" / "TestFarm_123"
        source.write_text(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<SaveGame xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            "<player><farmName>TestFarm</farmName></player>"
            '<param xsi:type="xsd:int">4</param>'
            "<uniqueIDForThisGame>123</uniqueIDForThisGame>"
            "</SaveGame>",
            encoding="utf-8",
        )
        self.scenario = load_scenario(self.scenario_dir)

        restored = restore_fixture(self.scenario, self.saves_dir, port=6000)
        runtime_xml = (restored.path / restored.runtime_save_name).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema"',
            runtime_xml,
        )
        self.assertIn('xsi:type="xsd:int"', runtime_xml)

    def test_refuses_to_delete_an_unmanaged_save_with_the_runtime_name(self) -> None:
        restored = restore_fixture(self.scenario, self.saves_dir, port=6000)
        collision = restored.path
        for child in collision.iterdir():
            child.unlink()
        (collision / "precious-save").write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(FixtureRestoreError, "not managed"):
            restore_fixture(self.scenario, self.saves_dir, port=6000)

        self.assertEqual((collision / "precious-save").read_text(encoding="utf-8"), "keep")

    def test_rejects_an_invalid_port_before_touching_the_save_directory(self) -> None:
        with self.assertRaisesRegex(FixtureRestoreError, "port"):
            restore_fixture(self.scenario, self.saves_dir, port=0)

        self.assertFalse(self.saves_dir.exists())

    def test_different_ports_receive_different_canonical_save_identities(self) -> None:
        first = restore_fixture(self.scenario, self.saves_dir, port=6000)
        second = restore_fixture(self.scenario, self.saves_dir, port=6001)

        self.assertNotEqual(first.runtime_save_name, second.runtime_save_name)

    def test_runtime_identity_uses_the_save_filename_prefix(self) -> None:
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
        self.scenario = load_scenario(self.scenario_dir)

        restored = restore_fixture(self.scenario, self.saves_dir, port=6000)

        self.assertRegex(restored.runtime_save_name, r"^TestFarm_[1-9][0-9]+$")

    def test_refuses_a_fixture_file_replaced_by_a_symlink_after_validation(self) -> None:
        outside = Path(self.temp_dir.name) / "outside-save"
        outside.write_text(
            "<SaveGame><player><farmName>TestFarm</farmName></player>"
            "<uniqueIDForThisGame>123</uniqueIDForThisGame></SaveGame>",
            encoding="utf-8",
        )
        source = self.scenario_dir / "save" / "TestFarm_123"
        source.unlink()
        source.symlink_to(outside)

        with self.assertRaisesRegex(FixtureRestoreError, "regular file"):
            restore_fixture(self.scenario, self.saves_dir, port=6000)

        self.assertEqual(outside.read_text(encoding="utf-8").count("123"), 1)
        self.assertFalse(
            any(
                path.is_dir() and not path.name.startswith(".")
                for path in self.saves_dir.iterdir()
            )
        )

    def test_runtime_lock_prevents_concurrent_reset_of_the_same_identity(self) -> None:
        restored = restore_fixture(self.scenario, self.saves_dir, port=6000)
        runtime_save = restored.path / restored.runtime_save_name
        runtime_save.write_text("<SaveGame><changed /></SaveGame>", encoding="utf-8")
        lock = self.saves_dir / (
            f".{restored.runtime_save_name}.stalleymod.lock"
        )
        lock.write_text("another process\n", encoding="utf-8")

        with self.assertRaisesRegex(FixtureRestoreError, "locked"):
            restore_fixture(self.scenario, self.saves_dir, port=6000)

        self.assertEqual(
            runtime_save.read_text(encoding="utf-8"),
            "<SaveGame><changed /></SaveGame>",
        )

    def test_symlinked_ownership_marker_does_not_authorize_deletion(self) -> None:
        restored = restore_fixture(self.scenario, self.saves_dir, port=6000)
        marker = restored.path / ".stalleymod-harness.json"
        marker_contents = marker.read_text(encoding="utf-8")
        external_marker = Path(self.temp_dir.name) / "external-marker.json"
        external_marker.write_text(marker_contents, encoding="utf-8")
        marker.unlink()
        marker.symlink_to(external_marker)
        precious = restored.path / "precious"
        precious.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(FixtureRestoreError, "not managed"):
            restore_fixture(self.scenario, self.saves_dir, port=6000)

        self.assertEqual(precious.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
