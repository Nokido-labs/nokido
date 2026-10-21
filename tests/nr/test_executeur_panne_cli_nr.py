# -*- coding: utf-8 -*-
"""NR (19/10, essai Mistral job_10971233) : une sortie de CLI en PANNE n'est ni un succes ni du « travail non committe ».

Mesure : le harness Vibe a rendu {"ok": true, "output": "Error: Client error '429 Too Many Requests' ..."} ; l'executeur
a repris ok=True, puis a compte le dossier de session `.vibe/` comme 1 fichier non committe -> « NON LIVRE apres delegation
(travail laisse non committe) ». Le verdict au registre etait juste (INCONNU via _RE_PANNE_INFRA), mais le motif et le
succes du harness etaient faux. Une sortie qui COMMENCE par une erreur de fournisseur est une panne ; un rapport qui parle
de 429 n'en est pas une. Les dossiers de configuration d'agent (_CONFIG_AGENT) ne sont pas du travail.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402

SORTIE_429 = ("Error: Client error '429 Too Many Requests' for url 'https://api.mistral.ai/v1/chat/completions'\r\n"
              "For more information check: ...: Rate limit exceeded\r\n")


def test_une_sortie_qui_commence_par_une_erreur_fournisseur_est_une_panne():
    assert "429" in (T._panne_cli(SORTIE_429) or "")
    rapport = "J'ai lu les 3 fichiers. Le hook leve PermissionError ; un 429 Too Many Requests n'y apparait pas.\n" * 3
    assert T._panne_cli(rapport) is None
    assert T._panne_cli("") is None


def test_le_motif_de_reaffectation_nomme_la_panne():
    effet = "[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 0"
    assert T._motif_reaffectation_apres(False, effet, SORTIE_429).startswith("PANNE FOURNISSEUR")


def test_les_dossiers_de_config_agent_ne_comptent_pas_comme_travail(tmp_path):
    def g(*a):
        return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(tmp_path), *a],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
    g("init", "-q")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
    (tmp_path / ".vibe").mkdir()
    (tmp_path / ".vibe" / "session.log").write_text("x", encoding="utf-8")
    assert T._etat_git(str(tmp_path))[1] == 0
    (tmp_path / "rapport.json").write_text("{}", encoding="utf-8")
    assert T._etat_git(str(tmp_path))[1] == 1     # temoin positif : un vrai fichier compte toujours
