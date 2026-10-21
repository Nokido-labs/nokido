"""NR 18/10 -- le corps reaffecte lui-meme une tache NON LIVREE (defaut d'orchestration n°5 mesure le 18/10).

Mesure du 18/10 : 5 taches terminees « done » SANS aucun commit (AGY sous sandbox, WORKER_CODE, GLM en panne fournisseur,
GPTOSS en timeout ACP, Codex pytest plante) ; `_juger_livraison` les nommait bien (« [NON LIVRE] », « commits produits : 0 »)
mais `_reaffecter` n'etait appele qu'AVANT l'execution (quota, indisponibilite). Chaque reprise etait faite a la main.

Contrat :
  * `_motif_reaffectation_apres(ok, effet)` rend un motif quand la delegation a ECHOUE sans rien livrer (0 commit),
    et None sinon -- une livraison existante, meme refusee (tests touches, livraison vide), se RELIT, elle ne se
    reaffecte pas en silence ;
  * le chemin de fin de delegation l'appelle et passe la tache a `_reaffecter` (anti ping-pong deja en place).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402

NON_LIVRE = ("[effet observe] commits produits : 0 (aaa..aaa) ; fichiers non commites : 5 ; "
             "[NON LIVRE] aucun commit propre, 5 fichier(s) non committe(s)")
PANNE = "[effet observe] commits produits : 0 (bbb..bbb) ; fichiers non commites : 0"
LIVRE_REFUSE = ("[effet observe] commits produits : 1 (ccc..ddd) ; fichiers non commites : 0 ; "
                "[TESTS TOUCHES] tests/nr/x.py -- un delegue ne reussit pas en modifiant un test existant")


def test_un_echec_sans_livraison_donne_un_motif():
    m = te._motif_reaffectation_apres(False, NON_LIVRE)
    assert m and "NON LIVRE" in m
    assert te._motif_reaffectation_apres(False, PANNE), "0 commit + echec (panne fournisseur, timeout) = a reaffecter"


def test_une_reussite_ou_une_livraison_a_relire_ne_se_reaffecte_pas():
    assert te._motif_reaffectation_apres(True, "[effet observe] commits produits : 1 (a..b)") is None
    assert te._motif_reaffectation_apres(False, LIVRE_REFUSE) is None, "un commit existe : il se RELIT"


def test_un_effet_illisible_ne_declenche_rien():
    """UNKNOWN n'est pas NO : sans compte de commits lisible, on ne deplace pas une tache a l'aveugle."""
    assert te._motif_reaffectation_apres(False, "") is None
    assert te._motif_reaffectation_apres(False, "effet illisible") is None


def test_le_chemin_de_fin_branche_la_reaffectation():
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8", errors="replace")
    appels = [m.start() for m in re.finditer(r"_motif_reaffectation_apres\(", src)]
    assert len(appels) >= 2, "la decision existe mais n'est appelee nulle part"
    assert any("_reaffecter(" in src[a:a + 600] for a in appels[1:]), (
        "un appel a _motif_reaffectation_apres doit etre suivi de _reaffecter(task, motif)")
