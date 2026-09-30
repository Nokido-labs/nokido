import pytest
import asyncio
from app.forge_code_loops import ErrorMemory, LoopState, ImprovementOrchestrator

def test_error_memory_record_version():
    mem = ErrorMemory()
    mem.record_version("1.0", 5, 5.0, "init", "ok")
    assert mem.best_version == "1.0"
    assert mem.best_error_count == 5
    
    # Meilleure version
    mem.record_version("1.1", 2, 8.0, "fix", "ok")
    assert mem.best_version == "1.1"
    assert mem.best_error_count == 2
    
    # Pire version (ne met pas à jour le best)
    mem.record_version("1.2", 10, 2.0, "bad fix", "ok")
    assert mem.best_version == "1.1"

def test_error_memory_context_build():
    mem = ErrorMemory()
    mem.record_success("Fixed null pointer")
    mem.record_failure("Tried global variable")
    mem.error_patterns.append("Missing import os")
    
    ctx = mem.build_prompt_context()
    assert "Fixed null pointer" in ctx
    assert "Tried global variable" in ctx
    assert "Missing import os" in ctx

@pytest.mark.asyncio
async def test_improvement_orchestrator_init():
    orc = ImprovementOrchestrator("http://mock", "http://mock")
    assert orc._running is False
    assert orc.state is not None
