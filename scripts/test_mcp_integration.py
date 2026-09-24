"""End-to-end official MCP client -> stdio server -> socket -> real Maya 2024."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maya_mcp.connection import request


def text_data(response):
    assert not response.isError, response
    return json.loads(next(c.text for c in response.content if c.type == "text"))


async def exercise():
    params = StdioServerParameters(command=sys.executable, args=["-m", "maya_mcp.server"], cwd=str(ROOT), env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert len(tools.tools) == 10
            status = text_data(await session.call_tool("get_maya_status", {}))
            assert status["maya_version"].startswith("2024") and status["batch"]
            initial = text_data(await session.call_tool("get_scene_info", {}))
            built = text_data(await session.call_tool("execute_maya_code", {"code":
                "node = cmds.polyCube(name='MCP_IntegrationCube')[0]\n"
                "cmds.setKeyframe(node, attribute='translateX', time=1, value=0)\n"
                "cmds.setKeyframe(node, attribute='translateX', time=24, value=5)\n"
                "print('中文连接测试')\n"
                "result = {'name': node, 'keys': cmds.keyframe(node, attribute='translateX', query=True, keyframeCount=True)}"}))
            assert built["result"]["keys"] == 2
            assert "中文连接测试" in built["stdout"]
            info = text_data(await session.call_tool("get_object_info", {"name": "MCP_IntegrationCube"}))
            assert info["type"] == "transform"
            undo = text_data(await session.call_tool("undo_maya_operation", {"expected_chunk": "MayaMCP_Python"}))
            assert undo["undone"] == "MayaMCP_Python"
            scene = text_data(await session.call_tool("get_scene_info", {}))
            assert scene["roots"] == initial["roots"]
            schemas_response = await session.call_tool("list_maya_tools", {"query": "create_primitive"})
            # FastMCP list return is encoded as one text content block per element.
            schemas = [json.loads(c.text) for c in schemas_response.content if c.type == "text"]
            assert any(s.get("name") == "create_primitive" for s in schemas)
            created = text_data(await session.call_tool("call_maya_tool", {"name": "create_primitive", "arguments": {"primitive": "cube", "name": "MCP_ToolCube"}}))
            assert created["ok"], created
            undone = text_data(await session.call_tool("undo_maya_operation", {"expected_chunk": "MayaMCP_create_primitive"}))
            assert undone["undone"]
            # Errors must remain errors in the MCP protocol.
            failure = await session.call_tool("call_maya_tool", {"name": "get_mesh_stats", "arguments": {"name": "DOES_NOT_EXIST"}})
            assert failure.isError
            rejected = await session.call_tool("undo_maya_operation", {"expected_chunk": "unrelated_user_edit"})
            assert rejected.isError
            mel = text_data(await session.call_tool("execute_mel", {"code": "about -version"}))
            assert mel["result"].startswith("2024")
            final = text_data(await session.call_tool("get_scene_info", {}))
            assert final["roots"] == initial["roots"]
            return {"mcp_tools": len(tools.tools), "maya_tools": status["tool_count"],
                    "maya_version": status["maya_version"], "checks": ["MCP initialize/list/call", "real Maya scene query", "Python Unicode output", "create mesh and two animation keys", "object inspection", "undo restores roots", "registry schema discovery", "registry tool execution and undo", "MCP error propagation", "undo guard", "MEL execution"]}


def main():
    with tempfile.TemporaryDirectory(prefix="maya_mcp_test_") as directory:
        temp = Path(directory)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = temp / "connection.json"
        config.write_text(json.dumps({"host": "127.0.0.1", "port": port, "token": secrets.token_hex(32)}), encoding="utf-8")
        os.environ["MAYA_MCP_CONFIG"] = str(config)
        os.environ["MAYA_MCP_TEST_STOP"] = str(temp / "stop")
        # Separate app dir prevents startup hooks/preferences from the GUI session being loaded.
        env = dict(os.environ, MAYA_APP_DIR=str(temp / "maya"), MAYA_DISABLE_CIP="1", MAYA_DISABLE_CER="1")
        mayapy = sys.argv[1]
        artifacts = ROOT / "outputs" / "mcp-tests"
        artifacts.mkdir(parents=True, exist_ok=True)
        with (artifacts / "maya-host.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([mayapy, str(ROOT / "scripts" / "mcp_standalone_host.py")], env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                until = time.monotonic() + 80
                while time.monotonic() < until:
                    if process.poll() is not None:
                        raise RuntimeError("Maya host exited; see outputs/mcp-tests/maya-host.log")
                    try:
                        request("status", timeout=2)
                        break
                    except (OSError, RuntimeError):
                        time.sleep(.5)
                else:
                    raise RuntimeError("Maya startup timed out")
                report = asyncio.run(exercise())
                (artifacts / "integration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(report, ensure_ascii=False, indent=2))
            finally:
                (temp / "stop").touch()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
