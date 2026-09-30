"""
tests/check_boot.py — Juge de Paix OrchestratorManager
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'app'))

# Reset cache modules
for k in list(sys.modules):
    if 'forge' in k: del sys.modules[k]

STATUS = ROOT / 'sandbox' / 'status.txt'

try:
    import forge_context
    from forge_orchestrator import OrchestratorManager, get_orchestrator

    # Simuler le boot
    forge_context.orchestrator = get_orchestrator()

    t = type(forge_context.orchestrator)
    print(f"STATUS: {t}")

    assert t is OrchestratorManager, f"Mauvais type: {t}"

    s = forge_context.orchestrator.get_status()
    assert 'mode' in s, f"get_status() invalide: {s}"

    result = f"OK\ntype: {t}\nget_status: {s}"
    print(result)
    STATUS.write_text(result, encoding='utf-8')

except Exception as e:
    import traceback as tb
    err = f"FAIL\n{e}\n{tb.format_exc()[-400:]}"
    print(err)
    STATUS.write_text(err, encoding='utf-8')
