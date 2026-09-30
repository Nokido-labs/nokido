import asyncio
import json
import os
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

async def test_build_handler():
    print("Testing handle_build_new_app...")
    from forge_handler_build import handle_build_new_app
    
    # Mocking necessary parts if needed or just run a simple case
    # This will actually try to call the LLM if not mocked.
    # In this environment, we should be careful.
    
    # Simple goal that shouldn't trigger GOAP but the build loop
    goal = "test_project create a hello world script"
    
    # We won't actually run it to avoid real LLM calls and potential timeouts in tests
    # But we can test the import and function existence
    assert callable(handle_build_new_app)
    print("Handler is callable.")

if __name__ == "__main__":
    asyncio.run(test_build_handler())
