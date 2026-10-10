"""MCP server for a running 3ds Max process."""
import asyncio

from mcp.server.fastmcp import FastMCP

from .connection import request

mcp = FastMCP("3ds Max MCP", instructions=(
    "Control the user's running 3ds Max through the local loopback bridge. "
    "Query the scene before edits. Preserve the current scene unless the user "
    "explicitly requests a change. MAXScript and Python execute on Max's main thread."
))


async def call(method, params=None, timeout=120):
    return await asyncio.to_thread(request, method, params, timeout)


@mcp.tool()
async def get_max_status() -> dict:
    """Read the connected Max version, scene path and bridge status."""
    return await call("status")


@mcp.tool()
async def get_scene_info(limit: int = 100) -> dict:
    """Read the current scene, selection, time range and top-level objects."""
    return await call("scene", {"limit": limit})


@mcp.tool()
async def execute_maxscript(code: str) -> dict:
    """Execute MAXScript on Max's main thread."""
    return await call("maxscript", {"code": code})


@mcp.tool()
async def execute_max_python(code: str) -> dict:
    """Execute embedded Python with pymxs.runtime available as rt."""
    return await call("python", {"code": code})


@mcp.tool()
async def export_bip(root: str, file_path: str, overwrite: bool = False) -> dict:
    """Export a Biped animation to a .bip file without saving the Max scene.

    Existing files are protected unless overwrite is explicitly enabled.
    """
    return await call("export_bip", {"root": root, "file_path": file_path, "overwrite": overwrite})


@mcp.tool()
async def load_bip(root: str, file_path: str) -> dict:
    """Load a .bip file onto a Biped root in the current temporary scene."""
    return await call("load_bip", {"root": root, "file_path": file_path})


@mcp.tool()
async def capture_biped(root: str, start: float, end: float, step: float = 1.0) -> dict:
    """Capture Biped animation with Figure Mode rest matrices for Maya retargeting.

    Temporarily enters Figure Mode to read rest matrices, then restores it.
    Does not save or replace the scene. Start with Figure Mode disabled.
    """
    return await call('capture_biped', dict(root=root,start=start,end=end,step=step),timeout=600)


@mcp.tool()
async def sample_biped(root: str, start: float, end: float, step: float = 1.0,
                       bones: list[str] | None = None) -> dict:
    """Return world matrices for Biped bones at sampled frames."""
    return await call("sample_biped", {"root": root, "start": start, "end": end,
                                        "step": step, "bones": bones or []}, timeout=600)


if __name__ == "__main__":
    mcp.run(transport="stdio")
