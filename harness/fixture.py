from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import xml.etree.ElementTree as element_tree
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .scenario import Scenario


MARKER_FILENAME = ".stalleymod-harness.json"
_MANAGED_BY = "stalleymod-scenario-harness"
_MARKER_FORMAT_VERSION = 1
_UNIQUE_ID_XML = re.compile(
    rb"(<uniqueIDForThisGame>\s*)([0-9]+)(\s*</uniqueIDForThisGame>)"
)


class FixtureRestoreError(RuntimeError):
    """Raised when a fixture cannot be restored without risking user save data."""


@dataclass(frozen=True)
class RestoredFixture:
    path: Path
    runtime_save_name: str


def _runtime_save_name(scenario: Scenario, port: int) -> str:
    if type(port) is not int or not 1 <= port <= 65535:
        raise FixtureRestoreError("port must be an integer between 1 and 65535")
    seed = f"{scenario.id}\0{scenario.unique_id}\0{port}".encode("utf-8")
    runtime_id = int.from_bytes(hashlib.sha256(seed).digest()[:8], "big")
    runtime_id &= (1 << 63) - 1
    if runtime_id == 0 or runtime_id == scenario.unique_id:
        runtime_id = (runtime_id + 1) & ((1 << 63) - 1) or 1
    save_prefix = scenario.save_file.rsplit("_", maxsplit=1)[0]
    return f"{save_prefix}_{runtime_id}"


def _fixture_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.name == MARKER_FILENAME:
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as fixture_file:
            for chunk in iter(lambda: fixture_file.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _is_managed_runtime_save(
    path: Path,
    runtime_save_name: str,
    scenario_id: str,
) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    marker_path = path / MARKER_FILENAME
    try:
        marker_stat = marker_path.lstat()
    except OSError:
        return False
    if marker_path.is_symlink() or not stat.S_ISREG(marker_stat.st_mode):
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(marker, dict)
        and marker.get("managedBy") == _MANAGED_BY
        and marker.get("formatVersion") == _MARKER_FORMAT_VERSION
        and marker.get("runtimeSaveName") == runtime_save_name
        and marker.get("scenarioId") == scenario_id
        and isinstance(marker.get("fixtureSha256"), str)
        and len(marker["fixtureSha256"]) == 64
        and all(character in "0123456789abcdef" for character in marker["fixtureSha256"])
    )


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


