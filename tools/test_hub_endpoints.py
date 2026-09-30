"""Appelle directement les endpoints /api/hub/overview + /api/hub/federation
(async, env serveur) -> prouve qu'ils renvoient de la VRAIE donnee. Trusted_script."""
import sys
import asyncio

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])
for p in (ROOT, ROOT + "/app"):
    if p not in sys.path:
        sys.path.insert(0, p)
from app.web_hub.app import api_hub_overview, api_hub_federation  # noqa: E402


async def main():
    ov = await api_hub_overview()
    fed = await api_hub_federation()
    print("OVERVIEW :", ov.body.decode("utf-8", "replace")[:500])
    print("FEDERATION (n) :", fed.body.decode("utf-8", "replace")[:500])


asyncio.run(main())
