from __future__ import annotations

import os
import platform
import socket
import subprocess
from pathlib import Path


class HarnessRuntimeError(RuntimeError):
    """Raised when Stardew/SMAPI runtime configuration is invalid."""


def default_saves_dir() -> Path:
    if platform.system() == "Windows":
        app_data = os.environ.get("APPDATA")
        if not app_data:
            raise HarnessRuntimeError(
                "APPDATA is required to locate Stardew Valley saves on Windows"
            )
        return Path(app_data) / "StardewValley" / "Saves"
    if platform.system() in {"Darwin", "Linux"}:
        return Path.home() / ".config" / "StardewValley" / "Saves"
    raise HarnessRuntimeError(f"unsupported operating system: {platform.system()}")


def resolve_smapi_path(configured_path: str | Path | None) -> Path:
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    if os.environ.get("STARDEW_APP_PATH"):
        candidates.append(Path(os.environ["STARDEW_APP_PATH"]).expanduser())
    if platform.system() == "Darwin":
        candidates.append(
            Path.home()
            / "Library/Application Support/Steam/steamapps/common"
            / "Stardew Valley/Contents/MacOS/StardewModdingAPI"
        )

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise HarnessRuntimeError(
        "SMAPI executable not found; pass --smapi-path or set STARDEW_APP_PATH"
    )


def ensure_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise HarnessRuntimeError(
                f"port {port} is already in use; choose another port or pass --attach"
            )


def launch_smapi(
    executable: Path,
    *,
    port: int,
    sample_rate: int = 100,
    capture_output: bool = False,
) -> subprocess.Popen[bytes]:
    if not 1 <= sample_rate <= 100:
        raise HarnessRuntimeError("sample rate must be between 1 and 100")
    ensure_port_available(port)
    try:
        return subprocess.Popen(
            [
                str(executable),
                "--port-id",
                str(port),
                "--sample-rate",
                str(sample_rate),
            ],
            cwd=executable.parent,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.STDOUT if capture_output else None,
        )
    except OSError as error:
        raise HarnessRuntimeError(f"failed to launch SMAPI: {error}") from error


def terminate_launched_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        return
