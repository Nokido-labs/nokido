"""NR 28/10 (recette reelle) : un agent ACP mort se DIT (rc), il ne rend pas « OSError 22 Invalid argument ».

Mesure : la session claude ouverte par NokidoAcpWorker est morte ~12 s apres session/new, sans une ligne de stderr ;
le prompt suivant est tombe sur `stdin.write` -> OSError(22). Ni l'heure de la mort ni son code n'etaient lisibles.
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_acp_client as C  # noqa: E402


def _agent_qui_sort(code, msg=""):
    journal = []
    cli = C.ACPClient(cmd=[sys.executable, "-c", "import sys; sys.stderr.write(%r); sys.exit(%d)" % (msg, code)],
                      on_log=journal.append)
    cli.start()   # le processus se lance par start(), pas par le constructeur
    t0 = time.time()
    while cli.proc.poll() is None and time.time() - t0 < 20:
        time.sleep(0.05)
    time.sleep(0.3)   # laisser les fils de lecture finir
    return cli, journal


def test_fin_du_flux_journalise_le_code_de_sortie():
    _cli, journal = _agent_qui_sort(3)
    assert any("rc=3" in m for m in journal), journal


def test_ecrire_a_un_agent_mort_dit_le_code_et_le_stderr():
    cli, _ = _agent_qui_sort(3, "auth manquante\n")
    with pytest.raises(RuntimeError) as e:
        cli._send({"jsonrpc": "2.0", "id": 1, "method": "session/prompt", "params": {}})
    assert "rc=3" in str(e.value) and "auth manquante" in str(e.value)
