"""Read-only end-to-end check against the running Maya GUI, including a native MCP image."""
import asyncio
import base64
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "mcp-tests"


def unpack(response):
    if response.isError:
        raise RuntimeError(str(response.content))
    return json.loads(next(c.text for c in response.content if c.type == "text"))


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "scripts" / "run_maya_mcp.py")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            report = {"mcp_tool_count": len(tools.tools)}
            report["status"] = unpack(await session.call_tool("get_maya_status", {}))
            before = unpack(await session.call_tool("get_scene_info", {}))
            report["scene"] = before
            report["python"] = unpack(await session.call_tool("execute_maya_code", {"code": "import threading\nresult = {'main_thread': threading.current_thread() is threading.main_thread(), 'version': cmds.about(version=True)}"}))
            assert report["python"]["result"]["main_thread"]
            report["mel"] = unpack(await session.call_tool("execute_mel", {"code": "about -version"}))
            report["registry_scene"] = unpack(await session.call_tool("call_maya_tool", {"name": "get_scene_info", "arguments": {}}))
            schemas = await session.call_tool("list_maya_tools", {"query": "set_keyframe"})
            assert not schemas.isError and any("set_keyframe" in c.text for c in schemas.content if c.type == "text")
            screenshot = await session.call_tool("get_viewport_screenshot", {"max_size": 960})
            if screenshot.isError:
                raise RuntimeError(str(screenshot.content))
            image = next(c for c in screenshot.content if c.type == "image")
            raw = base64.b64decode(image.data)
            assert raw.startswith(b"\x89PNG")
            OUTPUT.mkdir(parents=True, exist_ok=True)
            path = OUTPUT / "live-viewport.png"
            path.write_bytes(raw)
            report["screenshot"] = {"path": str(path), "bytes": len(raw), "mime": image.mimeType}
            after = unpack(await session.call_tool("get_scene_info", {}))
            assert before == after, "Read-only verification changed scene summary"
            report["scene_summary_unchanged"] = True
            (OUTPUT / "live-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
