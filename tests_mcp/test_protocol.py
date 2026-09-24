"""Real stdio MCP round trips against a simulated Maya dispatcher (not Maya verification)."""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from maya_mcp.bridge import Bridge

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII="


def test_stdio_protocol_images_and_errors(tmp_path):
    seen = []
    def dispatch(method, params):
        seen.append(method)
        if method == "status":
            return {"connected": True, "simulated": True}
        if method == "screenshot":
            return {"mime": "image/png", "data_b64": PNG}
        if method == "call_tool":
            return {"ok": False, "error": "fixture error", "images": []}
        if method == "list_tools":
            return [{"name": "example", "parameters": {"type": "object"}}]
        raise ValueError("fixture rejected method")

    cfg = {"host": "127.0.0.1", "port": 0, "token": "t" * 64}
    bridge = Bridge(dispatch, cfg)
    cfg["port"] = bridge.server.server_address[1]
    config = tmp_path / "connection.json"
    config.write_text(json.dumps(cfg), encoding="utf-8")

    async def run():
        async def pump():
            while True:
                bridge.drain()
                await asyncio.sleep(.005)
        pumping = asyncio.create_task(pump())
        params = StdioServerParameters(command=sys.executable, args=["-m", "maya_mcp.server"],
                                       cwd=str(Path(__file__).resolve().parents[1]),
                                       env=dict(os.environ, MAYA_MCP_CONFIG=str(config)))
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    catalog = await session.list_tools()
                    assert len(catalog.tools) == 10
                    status = await session.call_tool("get_maya_status", {})
                    assert not status.isError
                    assert json.loads(status.content[0].text)["simulated"]
                    shot = await session.call_tool("get_viewport_screenshot", {})
                    assert not shot.isError
                    assert shot.content[0].type == "image"
                    assert base64.b64decode(shot.content[0].data).startswith(b"\x89PNG")
                    error = await session.call_tool("call_maya_tool", {"name": "fixture", "arguments": {}})
                    assert error.isError
                    error = await session.call_tool("execute_maya_code", {"code": "fixture"})
                    assert error.isError
                    schemas = await session.call_tool("list_maya_tools", {})
                    assert not schemas.isError
                    assert "example" in schemas.content[0].text
        finally:
            pumping.cancel()
            try:
                await pumping
            except asyncio.CancelledError:
                pass
    try:
        asyncio.run(run())
    finally:
        bridge.stop()
    assert seen.count("python") == 1
