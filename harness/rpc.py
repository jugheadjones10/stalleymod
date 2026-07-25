from __future__ import annotations

import json
import math
import socket
import time


_EOF = b"<EOF>"
_MAX_COMMAND_BYTES = 255
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class ModProtocolError(RuntimeError):
    """Raised when the mod RPC protocol is malformed or returns an invalid response."""


class ModConnectionError(RuntimeError):
    """Raised when the harness cannot communicate with the mod."""


class ModClient:
    def __init__(
        self,
        *,
        port: int,
        host: str = "127.0.0.1",
        command_timeout: float = 30,
    ) -> None:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        if not math.isfinite(command_timeout) or command_timeout <= 0:
            raise ValueError("command_timeout must be greater than zero")
        self.host = host
        self.port = port
        self.command_timeout = command_timeout

    def send(self, command: str, *, timeout: float | None = None) -> str:
        if not isinstance(command, str) or not command:
            raise ModProtocolError("command must be a non-empty string")
        if "\n" in command or "\r" in command or "\0" in command:
            raise ModProtocolError("command may not contain a newline or NUL byte")
        encoded = command.encode("utf-8")
        if len(encoded) > _MAX_COMMAND_BYTES:
            raise ModProtocolError("command exceeds the mod's 255-byte protocol limit")
        effective_timeout = self.command_timeout if timeout is None else timeout
        if not math.isfinite(effective_timeout) or effective_timeout <= 0:
            raise ModConnectionError("mod command deadline expired")

        try:
            with socket.create_connection(
                (self.host, self.port),
                timeout=effective_timeout,
            ) as connection:
                connection.settimeout(effective_timeout)
                connection.sendall(encoded)
                response = bytearray()
                while not response.endswith(_EOF):
                    chunk = connection.recv(64 * 1024)
                    if not chunk:
                        raise ModProtocolError("mod closed the connection before <EOF>")
                    response.extend(chunk)
                    if len(response) > _MAX_RESPONSE_BYTES:
                        raise ModProtocolError("mod response exceeds the 64 MiB protocol limit")
        except ModProtocolError:
            raise
        except (OSError, TimeoutError) as error:
            raise ModConnectionError(
                f"could not communicate with mod at {self.host}:{self.port}: {error}"
            ) from error

        payload = bytes(response[: -len(_EOF)])
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ModProtocolError("mod response is not valid UTF-8") from error

    def wait_for_server(self, *, timeout: float = 30, poll_interval: float = 0.25) -> None:
        if (
            not math.isfinite(timeout)
            or not math.isfinite(poll_interval)
            or timeout <= 0
            or poll_interval < 0
        ):
            raise ValueError("timeout must be positive and poll_interval must not be negative")
        deadline = time.monotonic() + timeout
        while True:
            try:
                with socket.create_connection(
                    (self.host, self.port),
                    timeout=min(1, timeout),
                ):
                    return
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise ModConnectionError(
                        f"mod did not listen on {self.host}:{self.port} within {timeout:g}s"
                    ) from error
                time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))

    def load_fixture_until_ready(
        self,
        runtime_save_name: str,
        *,
        surroundings_size: int,
        timeout: float = 90,
        poll_interval: float = 0.5,
    ) -> str:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and greater than zero")
        deadline = time.monotonic() + timeout

        load_response = self.send(
            f"load_game_record%{runtime_save_name}",
            timeout=max(0, deadline - time.monotonic()),
        )
        if load_response.strip().lower() != "true":
            raise ModProtocolError(
                f"load_game_record failed for {runtime_save_name!r}: {load_response!r}"
            )

        last_error = "observation was empty"
        observation_command = f"observe_v2_light%{surroundings_size}"
        while True:
            try:
                raw_observation = self.send(
                    observation_command,
                    timeout=max(0, deadline - time.monotonic()),
                )
                parsed = json.loads(raw_observation)
                if isinstance(parsed, dict):
                    return raw_observation
                last_error = "observation root was not a JSON object"
            except (json.JSONDecodeError, ModConnectionError, ModProtocolError) as error:
                last_error = str(error)

            if time.monotonic() >= deadline:
                raise ModProtocolError(
                    f"world did not produce a valid observation within {timeout:g}s: {last_error}"
                )
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
