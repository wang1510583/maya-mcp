"""Start the stdio server independently of the caller's working directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from max_mcp.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
