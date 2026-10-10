"""Transport guarantees independent of a Max installation."""
import json
import socket
import threading
import time
import unittest

from max_mcp.bridge import Bridge


class MaxBridgeTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.bridge = Bridge(self.dispatch, port=0, token="test")
        self.port = self.bridge.server.server_address[1]

    def dispatch(self, method, params):
        self.calls.append((method, params))
        if method == "bad_result":
            return object()
        return params

    def tearDown(self):
        self.bridge.stop()

    def exchange(self, packet, drain=True):
        responses = []
        def client():
            with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
                sock.sendall((json.dumps(packet) + "\n").encode())
                responses.append(json.loads(sock.makefile("rb").readline()))
        thread = threading.Thread(target=client)
        thread.start()
        deadline = time.monotonic() + 5
        while thread.is_alive() and time.monotonic() < deadline:
            if drain:
                self.bridge.drain()
            thread.join(.01)
        self.assertFalse(thread.is_alive())
        return responses[0]

    def test_unicode_roundtrip(self):
        reply = self.exchange({"token": "test", "id": 2, "method": "echo", "params": {"name": "骨骼"}})
        self.assertEqual(reply, {"id": 2, "ok": True, "data": {"name": "骨骼"}})

    def test_bad_token_does_not_execute(self):
        self.assertFalse(self.exchange({"token": "wrong"})["ok"])
        self.assertEqual(self.calls, [])

    def test_expired_job_does_not_execute_later(self):
        reply = self.exchange({"token": "test", "method": "edit", "timeout": 1}, drain=False)
        self.assertFalse(reply["ok"])
        self.bridge.drain()
        self.assertEqual(self.calls, [])

    def test_unserializable_result_reports_error(self):
        reply = self.exchange({"token": "test", "method": "bad_result"})
        self.assertFalse(reply["ok"])
        self.assertIn("JSON serializable", reply["error"])

    def test_reject_remote_listening(self):
        with self.assertRaises(ValueError):
            Bridge(self.dispatch, host="0.0.0.0", port=0)
