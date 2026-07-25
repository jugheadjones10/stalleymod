import unittest
from pathlib import Path


class ModServerSafetyTests(unittest.TestCase):
    def test_tcp_handler_does_not_read_game_state_before_main_thread_dispatch(self) -> None:
        source = (
            Path(__file__).resolve().parent.parent / "ModEntry.cs"
        ).read_text(encoding="utf-8-sig")
        handler = source.split(
            "private async Task HandleClientAsync(TcpClient client)",
            maxsplit=1,
        )[1]
        before_dispatch = handler.split(
            "object? returnValue = await HandleMessage(data);",
            maxsplit=1,
        )[0]

        self.assertNotIn("Game1.", before_dispatch)


if __name__ == "__main__":
    unittest.main()
