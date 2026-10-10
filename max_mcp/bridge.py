"""Main-thread bridge loaded inside 3ds Max's embedded Python."""
import hmac
import json
import queue
import socketserver
import threading
import time

_active = None


class Job:
    def __init__(self, method, params, timeout):
        self.method, self.params = method, params
        self.deadline = time.monotonic() + timeout
        self.state = "queued"
        self.done = threading.Event()
        self.result = None
        self.lock = threading.Lock()


class Bridge:
    def __init__(self, dispatch, host="127.0.0.1", port=8766, token="max-mcp-local"):
        if host != "127.0.0.1":
            raise ValueError("Max MCP only accepts local loopback connections")
        self.dispatch, self.token = dispatch, token
        self.jobs = queue.Queue(maxsize=64)
        self.closed = False

        bridge = self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    self.connection.settimeout(10)
                    line = self.rfile.readline(8_000_001)
                    if len(line) > 8_000_000 or not line.endswith(b"\n"):
                        raise ValueError("Invalid or oversized request")
                    packet = json.loads(line.decode("utf-8"))
                    if not hmac.compare_digest(str(packet.get("token", "")), bridge.token):
                        raise ValueError("Unauthorized")
                    params = packet.get("params", {})
                    if not isinstance(params, dict):
                        raise ValueError("params must be an object")
                    timeout = max(1.0, min(float(packet.get("timeout", 120)), 600.0))
                    job = Job(packet.get("method"), params, timeout)
                    bridge.jobs.put_nowait(job)
                    if not job.done.wait(timeout):
                        raise TimeoutError("Max command is still running; inspect the scene before retrying")
                    response = dict(job.result)
                    response["id"] = packet.get("id")
                except Exception as exc:
                    response = {"id": None, "ok": False, "error": str(exc)}
                try:
                    payload = json.dumps(response, ensure_ascii=False, allow_nan=False)
                except (TypeError, ValueError):
                    payload = json.dumps({"ok": False, "error": "Result must be JSON serializable; convert Max objects to strings or lists"})
                self.wfile.write((payload + "\n").encode("utf-8"))

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = False

        self.server = Server((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       name="MaxMCP", daemon=True)
        self.thread.start()

    def drain(self):
        try:
            job = self.jobs.get_nowait()
        except queue.Empty:
            return
        with job.lock:
            if self.closed or time.monotonic() >= job.deadline:
                job.result = {"ok": False, "error": "Queued command expired"}
                job.done.set()
                return
            job.state = "running"
        try:
            job.result = {"ok": True, "data": self.dispatch(job.method, job.params)}
        except Exception as exc:
            job.result = {"ok": False, "error": "{}: {}".format(type(exc).__name__, exc)}
        job.state = "done"
        job.done.set()

    def stop(self):
        self.closed = True
        if hasattr(self, "timer"):
            self.timer.stop()
            self.timer.deleteLater()
        while not self.jobs.empty():
            self.drain()
        self.server.shutdown()
        self.server.server_close()


def start(port=8766, token="max-mcp-local"):
    global _active
    if _active is not None:
        return _active
    try:
        from PySide6.QtCore import QTimer
    except ImportError:
        from PySide2.QtCore import QTimer
    from . import max_adapter
    bridge = Bridge(lambda method, params: max_adapter.dispatch(method, params), port=port, token=token)
    timer = QTimer()
    timer.timeout.connect(bridge.drain)
    timer.start(30)
    bridge.timer = timer
    _active = bridge
    print("[Max MCP] Listening on 127.0.0.1:{}".format(port))
    return bridge


def stop():
    global _active
    if _active is not None:
        _active.stop()
        _active = None
