"""Entry point: `python -m groktimizer.mcp` (registered with grok at bootstrap)."""

from groktimizer.mcp.server import build_server

build_server().run()  # stdio transport