@contextmanager
def _runtime_lock(saves_root: Path, runtime_save_name: str) -> Iterator[None]:
    lock_path = saves_root / f".{runtime_save_name}.stalleymod.lock"
    try:
        descriptor = os.open(
            lock_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as error:
        raise FixtureRestoreError(
            f"runtime save is locked by another harness process: {lock_path}"
        ) from error

    lock_identity = os.fstat(descriptor)
    try:
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        try:
            current_identity = lock_path.lstat()
            if (
                current_identity.st_dev == lock_identity.st_dev
                and current_identity.st_ino == lock_identity.st_ino
            ):
                lock_path.unlink()
        except OSError:
            pass


def _validate_copied_snapshot(
    directory: Path,
    scenario: Scenario,
) -> None:
    for child in directory.iterdir():
        if child.is_symlink() or not child.is_file():
            raise FixtureRestoreError(
                f"fixture changed during restore; expected a regular file: {child.name}"
            )
    try:
        save_root = element_tree.parse(directory / scenario.save_file).getroot()
        info_root = element_tree.parse(directory / "SaveGameInfo").getroot()
    except (OSError, element_tree.ParseError) as error:
        raise FixtureRestoreError("fixture XML changed during restore") from error
    unique_id_element = next(
        (
            child
            for child in save_root
            if child.tag.rsplit("}", maxsplit=1)[-1] == "uniqueIDForThisGame"
        ),
        None,
    )
    if (
        unique_id_element is None
        or unique_id_element.text != str(scenario.unique_id)
    ):
        raise FixtureRestoreError("fixture identity changed during restore")
    player = next(
        (
            child
            for child in save_root
            if child.tag.rsplit("}", maxsplit=1)[-1] == "player"
        ),
        None,
    )
    player_farm_name = (
        next(
            (
                child.text
                for child in player
                if child.tag.rsplit("}", maxsplit=1)[-1] == "farmName"
            ),
            None,
        )
        if player is not None
        else None
    )
    info_farm_name = next(
        (
            child.text
            for child in info_root
            if child.tag.rsplit("}", maxsplit=1)[-1] == "farmName"
        ),
        None,
    )
    if player_farm_name != scenario.farm_name or info_farm_name != scenario.farm_name:
        raise FixtureRestoreError("fixture farm identity changed during restore")


def _rewrite_unique_id(path: Path, unique_id: int) -> None:
    contents = path.read_bytes()
    matches = list(_UNIQUE_ID_XML.finditer(contents))
    if len(matches) != 1:
        raise FixtureRestoreError(
            f"save XML must have exactly one uniqueIDForThisGame: {path.name}"
        )
    replacement = (
        matches[0].group(1)
        + str(unique_id).encode("ascii")
        + matches[0].group(3)
    )
    path.write_bytes(
        contents[: matches[0].start()]
        + replacement
        + contents[matches[0].end() :]
    )


def _remove_if_same_directory(path: Path, identity: os.stat_result) -> None:
    try:
        current = path.lstat()
    except OSError:
        return
    if (
        stat.S_ISDIR(current.st_mode)
        and current.st_dev == identity.st_dev
        and current.st_ino == identity.st_ino
    ):
        shutil.rmtree(path)


def _install_snapshot(
    temporary: Path,
    target: Path,
    runtime_save_name: str,
    scenario_id: str,
) -> None:
    quarantine: Path | None = None
    if _lexists(target):
        if not _is_managed_runtime_save(target, runtime_save_name, scenario_id):
            raise FixtureRestoreError(
                f"refusing to replace {target}: existing path is not managed by this harness"
            )
        quarantine = target.parent / f".{runtime_save_name}.previous-{uuid.uuid4().hex}"
        target.rename(quarantine)
        quarantine_identity = quarantine.lstat()
        if not _is_managed_runtime_save(
            quarantine,
            runtime_save_name,
            scenario_id,
        ):
            if not _lexists(target):
                quarantine.rename(target)
            raise FixtureRestoreError(
                f"runtime save changed during replacement; preserved at {quarantine}"
            )

    try:
        target.mkdir()
        target_identity = target.lstat()
        for child in temporary.iterdir():
            child.rename(target / child.name)
        temporary.rmdir()
    except Exception as error:
        if "target_identity" in locals():
            _remove_if_same_directory(target, target_identity)
        if quarantine is not None and not _lexists(target):
            quarantine.rename(target)
        raise FixtureRestoreError(f"failed to install runtime save: {error}") from error

    if quarantine is not None:
        _remove_if_same_directory(quarantine, quarantine_identity)


def restore_fixture(
    scenario: Scenario,
    saves_dir: str | Path,
    *,
    port: int,
) -> RestoredFixture:
    runtime_save_name = _runtime_save_name(scenario, port)
    saves_root = Path(saves_dir).expanduser().resolve()
    target = saves_root / runtime_save_name
    if target.parent != saves_root:
        raise FixtureRestoreError("runtime save path escaped the configured save directory")

    saves_root.mkdir(parents=True, exist_ok=True)
    with _runtime_lock(saves_root, runtime_save_name):
        if _lexists(target) and not _is_managed_runtime_save(
            target,
            runtime_save_name,
            scenario.id,
        ):
            raise FixtureRestoreError(
                f"refusing to replace {target}: existing path is not managed by this harness"
            )

        temporary = Path(
            tempfile.mkdtemp(prefix=f".{runtime_save_name}.tmp-", dir=saves_root)
        )
        try:
            shutil.copytree(
                scenario.save_dir,
                temporary,
                dirs_exist_ok=True,
                symlinks=True,
            )
            _validate_copied_snapshot(temporary, scenario)
            fixture_digest = _fixture_digest(temporary)
            runtime_id = int(runtime_save_name.rsplit("_", maxsplit=1)[-1])

            source_save = temporary / scenario.save_file
            _rewrite_unique_id(source_save, runtime_id)
            runtime_save = temporary / runtime_save_name
            source_save.rename(runtime_save)

            old_source_save = temporary / f"{scenario.save_file}_old"
            if old_source_save.exists():
                _rewrite_unique_id(old_source_save, runtime_id)
                old_source_save.rename(temporary / f"{runtime_save_name}_old")

            marker = {
                "formatVersion": _MARKER_FORMAT_VERSION,
                "managedBy": _MANAGED_BY,
                "scenarioId": scenario.id,
                "runtimeSaveName": runtime_save_name,
                "fixtureSha256": fixture_digest,
            }
            (temporary / MARKER_FILENAME).write_text(
                json.dumps(marker, indent=2, sort_keys=True) + os.linesep,
                encoding="utf-8",
            )

            _install_snapshot(
                temporary,
                target,
                runtime_save_name,
                scenario.id,
            )
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    return RestoredFixture(path=target, runtime_save_name=runtime_save_name)


def restore_debug_checkpoint(
    source_dir: str | Path,
    source_save_name: str,
    checkpoint_id: str,
    saves_dir: str | Path,
    *,
    port: int,
) -> RestoredFixture:
    if type(port) is not int or not 1 <= port <= 65535:
        raise FixtureRestoreError("port must be an integer between 1 and 65535")
    source = Path(source_dir).resolve()
    source_save = source / source_save_name
    if (
        source_save.parent != source
        or source.is_symlink()
        or not source.is_dir()
        or not source_save.is_file()
    ):
        raise FixtureRestoreError("checkpoint save is incomplete")
    try:
        save_root = element_tree.parse(source_save).getroot()
        unique_id = int(
            next(
                child.text
                for child in save_root
                if child.tag.rsplit("}", maxsplit=1)[-1] == "uniqueIDForThisGame"
            )
        )
    except (OSError, ValueError, StopIteration, element_tree.ParseError) as error:
        raise FixtureRestoreError("checkpoint save identity is invalid") from error

    seed = f"debug\0{checkpoint_id}\0{unique_id}\0{port}".encode("utf-8")
    runtime_id = int.from_bytes(hashlib.sha256(seed).digest()[:8], "big")
    runtime_id &= (1 << 63) - 1
    if runtime_id in {0, unique_id}:
        runtime_id = (runtime_id + 1) & ((1 << 63) - 1) or 1
    save_prefix = source_save_name.rsplit("_", maxsplit=1)[0]
    runtime_save_name = f"{save_prefix}_{runtime_id}"
    fixture_id = f"debug:{checkpoint_id}"
    saves_root = Path(saves_dir).expanduser().resolve()
    target = saves_root / runtime_save_name

    saves_root.mkdir(parents=True, exist_ok=True)
    with _runtime_lock(saves_root, runtime_save_name):
        if _lexists(target) and not _is_managed_runtime_save(
            target,
            runtime_save_name,
            fixture_id,
        ):
            raise FixtureRestoreError(
                f"refusing to replace {target}: existing path is not managed by this harness"
            )
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{runtime_save_name}.tmp-", dir=saves_root)
        )
        try:
            shutil.copytree(source, temporary, dirs_exist_ok=True, symlinks=True)
            for child in temporary.iterdir():
                if child.is_symlink() or not child.is_file():
                    raise FixtureRestoreError(
                        f"checkpoint must contain regular files: {child.name}"
                    )
            fixture_digest = _fixture_digest(temporary)
            copied_save = temporary / source_save_name
            _rewrite_unique_id(copied_save, runtime_id)
            copied_save.rename(temporary / runtime_save_name)
            old_save = temporary / f"{source_save_name}_old"
            if old_save.exists():
                _rewrite_unique_id(old_save, runtime_id)
                old_save.rename(temporary / f"{runtime_save_name}_old")
            (temporary / MARKER_FILENAME).write_text(
                json.dumps(
                    {
                        "formatVersion": _MARKER_FORMAT_VERSION,
                        "managedBy": _MANAGED_BY,
                        "scenarioId": fixture_id,
                        "runtimeSaveName": runtime_save_name,
                        "fixtureSha256": fixture_digest,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + os.linesep,
                encoding="utf-8",
            )
            _install_snapshot(
                temporary,
                target,
                runtime_save_name,
                fixture_id,
            )
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    return RestoredFixture(path=target, runtime_save_name=runtime_save_name)
