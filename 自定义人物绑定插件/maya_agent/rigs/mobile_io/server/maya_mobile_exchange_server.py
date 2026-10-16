#!/usr/bin/env python3
"""Small authenticated IPv6/HTTP file service for Maya <-> Android exchange.

It deliberately exposes only JSON/mobile project files from one directory.
Use HTTPS (or Tailscale) when the phone is outside the trusted LAN.
"""
import argparse, hashlib, json, os, re, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
import socket, ssl

DEFAULT_ROOT = "/home/wangjiafeng/电脑maya和安卓maya互通文件"
MAX_BYTES = 128 * 1024 * 1024
# User-facing names may be Chinese; path separators/control characters remain forbidden.
NAME_RE = re.compile(r"^[^/\\\x00-\x1f]+\.json$", re.UNICODE)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def metadata(path):
    """Read only identity fields so clients can filter files by role safely."""
    try:
        with path.open("r", encoding="utf-8-sig") as stream: data=json.load(stream)
        result={"format":data.get("format"),"characterId":data.get("characterId"),"rigVersion":data.get("rigVersion"),"sourceSnapshotSha256":data.get("sourceSnapshotSha256")}
        if data.get("format")=="maya-mobile-project":
            try:
                snap=json.loads(data.get("snapshotJson", "{}")); result["characterId"]=snap.get("characterId",result["characterId"]); result["rigVersion"]=snap.get("rigVersion",result["rigVersion"])
                result["sourceSnapshotSha256"]=(data.get("solver") or {}).get("sourceSnapshotSha256")
            except Exception: pass
        return {k:v for k,v in result.items() if v is not None}
    except Exception: return {}

def make_handler(root, token):
    root = Path(root).expanduser().resolve(); root.mkdir(parents=True, exist_ok=True)
    file_lock = threading.RLock()
    class Handler(BaseHTTPRequestHandler):
        server_version = "MayaMobileExchange/1.0"
        def log_message(self, fmt, *args):
            print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)
        def auth(self):
            return bool(token) and self.headers.get("X-Exchange-Token", "") == token
        def send_json(self, code, value):
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def fail(self, code, message): self.send_json(code, {"ok": False, "error": message})
        def name(self):
            value = unquote(urlparse(self.path).path.rsplit("/", 1)[-1])
            if not NAME_RE.fullmatch(value) or Path(value).name != value: raise ValueError("只允许 JSON / mobile.json 文件名")
            return value
        def do_GET(self):
            if not self.auth(): return self.fail(401, "令牌错误")
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/health": return self.send_json(200, {"ok": True, "service": "maya-mobile-exchange", "version": 1, "root": str(root)})
                if parsed.path == "/api/files":
                    rows=[]
                    for p in sorted(root.iterdir(), key=lambda x:x.name.lower()):
                        if p.is_file() and NAME_RE.fullmatch(p.name):
                            row={"name":p.name,"size":p.stat().st_size,"mtime":p.stat().st_mtime,"sha256":sha256(p)};row.update(metadata(p));rows.append(row)
                    return self.send_json(200, {"ok": True, "files": rows})
                if parsed.path.startswith("/api/files/"):
                    p=root/self.name()
                    if not p.is_file(): return self.fail(404, "文件不存在")
                    size=p.stat().st_size; self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(size)); self.send_header("X-File-Sha256", sha256(p)); self.end_headers()
                    with p.open("rb") as f:
                        for block in iter(lambda:f.read(1024*1024), b""): self.wfile.write(block)
                    return
                self.fail(404, "接口不存在")
            except ValueError as e: self.fail(400, str(e))
            except Exception as e: self.fail(500, str(e))
        def do_PUT(self):
            if not self.auth(): return self.fail(401, "令牌错误")
            try:
                if not urlparse(self.path).path.startswith("/api/files/"): return self.fail(404, "接口不存在")
                p=root/self.name(); length=int(self.headers.get("Content-Length", "-1"))
                if length < 0 or length > MAX_BYTES: return self.fail(413, "文件过大或缺少长度")
                fd,tmp=tempfile.mkstemp(prefix=".upload-", dir=str(root)); os.close(fd)
                try:
                    remaining=length
                    with open(tmp,"wb") as out:
                        while remaining:
                            block=self.rfile.read(min(1024*1024,remaining))
                            if not block: raise IOError("上传提前结束")
                            out.write(block); remaining-=len(block)
                    with file_lock: os.replace(tmp,p)
                finally:
                    if os.path.exists(tmp): os.unlink(tmp)
                self.send_json(200,{"ok":True,"name":p.name,"size":p.stat().st_size,"sha256":sha256(p)})
            except (ValueError,IOError) as e: self.fail(400,str(e))
            except Exception as e: self.fail(500,str(e))
        def do_DELETE(self):
            if not self.auth(): return self.fail(401, "令牌错误")
            try:
                if not urlparse(self.path).path.startswith("/api/files/"): return self.fail(404, "接口不存在")
                p = root / self.name()
                with file_lock:
                    if p.is_symlink() or p.resolve().parent != root: return self.fail(400, "不能删除链接或目录外文件")
                    if not p.is_file(): return self.fail(404, "文件不存在，请刷新列表")
                    expected = self.headers.get("If-Match", "").strip('"')
                    if not expected: return self.fail(428, "缺少文件校验值，请刷新列表")
                    if expected != sha256(p): return self.fail(409, "文件已被更新，请刷新列表后重新确认删除")
                    p.unlink()
                self.send_json(200, {"ok": True, "name": p.name})
            except ValueError as e: self.fail(400, str(e))
            except Exception as e: self.fail(500, str(e))
    return Handler

class IPv6Server(ThreadingHTTPServer): address_family = socket.AF_INET6

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--host",default="::"); ap.add_argument("--port",type=int,default=8765); ap.add_argument("--root",default=DEFAULT_ROOT); ap.add_argument("--token",default=os.environ.get("MAYA_MOBILE_TOKEN", "")); ap.add_argument("--cert"); ap.add_argument("--key"); a=ap.parse_args()
    if not a.token: ap.error("必须通过 --token 或 MAYA_MOBILE_TOKEN 设置令牌")
    server=IPv6Server((a.host,a.port),make_handler(a.root,a.token))
    if bool(a.cert) != bool(a.key): ap.error("--cert 与 --key 必须同时提供")
    if a.cert: ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(a.cert,a.key);server.socket=ctx.wrap_socket(server.socket,server_side=True)
    print("Maya mobile exchange listening on [%s]:%s; root=%s"%(a.host,a.port,Path(a.root).resolve()),flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
if __name__ == "__main__": main()
