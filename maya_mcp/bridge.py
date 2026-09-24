"""Standard-library socket server; all Maya work is drained on the main thread."""
import hmac
import queue
import socketserver
import threading
import time

from .connection import encode_packet, ensure_settings, read_packet

_active = None


class Job:
    def __init__(self, method, params, timeout):
        self.method, self.params = method, params
        self.deadline = time.monotonic() + timeout
        self.state = "queued"
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.result = None


class Bridge:
    def __init__(self, dispatch, config):
        self.dispatch = dispatch
        self.jobs = queue.Queue(maxsize=64)
        self.owner = threading.get_ident()
        self.closed = False
        self.config = config
        self.timer = None
        bridge = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(10)
                request_id = None
                try:
                    packet = read_packet(self.rfile)
                    request_id = packet.get("id")
                    token = packet.get("token", "")
                    if not isinstance(token, str) or not hmac.compare_digest(token, config["token"]):
                        raise ValueError("Unauthorized")
                    params = packet.get("params", {})
                    if not isinstance(params, dict):
                        raise ValueError("params must be an object")
                    timeout = max(1, min(float(packet.get("timeout", 120)), 600))
                    if bridge.closed:
                        raise RuntimeError("Maya bridge is stopping")
                    job = Job(packet.get("method"), params, timeout)
                    bridge.jobs.put_nowait(job)
                    if not job.done.wait(timeout):
                        with job.lock:
                            if job.state == "queued":
                                job.state = "cancelled"
                                raise TimeoutError("Maya busy; queued command cancelled without execution")
                            if job.state != "done":
                                raise TimeoutError("Command is still running; result unknown. Inspect scene before retrying.")
                    response = dict(job.result)
                    response["id"] = request_id
                except Exception as exc:
                    response = {"id": request_id, "ok": False, "error": str(exc)}
                try:
                    try:
                        data = encode_packet(response)
                    except ValueError as exc:
                        data = encode_packet({"id": request_id, "ok": False, "error": str(exc)})
                    self.wfile.write(data)
                except OSError:
                    pass

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = False

        if config["host"] != "127.0.0.1":
            raise ValueError("Only loopback is allowed")
        self.server = Server((config["host"], config["port"]), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="MayaMCP", daemon=True)
        self.thread.start()

    def drain(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("Maya operations must run on the bridge's main thread")
        # One job per tick lets Maya UI process input between operations.
        try:
            job = self.jobs.get_nowait()
        except queue.Empty:
            return
        with job.lock:
            if job.state == "cancelled":
                return
            if self.closed or time.monotonic() >= job.deadline:
                job.result = {"ok": False, "error": "Queued command expired without execution"}
                job.state = "done"
                job.done.set()
                return
            job.state = "running"
        try:
            result = {"ok": True, "data": self.dispatch(job.method, job.params)}
        except Exception as exc:
            result = {"ok": False, "error": "{}: {}".format(type(exc).__name__, exc)}
        with job.lock:
            job.result = result
            job.state = "done"
            job.done.set()

    def stop(self):
        self.closed = True
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
        while not self.jobs.empty():
            job = self.jobs.get_nowait()
            with job.lock:
                job.state = "done"
                job.result = {"ok": False, "error": "Bridge stopped; queued command cancelled"}
                job.done.set()
        self.server.shutdown()
        self.server.server_close()


def start(use_qt=True):
    global _active
    if _active is not None:
        return _active
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Call start() from Maya's main thread")
    from .maya_adapter import dispatch, prepare
    prepare()
    timer = None
    if use_qt:
        try:
            from PySide6.QtCore import QTimer
        except ImportError:
            from PySide2.QtCore import QTimer
        timer = QTimer()
    instance = Bridge(dispatch, ensure_settings())
    instance.timer = timer
    if timer is not None:
        timer.timeout.connect(instance.drain)
        timer.start(30)
    _active = instance
    print("[Maya MCP] Listening on 127.0.0.1:{}".format(instance.server.server_address[1]))
    return instance


def stop():
    global _active
    if _active is not None:
        _active.stop()
        _active = None
        print("[Maya MCP] Stopped")
