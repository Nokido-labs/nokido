"""
DEPRECATED: hardware_monitor.py → app/hardware/monitor.py

This is a backward-compatibility stub. All imports are redirected to the new location.
Phase 3 migration (2026-06-10): Module moved to organized package structure.
"""

from __future__ import annotations

# Re-export everything from the new location for backward compatibility
from hardware.monitor import *  # noqa: F401, F403

# If imported as __main__, run the new module
if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Run the actual module
    _app_dir = Path(__file__).parent
    _new_module = _app_dir / "hardware" / "monitor.py"
    
    import runpy
    runpy.run_path(str(_new_module), run_name="__main__")
