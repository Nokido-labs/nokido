"""
tests/verify_orchestrator.py
Validation muette : ecrit OK ou l erreur dans sandbox/status.txt
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
APP  = ROOT / 'app'
sys.path.insert(0, str(APP))

STATUS = ROOT / 'sandbox' / 'status.txt'

try:
    import forge_context
    from forge_orchestrator import OrchestratorManager

    orc = forge_context.orchestrator
    if orc is None:
        # Forcer init si absent
        from forge_orchestrator import get_orchestrator
        orc = get_orchestrator()
        forge_context.orchestrator = orc

    assert isinstance(orc, OrchestratorManager), f"Type inattendu: {type(orc)}"

    status = orc.get_status()
    assert isinstance(status, dict), f"get_status() ne retourne pas un dict: {status}"
    assert 'mode' in status, f"Cle 'mode' absente: {status}"

    STATUS.write_text(
        f"OK\n"
        f"orchestrator: {type(orc).__name__}\n"
        f"get_status: {status}",
        encoding='utf-8'
    )

except Exception as e:
    import traceback
    STATUS.write_text(f"FAIL\n{e}\n{traceback.format_exc()}", encoding='utf-8')
