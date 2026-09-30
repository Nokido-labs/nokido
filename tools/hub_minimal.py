"""Hub minimal Nokido - approach Windows-friendly sans asyncio.run."""

import os
import sys

sys.path.insert(0, "app")
sys.path.insert(0, "tools")
os.chdir(str(__import__("pathlib").Path(__file__).resolve().parents[1]))

import asyncio

# Build l app
from nokido_agent.tools.nokido_hub import HUB_HOST, HUB_PORT, _build_app

# Set Windows event loop policy AVANT toute creation de loop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
app = loop.run_until_complete(_build_app())
print(f"[hub_minimal] App built OK on {HUB_HOST}:{HUB_PORT}")

# Cree uvicorn config + serveur manuellement (pas uvicorn.run)
import uvicorn

config = uvicorn.Config(
    app=app,
    host=HUB_HOST,
    port=HUB_PORT,
    log_level="info",
    loop="asyncio",
    use_colors=False,
)
server = uvicorn.Server(config)

# Run dans le loop existant (evite asyncio.run interne)
try:
    loop.run_until_complete(server.serve())
except KeyboardInterrupt:
    print("[hub_minimal] CTRL+C received, shutting down...")
finally:
    loop.close()
