import json
import socketserver
import threading
import unittest

from harness.rpc import ModClient, ModProtocolError


class _ProtocolHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        request = self.request.recv(4096).decode("utf-8")
        self.server.requests.append(request)
        responses = self.server.responses.setdefault(request, [])
        response = responses.pop(0) if responses else "unknown"
        self.request.sendall((response + "<EOF>").encode("utf-8"))


class ModClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _ProtocolHandler)
        self.server.requests = []
        self.server.responses = {}
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.client = ModClient(port=self.server.server_address[1], command_timeout=2)

    def test_sends_the_existing_percent_delimited_mod_protocol(self) -> None:
        self.server.responses["load_game_record%TestFarm_123"] = ["True"]

        response = self.client.send("load_game_record%TestFarm_123")

        self.assertEqual(response, "True")
        self.assertEqual(self.server.requests, ["load_game_record%TestFarm_123"])

    def test_loads_once_then_polls_the_normal_observation_until_json_is_ready(self) -> None:
        self.server.responses["load_game_record%TestFarm_123"] = ["True"]
        self.server.responses["observe_v2_light%-1"] = [
            "",
            json.dumps({"CurrentMenuData": {"Type": "LevelUpMenu"}}),
        ]

        observation = self.client.load_fixture_until_ready(
            "TestFarm_123",
            surroundings_size=-1,
            timeout=2,
            poll_interval=0,
        )

        self.assertEqual(
            json.loads(observation)["CurrentMenuData"]["Type"],
            "LevelUpMenu",
        )
        self.assertEqual(
            self.server.requests,
            [
                "load_game_record%TestFarm_123",
                "observe_v2_light%-1",
                "observe_v2_light%-1",
            ],
        )

    def test_rejects_commands_containing_protocol_delimiters(self) -> None:
        with self.assertRaisesRegex(ModProtocolError, "newline"):
            self.client.send("observe_v2_light%-1\nexit_title")


if __name__ == "__main__":
    unittest.main()
