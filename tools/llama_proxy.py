"""llama_proxy.py — shim: delegates to forge_demand_proxy --service llama"""

import subprocess
import sys
from pathlib import Path

subprocess.run(
    [sys.executable, str(Path(__file__).parent / "forge_demand_proxy.py"), "--service", "llama"],
    check=True,
)
