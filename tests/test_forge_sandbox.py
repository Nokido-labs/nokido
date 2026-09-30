import pytest
import asyncio
from app.forge_sandbox import SafeRunner, SandboxResult

@pytest.mark.asyncio
async def test_safe_runner_success():
    runner = SafeRunner(timeout=2.0)
    code = "print('Hello Sandbox')"
    success, stdout, stderr = await runner.run(code)
    assert success is True
    assert "Hello Sandbox" in stdout
    assert stderr == ""

@pytest.mark.asyncio
async def test_safe_runner_timeout():
    runner = SafeRunner(timeout=1.0)
    # Code qui boucle infiniment
    code = "import time\nwhile True: time.sleep(0.1)"
    success, stdout, stderr = await runner.run(code)
    assert success is False
    assert "Timeout" in stderr or "dépassé" in stderr

@pytest.mark.asyncio
async def test_safe_runner_error():
    runner = SafeRunner(timeout=2.0)
    code = "raise ValueError('Test Error')"
    success, stdout, stderr = await runner.run(code)
    assert success is False
    assert "Test Error" in stderr
