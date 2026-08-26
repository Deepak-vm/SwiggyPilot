import asyncio
from backend.mcp.swiggy_client import get_tools

tools = asyncio.run(get_tools(["food"]))
print([t.name for t in tools])
