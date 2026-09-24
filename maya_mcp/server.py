"""Run with python -m maya_mcp.server; stdout is reserved for MCP."""
import asyncio
import json
from typing import Any

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import CallToolResult, ImageContent, TextContent

from .connection import request

mcp = FastMCP("Maya MCP", instructions=(
    "Control the user's running Maya. Query status and scene before edits. "
    "Preserve existing animation unless the user requests changes. "
    "Use list_maya_tools to discover schemas then call_maya_tool. "
    "Python/MEL can execute arbitrary code: use only for the user's requested work. "
    "Never create/open a scene or save over a file without user intent. "
    "A timeout does not prove an operation failed: inspect state before retrying. "
    "Undo chunks cover Maya undoable edits, not file writes or all plugin effects."
    " 用户说‘创建自定义身体绑定’时，调用 create_custom_body_rig，可指定 segment_count 和 height，默认四节。"
))


async def call(method, params=None):
    return await asyncio.to_thread(request, method, params)


@mcp.tool()
async def get_maya_status() -> dict:
    """Check the connected Maya version, process, scene and available tool count."""
    return await call("status")


@mcp.tool()
async def get_scene_info(limit: int = 100) -> dict:
    """Read selection, roots, cameras, frame and timeline without modifying the scene."""
    return await call("scene", {"limit": limit})


@mcp.tool()
async def get_object_info(name: str) -> dict:
    """Inspect a node's hierarchy and world transforms; use full paths if ambiguous."""
    return await call("object", {"name": name})


@mcp.tool()
async def execute_maya_code(code: str) -> dict:
    """Execute Python in Maya's MAIN THREAD. cmds is provided; assign result for structured output.

    stdout/stderr are returned. Undoable edits form the MayaMCP_Python chunk.
    Failed code may have partially modified the scene; inspect before retrying.
    """
    return await call("python", {"code": code})


@mcp.tool()
async def execute_mel(code: str) -> dict:
    """Execute MEL on Maya's main thread in undo chunk MayaMCP_MEL."""
    return await call("mel", {"code": code})


@mcp.tool()
async def get_viewport_screenshot(max_size: int = 1280) -> Image:
    """Return the active Maya viewport as a native image. Requires interactive Maya."""
    import base64
    result = await call("screenshot", {"max_size": max_size})
    return Image(data=base64.b64decode(result["data_b64"]), format="png")


@mcp.tool()
async def list_maya_tools(query: str = "", category: str = "") -> list:
    """Discover Maya Agent tools and their exact JSON argument schemas. Filter by keyword/category.

    Includes modeling, UV, rigging, animation, materials, lighting, export and scripting.
    """
    return await call("list_tools", {"query": query, "category": category})


@mcp.tool()
async def call_maya_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Execute a discovered Maya tool. Read its schema first. Edits use MayaMCP_<name> undo chunk.

    Approval belongs to the MCP client; this bypasses Maya Agent chat confirmation dialogs.
    """
    result = await call("call_tool", {"name": name, "arguments": arguments})
    images = result.pop("images", [])
    content = [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
    content.extend(ImageContent(type="image", data=i["data_b64"], mimeType=i["mime"]) for i in images)
    return CallToolResult(content=content, isError=not result.get("ok", False))


@mcp.tool()
async def create_custom_body_rig(namespace: str = "customBody", on_conflict: str = "increment",
                                 segment_count: int = 4, height: float = 6.0) -> CallToolResult:
    """创建自定义身体绑定：2–64 根骨骼及同数量控制器，矩阵驱动和旋转混合。

    用户说“创建自定义身体绑定”时使用。默认重名自动编号；当前仅支持厘米场景。
    segment_count 含髋部和胸部；height 是总高度（厘米，默认 6）。默认四节保留原版行为。
    参数仅用于新建，保留已有绑定、动画和蒙皮。后续扩展集中在 maya_agent.rigs.custom_body 模块。
    """
    return await call_maya_tool("create_custom_body_rig", {"namespace": namespace, "on_conflict": on_conflict,
                                                        "segment_count": segment_count, "height": height})


@mcp.tool()
async def undo_maya_operation(expected_chunk: str) -> dict:
    """Undo only if the undo head exactly matches this MayaMCP_ chunk, protecting newer user edits."""
    return await call("undo", {"expected_chunk": expected_chunk})


if __name__ == "__main__":
    mcp.run(transport="stdio")
